import csv
import hashlib
import io
from collections import Counter, defaultdict
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from app.models import ApplicationStatus, Institution, Program, QualificationAggregate, UploadBatch
from app.services.normalizers import (
    clean_text, normalize_institution, normalize_region, normalize_sport, normalized_key,
    split_qualification,
)


SUPPORTED_ENCODINGS = ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr')


class ImportValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(f'{len(errors):,}개 행에서 오류가 발견되어 저장하지 않았습니다.')

FIELD_LABELS = {
    'qualification': {
        'acquisition_date': '취득일 또는 취득 연도', 'region': '지역', 'sport': '종목',
        'qualification': '자격 종류·등급', 'count': '취득 인원/건수',
    },
    'program': {
        'institution': '기관명', 'region': '지역', 'address': '주소', 'institution_type': '기관 유형',
        'program': '프로그램명', 'sport': '현재 종목/분류', 'program_type': '프로그램 유형',
        'facility_industry': '시설 업종', 'target': '대상', 'weekdays': '요일',
        'time': '운영 시간', 'start_date': '시작일', 'end_date': '종료일', 'capacity': '정원',
        'status': '운영 상태',
    },
    'application': {
        'institution': '기관명', 'program': '프로그램명', 'sport': '종목', 'reference_date': '기준일/모집 연도',
        'capacity': '정원', 'applicants': '신청 인원', 'waitlist': '대기 인원',
    },
}

REQUIRED_FIELDS = {
    'qualification': {'acquisition_date', 'sport', 'qualification'},
    'program': {'institution', 'program'},
    'application': {'program', 'capacity', 'applicants'},
}

ALIASES = {
    'acquisition_date': ('ACQS_DE', 'SDYTRN_OPERTN_YEAR', '취득일', '연도'),
    'region': ('ACQS_AREA_NM', 'CTPRVN_NM', 'SIGNGU_NM', '지역'),
    'sport': ('QUALF_ITEM_NM', 'ITEM_NM', 'PROGRM_TY_NM', 'INDUTY_NM', '종목'),
    'program_type': ('PROGRM_TY_NM', 'PROGRAM_TYPE', '프로그램유형'),
    'facility_industry': ('INDUTY_NM', 'FCLTY_INDUTY_NM', '시설업종', '업종'),
    'qualification': ('QUALF_GRAD_NM', '자격종류', '자격'),
    'count': ('취득인원', '취득건수', '인원'),
    'institution': ('CNTER_NM', 'FCLTY_NM', '기관명', '센터명'),
    'address': ('FCLTY_ADDR', '주소'),
    'institution_type': ('FCLTY_TY_NM', 'FCLTY_FLAG_NM', '기관유형'),
    'program': ('COURSE_NM', 'PROGRM_NM', '프로그램명', '강좌명'),
    'target': ('PROGRM_TRGET_NM', '대상'),
    'weekdays': ('PROGRM_ESTBL_WKDAY_NM', '요일'),
    'time': ('PROGRM_ESTBL_TIZN_VALUE', '운영시간', '시간'),
    'start_date': ('COURSE_BEGIN_DE', 'PROGRM_BEGIN_DE', '시작일'),
    'end_date': ('COURSE_END_DE', 'PROGRM_END_DE', '종료일'),
    'capacity': ('PSNCPA_CO', 'PROGRM_RCRIT_NMPR_CO', '정원'),
    'status': ('운영상태', '상태'),
    'reference_date': ('기준일', '모집연도', '모집년도'),
    'applicants': ('신청인원', '접수인원', '등록인원'),
    'waitlist': ('대기인원', '대기자'),
}


def detect_encoding(path):
    sample = Path(path).open('rb').read(1024 * 1024)
    for encoding in SUPPORTED_ENCODINGS:
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError('지원하는 인코딩(UTF-8, CP949, EUC-KR)으로 파일을 읽을 수 없습니다.')


def xlsx_sheets(path):
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError('XLSX 처리를 위해 openpyxl 설치가 필요합니다.') from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    names = workbook.sheetnames
    workbook.close()
    return names


def iter_table(path, sheet_name=''):
    path = Path(path)
    if path.suffix.lower() == '.csv':
        encoding = detect_encoding(path)
        handle = path.open('r', encoding=encoding, newline='')
        sample = handle.read(65536)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',\t;|')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        headers = reader.fieldnames or []

        def rows():
            try:
                yield from reader
            finally:
                handle.close()
        return headers, rows(), encoding
    if path.suffix.lower() == '.xlsx':
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError('XLSX 처리를 위해 openpyxl 설치가 필요합니다.') from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        selected = sheet_name or workbook.sheetnames[0]
        if selected not in workbook.sheetnames:
            workbook.close()
            raise ValueError('선택한 시트를 찾을 수 없습니다.')
        sheet = workbook[selected]
        source = sheet.iter_rows(values_only=True)
        headers = [clean_text(value) for value in next(source, [])]

        def rows():
            try:
                for values in source:
                    yield dict(zip(headers, ('' if value is None else value for value in values)))
            finally:
                workbook.close()
        return headers, rows(), 'xlsx'
    raise ValueError('CSV 또는 XLSX 파일만 업로드할 수 있습니다.')


def detect_dataset_type(columns):
    column_set = set(columns)
    if {'QUALF_GRAD_NM', 'QUALF_ITEM_NM'} <= column_set:
        return 'qualification'
    if {'PROGRM_NM', 'FCLTY_NM'} <= column_set or {'COURSE_NM', 'CNTER_NM'} <= column_set:
        return 'program'
    lowered = {normalized_key(value) for value in columns}
    if any(normalized_key(value) in lowered for value in ALIASES['applicants']):
        return 'application'
    return 'program'


def suggest_mapping(dataset_type, columns):
    result = {}
    normalized = {normalized_key(column): column for column in columns}
    for field in FIELD_LABELS[dataset_type]:
        for alias in ALIASES.get(field, ()):
            if normalized_key(alias) in normalized:
                result[field] = normalized[normalized_key(alias)]
                break
    return result


def preview(path, sheet_name='', requested_type='auto'):
    headers, rows, encoding = iter_table(path, sheet_name)
    dataset_type = detect_dataset_type(headers) if requested_type == 'auto' else requested_type
    missing = Counter()
    samples = []
    count = 0
    for row in rows:
        count += 1
        for header in headers:
            if clean_text(row.get(header)) == '':
                missing[header] += 1
        if len(samples) < 20:
            samples.append([clean_text(row.get(header)) for header in headers])
    return {
        'dataset_type': dataset_type, 'columns': headers, 'encoding': encoding, 'row_count': count,
        'missing_counts': dict(missing), 'preview_rows': samples,
        'suggested_mapping': suggest_mapping(dataset_type, headers),
    }


def _value(row, mapping, field):
    column = mapping.get(field)
    return clean_text(row.get(column)) if column else ''


def _integer(value, required=False):
    value = clean_text(value).replace(',', '')
    if not value:
        if required:
            raise ValueError('필수 숫자 값이 비어 있습니다.')
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'숫자로 변환할 수 없습니다: {value}') from exc
    if number < 0:
        raise ValueError('음수는 사용할 수 없습니다.')
    return number


def _date(value):
    value = clean_text(value)
    if not value:
        return None
    if value.isdigit() and len(value) >= 12:
        return datetime.fromtimestamp(int(value) / 1000, tz=dt_timezone.utc).date()
    digits = ''.join(character for character in value if character.isdigit())
    if len(digits) == 4:
        return datetime(int(digits), 1, 1).date()
    if len(digits) == 8:
        return datetime.strptime(digits, '%Y%m%d').date()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'날짜로 변환할 수 없습니다: {value}')


def _time_range(value):
    value = clean_text(value)
    if not value:
        return None, None
    parts = value.replace('∼', '~').replace('-', '~').split('~', 1)
    parsed = []
    for part in parts[:2]:
        part = part.strip()
        try:
            parsed.append(datetime.strptime(part, '%H:%M').time())
        except ValueError:
            parsed.append(None)
    return (parsed + [None, None])[:2]


def _source_key(*values):
    payload = '\x1f'.join(clean_text(value) for value in values)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def validate_mapping(dataset_type, mapping):
    missing = REQUIRED_FIELDS[dataset_type] - {key for key, value in mapping.items() if value}
    if missing:
        labels = [FIELD_LABELS[dataset_type][field] for field in sorted(missing)]
        raise ValueError('필수 필드 매핑이 없습니다: ' + ', '.join(labels))


@transaction.atomic
def import_batch(batch, mapping, allow_invalid=False, source_path=None):
    validate_mapping(batch.dataset_type, mapping)
    path = source_path or batch.temporary_file.path
    headers, rows, _ = iter_table(path, batch.sheet_name)
    unknown = set(mapping.values()) - set(headers) - {''}
    if unknown:
        raise ValueError('파일에 없는 컬럼이 매핑되었습니다: ' + ', '.join(sorted(unknown)))
    errors = []
    if batch.dataset_type == 'qualification':
        success, duplicates = _import_qualifications(rows, mapping, batch, errors, allow_invalid)
    elif batch.dataset_type == 'program':
        success, duplicates = _import_programs(rows, mapping, batch, errors, allow_invalid)
    else:
        success, duplicates = _import_applications(rows, mapping, batch, errors, allow_invalid)
    batch.success_count = success
    batch.failure_count = len(errors)
    batch.duplicate_count = duplicates
    batch.field_mapping = mapping
    batch.errors = errors[:10000]
    batch.status = UploadBatch.Status.COMPLETED
    batch.completed_at = timezone.now()
    batch.save(update_fields=['success_count', 'failure_count', 'duplicate_count', 'field_mapping', 'errors', 'status', 'completed_at'])
    if batch.temporary_file:
        batch.temporary_file.delete(save=False)
        batch.temporary_file = ''
        batch.save(update_fields=['temporary_file'])
    return batch


def _import_qualifications(rows, mapping, batch, errors, allow_invalid=False):
    aggregated = Counter()
    raw_values = {}
    valid_rows = 0
    for number, row in enumerate(rows, start=2):
        try:
            sport_raw = _value(row, mapping, 'sport')
            qualification_raw = _value(row, mapping, 'qualification')
            if not sport_raw or not qualification_raw:
                raise ValueError('종목 또는 자격 값이 비어 있습니다.')
            date = _date(_value(row, mapping, 'acquisition_date'))
            region_raw = _value(row, mapping, 'region')
            qualification_type, grade = split_qualification(qualification_raw)
            sport = normalize_sport(sport_raw)
            region = normalize_region(region_raw)
            count = _integer(_value(row, mapping, 'count')) or 1
            key = (date.year if date else None, normalized_key(region), normalized_key(sport), qualification_type, grade)
            aggregated[key] += count
            raw_values[key] = (region_raw, sport_raw)
            valid_rows += 1
        except ValueError as exc:
            errors.append({'row': number, 'message': str(exc)})
    duplicates = valid_rows - len(aggregated)
    if errors and not allow_invalid:
        raise ImportValidationError(errors)
    objects = []
    for key, count in aggregated.items():
        year, region_key, sport_key, qualification_type, grade = key
        region_raw, sport_raw = raw_values[key]
        objects.append(QualificationAggregate(
            acquisition_year=year, region=region_raw, normalized_region=region_key,
            sport=sport_raw, normalized_sport=sport_key, qualification_type=qualification_type,
            grade=grade, acquisition_count=count, source_filename=batch.original_filename,
        ))
    QualificationAggregate.objects.bulk_create(
        objects, batch_size=1000, update_conflicts=True, update_fields=['acquisition_count', 'region', 'sport'],
        unique_fields=['acquisition_year', 'normalized_region', 'normalized_sport', 'qualification_type', 'grade', 'source_filename'],
    )
    # 새 자격 종목이 생기면 이 데이터만을 기준으로 taxonomy를 동기화한다.
    from app.services.sport_matching import sync_taxonomy
    sync_taxonomy()
    return valid_rows, duplicates


def _institution(region_raw, name_raw, mapping_values, batch, cache):
    region = normalize_region(region_raw)
    name = normalize_institution(name_raw)
    key = (normalized_key(name), normalized_key(region))
    if not name:
        raise ValueError('기관명이 비어 있습니다.')
    if key not in cache:
        institution, _ = Institution.objects.update_or_create(
            normalized_name=key[0], normalized_region=key[1],
            defaults={'name': name_raw, 'region': region_raw, 'address': mapping_values.get('address', ''),
                      'institution_type': mapping_values.get('institution_type', ''), 'source_filename': batch.original_filename},
        )
        cache[key] = institution
    return cache[key]


def _import_programs(rows, mapping, batch, errors, allow_invalid=False):
    from app.models import CanonicalSport
    from app.services.sport_matching import SportMatcher, matching_key

    institutions = {}
    programs = {}
    valid_rows = 0
    taxonomy = list(CanonicalSport.objects.filter(is_active=True))
    matcher = SportMatcher(taxonomy) if taxonomy else None
    sports_by_key = {matching_key(item.normalized_name): item for item in taxonomy}
    for number, row in enumerate(rows, start=2):
        try:
            values = {field: _value(row, mapping, field) for field in FIELD_LABELS['program']}
            institution = _institution(values['region'], values['institution'], values, batch, institutions)
            if not values['program']:
                raise ValueError('프로그램명이 비어 있습니다.')
            start_date, end_date = _date(values['start_date']), _date(values['end_date'])
            start_time, end_time = _time_range(values['time'])
            sport = normalize_sport(values['sport'])
            key = _source_key(
                batch.original_filename, institution.normalized_name, values['program'], sport,
                values['target'], values['weekdays'], start_date, end_date, values['time'],
            )
            program = Program(
                institution=institution, source_key=key, name=values['program'], normalized_name=normalized_key(values['program']),
                sport=values['sport'], normalized_sport=normalized_key(sport), target=values['target'], weekdays=values['weekdays'],
                start_time=start_time, end_time=end_time, start_date=start_date, end_date=end_date,
                capacity=_integer(values['capacity']), status=values['status'] or '운영', source_filename=batch.original_filename,
                program_type=values['program_type'], facility_industry=values['facility_industry'],
            )
            if matcher:
                result = matcher.match(
                    name=program.name, sport=program.sport, program_type=program.program_type,
                    facility_industry=program.facility_industry,
                    institution_type=institution.institution_type,
                )
                program.matched_sport = sports_by_key.get(result.canonical_key)
                program.match_grade = result.grade
                program.match_confidence = result.confidence
                program.match_reason = result.reason
                program.match_rules = result.rules
                program.match_candidates = result.candidates
                program.match_updated_at = timezone.now()
            programs[key] = program
            valid_rows += 1
        except ValueError as exc:
            errors.append({'row': number, 'message': str(exc)})
    if errors and not allow_invalid:
        raise ImportValidationError(errors)
    Program.objects.bulk_create(
        list(programs.values()), batch_size=1000, update_conflicts=True,
        update_fields=['institution', 'name', 'normalized_name', 'sport', 'normalized_sport', 'target', 'weekdays',
                       'start_time', 'end_time', 'start_date', 'end_date', 'capacity', 'status', 'source_filename',
                       'program_type', 'facility_industry'],
        unique_fields=['source_key'],
    )
    return valid_rows, valid_rows - len(programs)


def _import_applications(rows, mapping, batch, errors, allow_invalid=False):
    institutions = {}
    applications = {}
    valid_rows = 0
    for number, row in enumerate(rows, start=2):
        try:
            values = {field: _value(row, mapping, field) for field in FIELD_LABELS['application']}
            reference_date = _date(values['reference_date'])
            institution_name = values['institution'] or '기관 미상'
            institution = _institution('', institution_name, {}, batch, institutions)
            normalized_program = normalized_key(values['program'])
            program = Program.objects.filter(institution=institution, normalized_name=normalized_program).first()
            if not program:
                key = _source_key(institution.normalized_name, values['program'], '', '', '')
                program, _ = Program.objects.get_or_create(
                    source_key=key,
                    defaults={'institution': institution, 'name': values['program'], 'normalized_name': normalized_program,
                              'sport': values['sport'], 'normalized_sport': normalized_key(normalize_sport(values['sport'])),
                              'capacity': _integer(values['capacity']), 'source_filename': batch.original_filename},
                )
            capacity = _integer(values['capacity'], required=True)
            applicants = _integer(values['applicants'], required=True)
            # 동일 프로그램·기준일은 원본 파일명과 무관하게 하나의 현황으로 관리한다.
            key = _source_key(program.source_key, reference_date or batch.original_filename)
            applications[key] = ApplicationStatus(
                program=program, source_key=key, reference_date=reference_date,
                recruitment_year=reference_date.year if reference_date else None, capacity=capacity,
                applicants=applicants, waitlist=_integer(values['waitlist']), is_synthetic=False,
                source_filename=batch.original_filename,
            )
            valid_rows += 1
        except ValueError as exc:
            errors.append({'row': number, 'message': str(exc)})
    if errors and not allow_invalid:
        raise ImportValidationError(errors)
    ApplicationStatus.objects.bulk_create(
        list(applications.values()), batch_size=1000, update_conflicts=True,
        update_fields=['program', 'reference_date', 'recruitment_year', 'capacity', 'applicants', 'waitlist', 'is_synthetic', 'source_filename'],
        unique_fields=['source_key'],
    )
    return valid_rows, valid_rows - len(applications)
