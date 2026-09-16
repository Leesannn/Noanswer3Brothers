import calendar
import csv
import hashlib
import os
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from analytics.services.sport_matching import SportMatcher, matching_key


QUALIFICATION_COLUMNS = {
    'QUALF_GRAD_NM', 'QUALF_ITEM_NM', 'ACQS_DE', 'ACQS_AREA_NM',
}
PROGRAM_COLUMNS = {
    'FCLTY_NM', 'FCLTY_TY_NM', 'CTPRVN_NM', 'FCLTY_ADDR', 'INDUTY_NM',
    'PROGRM_TY_NM', 'PROGRM_NM', 'PROGRM_BEGIN_DE', 'PROGRM_END_DE',
    'PROGRM_RCRIT_NMPR_CO',
}

SPACE_RE = re.compile(r'\s+')
LEADING_PAREN_RE = re.compile(r'^\s*(?:\([^)]*\)\s*)+')
NON_KEY_RE = re.compile(r'[^0-9a-z가-힣]+')
REFERENCE_MONTH_RE = re.compile(r'_(20\d{2})(0[1-9]|1[0-2])(?:\D|$)')
GRADE_RE = re.compile(r'^\s*(\d+\s*급)\s*(.*?)\s*$')

# 자격 종목 자체에서 의미가 명확한 과거 명칭만 합친다. 프로그램 쪽의
# 표현 확장은 sport_matching_rules.json의 명시적 규칙이 담당한다.
QUALIFICATION_SPORT_ALIASES = {
    '보디빌딩구육체미': '보디빌딩',
    '육체미': '보디빌딩',
    '럭비풋볼': '럭비',
    '연식정구': '정구',
    '트라이애슬론': '철인3종',
}

REGION_ALIASES = {
    '서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구',
    '인천광역시': '인천', '광주광역시': '광주', '대전광역시': '대전',
    '울산광역시': '울산', '세종특별자치시': '세종', '경기도': '경기',
    '강원도': '강원', '강원특별자치도': '강원', '충청북도': '충북',
    '충청남도': '충남', '전라북도': '전북', '전북특별자치도': '전북',
    '전라남도': '전남', '경상북도': '경북', '경상남도': '경남',
    '제주특별자치도': '제주',
}


@dataclass(frozen=True)
class BuildPaths:
    database: Path
    unmatched: Path
    invalid: Path
    summary: Path


def clean_text(value):
    if value is None:
        return ''
    text = unicodedata.normalize('NFKC', str(value)).replace('<br>', ' ')
    return SPACE_RE.sub(' ', text).strip()


def normalized_key(value):
    return NON_KEY_RE.sub('', clean_text(value).casefold())


def normalize_region(value):
    cleaned = clean_text(value)
    return REGION_ALIASES.get(cleaned, cleaned)


def normalize_institution(value):
    cleaned = clean_text(value)
    return LEADING_PAREN_RE.sub('', cleaned).strip()


def normalize_qualification_sport(value):
    cleaned = clean_text(value)
    alias = QUALIFICATION_SPORT_ALIASES.get(normalized_key(cleaned))
    return alias or cleaned


def split_qualification(value):
    cleaned = clean_text(value)
    match = GRADE_RE.match(cleaned)
    if not match:
        return cleaned, ''
    return match.group(2) or cleaned, SPACE_RE.sub('', match.group(1))


def parse_year(row):
    acquired = clean_text(row.get('ACQS_DE'))
    digits = ''.join(character for character in acquired if character.isdigit())
    if len(digits) >= 4:
        year = int(digits[:4])
        if 1900 <= year <= 2100:
            return year
    for column in ('SDYTRN_OPERTN_YEAR', 'WRTNG_OPERTN_YEAR', 'PRCTTQ_OPERTN_YEAR'):
        value = clean_text(row.get(column))
        if value.isdigit() and 1900 <= int(value) <= 2100:
            return int(value)
    raise ValueError('취득 연도를 확인할 수 없습니다.')


def parse_date(value):
    cleaned = clean_text(value)
    if not cleaned:
        return None
    if cleaned.isdigit() and len(cleaned) >= 12:
        return datetime.fromtimestamp(int(cleaned) / 1000).date()
    digits = ''.join(character for character in cleaned if character.isdigit())
    if len(digits) == 8:
        return datetime.strptime(digits, '%Y%m%d').date()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    raise ValueError(f'날짜로 변환할 수 없습니다: {cleaned}')


def parse_capacity(value):
    cleaned = clean_text(value).replace(',', '')
    if not cleaned:
        return None
    try:
        number = int(float(cleaned))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'정원 값을 숫자로 변환할 수 없습니다: {cleaned}') from exc
    if number < 0:
        raise ValueError('정원은 음수일 수 없습니다.')
    return number


def reference_date_from_filename(path):
    match = REFERENCE_MONTH_RE.search(Path(path).name)
    if not match:
        return date.today()
    year, month = int(match.group(1)), int(match.group(2))
    return date(year, month, calendar.monthrange(year, month)[1])


def operating_status(start_date, end_date, reference_date):
    if start_date and end_date:
        if end_date < start_date:
            raise ValueError('종료일이 시작일보다 빠릅니다.')
        if end_date < reference_date:
            return 'ended'
        if start_date > reference_date:
            return 'upcoming'
        return 'active'
    if end_date and end_date < reference_date:
        return 'ended'
    if start_date and start_date > reference_date:
        return 'upcoming'
    return 'unknown'


def source_key(*values):
    payload = '\x1f'.join('' if value is None else str(value) for value in values)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]


def detect_encoding(path):
    sample = Path(path).open('rb').read(1024 * 1024)
    for encoding in ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr'):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f'지원하는 인코딩으로 읽을 수 없습니다: {path}')


def open_csv(path, required_columns):
    encoding = detect_encoding(path)
    handle = Path(path).open('r', encoding=encoding, newline='')
    reader = csv.DictReader(handle)
    columns = set(reader.fieldnames or [])
    missing = required_columns - columns
    if missing:
        handle.close()
        raise ValueError(f'{Path(path).name} 필수 컬럼 누락: {", ".join(sorted(missing))}')
    return handle, reader, encoding


def create_schema(connection):
    connection.executescript(
        '''
        PRAGMA foreign_keys = ON;
        PRAGMA journal_mode = DELETE;
        PRAGMA synchronous = NORMAL;

        CREATE TABLE canonical_sport (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE institution (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT '',
            normalized_region TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            normalized_address TEXT NOT NULL DEFAULT '',
            institution_type TEXT NOT NULL DEFAULT '',
            UNIQUE(normalized_name, normalized_region, normalized_address)
        );

        CREATE TABLE qualification_aggregate (
            id INTEGER PRIMARY KEY,
            acquisition_year INTEGER NOT NULL,
            region TEXT NOT NULL DEFAULT '',
            normalized_region TEXT NOT NULL DEFAULT '',
            sport_id INTEGER NOT NULL REFERENCES canonical_sport(id) ON DELETE RESTRICT,
            qualification_type TEXT NOT NULL,
            grade TEXT NOT NULL DEFAULT '',
            acquisition_count INTEGER NOT NULL CHECK(acquisition_count >= 0),
            UNIQUE(acquisition_year, normalized_region, sport_id, qualification_type, grade)
        );

        CREATE TABLE program (
            id INTEGER PRIMARY KEY,
            institution_id INTEGER NOT NULL REFERENCES institution(id) ON DELETE RESTRICT,
            sport_id INTEGER NOT NULL REFERENCES canonical_sport(id) ON DELETE RESTRICT,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            source_key TEXT NOT NULL UNIQUE,
            UNIQUE(institution_id, sport_id, normalized_name)
        );

        CREATE TABLE program_period (
            id INTEGER PRIMARY KEY,
            program_id INTEGER NOT NULL REFERENCES program(id) ON DELETE CASCADE,
            start_date TEXT,
            end_date TEXT,
            capacity INTEGER CHECK(capacity IS NULL OR capacity >= 0),
            operating_status TEXT NOT NULL CHECK(
                operating_status IN ('active', 'ended', 'upcoming', 'unknown')
            ),
            source_key TEXT NOT NULL UNIQUE
        );

        CREATE INDEX idx_institution_region ON institution(normalized_region);
        CREATE INDEX idx_qualification_sport_region
            ON qualification_aggregate(sport_id, normalized_region);
        CREATE INDEX idx_program_sport ON program(sport_id);
        CREATE INDEX idx_program_institution ON program(institution_id);
        CREATE INDEX idx_period_status ON program_period(operating_status);
        CREATE INDEX idx_period_program_dates
            ON program_period(program_id, start_date, end_date);
        '''
    )


def _preferred_labels(label_counts):
    result = {}
    for key, counts in label_counts.items():
        result[key] = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return result


def load_qualifications(path, invalid_writer, stats):
    aggregates = Counter()
    sport_labels = defaultdict(Counter)
    handle, reader, encoding = open_csv(path, QUALIFICATION_COLUMNS)
    stats['qualification_encoding'] = encoding
    try:
        for row_number, row in enumerate(reader, start=2):
            stats['qualification_rows'] += 1
            try:
                raw_sport = clean_text(row.get('QUALF_ITEM_NM'))
                raw_qualification = clean_text(row.get('QUALF_GRAD_NM'))
                if not raw_sport:
                    raise ValueError('자격 종목이 비어 있습니다.')
                if not raw_qualification:
                    raise ValueError('자격 종류·등급이 비어 있습니다.')
                sport = normalize_qualification_sport(raw_sport)
                sport_key = matching_key(sport)
                if not sport_key:
                    raise ValueError('정규화 후 자격 종목이 비어 있습니다.')
                year = parse_year(row)
                region = normalize_region(row.get('ACQS_AREA_NM'))
                qualification_type, grade = split_qualification(raw_qualification)
                if not qualification_type:
                    raise ValueError('자격 종류를 분리할 수 없습니다.')
                key = (
                    year, normalized_key(region), sport_key,
                    qualification_type, grade,
                )
                aggregates[key] += 1
                sport_labels[sport_key][sport] += 1
            except (TypeError, ValueError) as exc:
                stats['qualification_invalid'] += 1
                stats['invalid_reasons'][str(exc)] += 1
                invalid_writer.writerow(['qualification', row_number, str(exc)])
    finally:
        handle.close()
    stats['qualification_aggregates'] = len(aggregates)
    stats['canonical_sports'] = len(sport_labels)
    return aggregates, _preferred_labels(sport_labels)


def insert_qualifications(connection, aggregates, sport_labels):
    connection.executemany(
        'INSERT INTO canonical_sport(name, normalized_name) VALUES (?, ?)',
        [(sport_labels[key], key) for key in sorted(sport_labels)],
    )
    sport_ids = dict(connection.execute(
        'SELECT normalized_name, id FROM canonical_sport'
    ))
    rows = []
    for key, count in aggregates.items():
        year, region_key, sport_key, qualification_type, grade = key
        rows.append((
            year, region_key, region_key, sport_ids[sport_key],
            qualification_type, grade, count,
        ))
    connection.executemany(
        '''
        INSERT INTO qualification_aggregate(
            acquisition_year, region, normalized_region, sport_id,
            qualification_type, grade, acquisition_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        rows,
    )
    return sport_ids


def _get_institution(connection, cache, row):
    name = normalize_institution(row.get('FCLTY_NM'))
    if not name:
        raise ValueError('기관명이 비어 있습니다.')
    region = normalize_region(row.get('CTPRVN_NM'))
    address = clean_text(row.get('FCLTY_ADDR'))
    institution_type = clean_text(row.get('FCLTY_TY_NM')) or clean_text(row.get('FCLTY_FLAG_NM'))
    key = (normalized_key(name), normalized_key(region), normalized_key(address))
    if key in cache:
        return cache[key]
    cursor = connection.execute(
        '''
        INSERT INTO institution(
            name, normalized_name, region, normalized_region, address,
            normalized_address, institution_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(normalized_name, normalized_region, normalized_address)
        DO NOTHING
        ''',
        (name, key[0], region, key[1], address, key[2], institution_type),
    )
    if cursor.lastrowid:
        institution_id = cursor.lastrowid
    else:
        institution_id = connection.execute(
            '''SELECT id FROM institution
               WHERE normalized_name=? AND normalized_region=? AND normalized_address=?''',
            key,
        ).fetchone()[0]
    cache[key] = institution_id
    return institution_id


def load_programs(
    connection, path, sport_labels, sport_ids, reference_date,
    unmatched_writer, invalid_writer, stats,
):
    matcher = SportMatcher(list(sport_labels.values()))
    institution_cache = {}
    program_cache = {}
    period_keys = set()
    raw_names = set()
    normalized_names = set()
    handle, reader, encoding = open_csv(path, PROGRAM_COLUMNS)
    stats['program_encoding'] = encoding
    try:
        for row_number, row in enumerate(reader, start=2):
            stats['program_rows'] += 1
            try:
                program_name = clean_text(row.get('PROGRM_NM'))
                if not program_name:
                    raise ValueError('프로그램명이 비어 있습니다.')
                raw_names.add(str(row.get('PROGRM_NM') or ''))
                program_name_key = normalized_key(program_name)
                if not program_name_key:
                    raise ValueError('정규화 후 프로그램명이 비어 있습니다.')
                normalized_names.add(program_name_key)

                result = matcher.match(
                    name=program_name,
                    program_type=clean_text(row.get('PROGRM_TY_NM')),
                    facility_industry=clean_text(row.get('INDUTY_NM')),
                    institution_type=(
                        clean_text(row.get('FCLTY_TY_NM'))
                        or clean_text(row.get('FCLTY_FLAG_NM'))
                    ),
                )
                if result.canonical_key not in sport_ids or result.grade not in ('exact', 'similar'):
                    stats['program_unmatched'] += 1
                    stats['unmatched_reasons'][result.grade] += 1
                    unmatched_writer.writerow([
                        row_number, clean_text(row.get('FCLTY_NM')), program_name,
                        clean_text(row.get('PROGRM_TY_NM')),
                        clean_text(row.get('PROGRM_TY_NM')),
                        clean_text(row.get('INDUTY_NM')), result.reason,
                    ])
                    continue

                start_date = parse_date(row.get('PROGRM_BEGIN_DE'))
                end_date = parse_date(row.get('PROGRM_END_DE'))
                capacity = parse_capacity(row.get('PROGRM_RCRIT_NMPR_CO'))
                status = operating_status(start_date, end_date, reference_date)
                institution_id = _get_institution(connection, institution_cache, row)
                sport_id = sport_ids[result.canonical_key]
                program_identity = (institution_id, sport_id, program_name_key)
                program_id = program_cache.get(program_identity)
                if program_id is None:
                    program_key = source_key(*program_identity)
                    cursor = connection.execute(
                        '''
                        INSERT INTO program(
                            institution_id, sport_id, name, normalized_name, source_key
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(institution_id, sport_id, normalized_name) DO NOTHING
                        ''',
                        (institution_id, sport_id, program_name, program_name_key, program_key),
                    )
                    if cursor.lastrowid:
                        program_id = cursor.lastrowid
                        stats['programs_created'] += 1
                    else:
                        program_id = connection.execute(
                            '''SELECT id FROM program
                               WHERE institution_id=? AND sport_id=? AND normalized_name=?''',
                            program_identity,
                        ).fetchone()[0]
                    program_cache[program_identity] = program_id

                period_key = source_key(
                    program_id,
                    start_date.isoformat() if start_date else '',
                    end_date.isoformat() if end_date else '',
                    '' if capacity is None else capacity,
                )
                if period_key in period_keys:
                    stats['period_duplicates'] += 1
                else:
                    period_keys.add(period_key)
                    connection.execute(
                        '''
                        INSERT INTO program_period(
                            program_id, start_date, end_date, capacity,
                            operating_status, source_key
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            program_id,
                            start_date.isoformat() if start_date else None,
                            end_date.isoformat() if end_date else None,
                            capacity, status, period_key,
                        ),
                    )
                    stats['periods_created'] += 1
                    stats[f'status_{status}'] += 1
                stats['program_matched'] += 1
                stats[f'match_{result.grade}'] += 1
            except (OverflowError, TypeError, ValueError) as exc:
                stats['program_invalid'] += 1
                stats['invalid_reasons'][str(exc)] += 1
                invalid_writer.writerow(['program', row_number, str(exc)])

            if stats['program_rows'] % 50000 == 0:
                connection.commit()
    finally:
        handle.close()
    stats['program_unique_names_before'] = len(raw_names)
    stats['program_unique_names_normalized'] = len(normalized_names)


def validate_database(connection):
    checks = {}
    checks['integrity_check'] = connection.execute('PRAGMA integrity_check').fetchone()[0]
    checks['foreign_key_errors'] = len(connection.execute('PRAGMA foreign_key_check').fetchall())
    checks['orphan_programs'] = connection.execute(
        '''SELECT COUNT(*) FROM program p
           LEFT JOIN institution i ON i.id=p.institution_id
           LEFT JOIN canonical_sport s ON s.id=p.sport_id
           WHERE i.id IS NULL OR s.id IS NULL'''
    ).fetchone()[0]
    checks['orphan_periods'] = connection.execute(
        '''SELECT COUNT(*) FROM program_period pp
           LEFT JOIN program p ON p.id=pp.program_id WHERE p.id IS NULL'''
    ).fetchone()[0]
    checks['duplicate_institutions'] = connection.execute(
        '''SELECT COUNT(*) FROM (
             SELECT normalized_name, normalized_region, normalized_address, COUNT(*) count
             FROM institution GROUP BY 1,2,3 HAVING count>1
           )'''
    ).fetchone()[0]
    checks['duplicate_programs'] = connection.execute(
        '''SELECT COUNT(*) FROM (
             SELECT institution_id, sport_id, normalized_name, COUNT(*) count
             FROM program GROUP BY 1,2,3 HAVING count>1
           )'''
    ).fetchone()[0]
    checks['duplicate_periods'] = connection.execute(
        '''SELECT COUNT(*) FROM (
             SELECT program_id, COALESCE(start_date,''), COALESCE(end_date,''),
                    COALESCE(CAST(capacity AS TEXT),''), COUNT(*) count
             FROM program_period GROUP BY 1,2,3,4 HAVING count>1
           )'''
    ).fetchone()[0]
    checks['empty_program_names'] = connection.execute(
        "SELECT COUNT(*) FROM program WHERE TRIM(name)='' OR TRIM(normalized_name)=''"
    ).fetchone()[0]
    checks['invalid_date_ranges'] = connection.execute(
        '''SELECT COUNT(*) FROM program_period
           WHERE start_date IS NOT NULL AND end_date IS NOT NULL AND end_date<start_date'''
    ).fetchone()[0]
    checks['negative_values'] = connection.execute(
        '''SELECT
             (SELECT COUNT(*) FROM program_period WHERE capacity<0) +
             (SELECT COUNT(*) FROM qualification_aggregate WHERE acquisition_count<0)'''
    ).fetchone()[0]
    return checks


def _summary_text(paths, qualification_path, program_path, reference_date, stats, checks):
    lines = [
        '스포츠 데이터베이스 재구축 결과',
        '',
        f'자격증 원본: {Path(qualification_path)}',
        f'프로그램 원본: {Path(program_path)}',
        f'운영 상태 기준일: {reference_date.isoformat()}',
        '프로그램명 의미 단순화: 적용하지 않음(공백·유니코드·검색키만 정규화)',
        '',
        f'자격증 원본 행 수: {stats["qualification_rows"]:,}',
        f'프로그램 원본 행 수: {stats["program_rows"]:,}',
        f'표준 스포츠 종목 수: {stats["canonical_sports"]:,}',
        f'자격증 집계 행 수: {stats["qualification_aggregates"]:,}',
        f'자격 종목 연결 프로그램 행 수: {stats["program_matched"]:,}',
        f'미매칭 제외 프로그램 행 수: {stats["program_unmatched"]:,}',
        f'프로그램 오류 행 수: {stats["program_invalid"]:,}',
        f'자격증 오류 행 수: {stats["qualification_invalid"]:,}',
        f'원본 고유 프로그램명 수: {stats["program_unique_names_before"]:,}',
        f'표기 정규화 후 고유 프로그램명 수: {stats["program_unique_names_normalized"]:,}',
        f'중복 제거 후 Program 수: {stats["programs_created"]:,}',
        f'생성된 ProgramPeriod 수: {stats["periods_created"]:,}',
        f'중복 제거된 기간 행 수: {stats["period_duplicates"]:,}',
        f'active 기간 수: {stats["status_active"]:,}',
        f'ended 기간 수: {stats["status_ended"]:,}',
        f'upcoming 기간 수: {stats["status_upcoming"]:,}',
        f'unknown 기간 수: {stats["status_unknown"]:,}',
        f'기관 수: {stats["institution_count"]:,}',
        f'새 DB 크기: {paths.database.stat().st_size:,} bytes',
        '',
        '미매칭 사유별 개수:',
    ]
    if stats['unmatched_reasons']:
        lines.extend(
            f'- {reason}: {count:,}'
            for reason, count in stats['unmatched_reasons'].most_common()
        )
    else:
        lines.append('- 없음')
    lines.extend(['', '오류 사유별 개수:'])
    if stats['invalid_reasons']:
        lines.extend(
            f'- {reason}: {count:,}'
            for reason, count in stats['invalid_reasons'].most_common()
        )
    else:
        lines.append('- 없음')
    lines.extend(['', '무결성 검사:'])
    lines.extend(f'- {name}: {value}' for name, value in checks.items())
    lines.append('')
    return '\n'.join(lines)


def build_clean_database(
    qualification_path, program_path, output_dir, *, reference_date=None,
    replace=False, progress=None,
):
    qualification_path = Path(qualification_path).resolve()
    program_path = Path(program_path).resolve()
    output_dir = Path(output_dir).resolve()
    if not qualification_path.is_file():
        raise FileNotFoundError(qualification_path)
    if not program_path.is_file():
        raise FileNotFoundError(program_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = BuildPaths(
        database=output_dir / 'sports_clean_202607.sqlite3',
        unmatched=output_dir / 'unmatched_programs.csv',
        invalid=output_dir / 'invalid_rows.csv',
        summary=output_dir / 'cleaning_summary.txt',
    )
    if paths.database.exists() and not replace:
        raise FileExistsError(f'결과 DB가 이미 존재합니다: {paths.database}')
    if reference_date is None:
        reference_date = reference_date_from_filename(program_path)
    elif isinstance(reference_date, str):
        reference_date = date.fromisoformat(reference_date)

    temporary_database = paths.database.with_suffix('.building.sqlite3')
    if temporary_database.exists():
        temporary_database.unlink()
    stats = Counter()
    stats['invalid_reasons'] = Counter()
    stats['unmatched_reasons'] = Counter()

    connection = sqlite3.connect(temporary_database)
    try:
        create_schema(connection)
        with paths.invalid.open('w', encoding='utf-8-sig', newline='') as invalid_handle:
            invalid_writer = csv.writer(invalid_handle)
            invalid_writer.writerow(['dataset', 'row_number', 'reason'])
            aggregates, sport_labels = load_qualifications(
                qualification_path, invalid_writer, stats,
            )
            if not sport_labels:
                raise ValueError('자격증 원본에서 표준 스포츠 종목을 만들지 못했습니다.')
            sport_ids = insert_qualifications(connection, aggregates, sport_labels)
            connection.commit()
            if progress:
                progress(f'자격 종목 {len(sport_labels):,}개와 집계 {len(aggregates):,}건 생성')
            with paths.unmatched.open('w', encoding='utf-8-sig', newline='') as unmatched_handle:
                unmatched_writer = csv.writer(unmatched_handle)
                unmatched_writer.writerow([
                    'row_number', 'institution_name', 'original_program_name',
                    'original_sport', 'program_type', 'facility_industry', 'reason',
                ])
                load_programs(
                    connection, program_path, sport_labels, sport_ids, reference_date,
                    unmatched_writer, invalid_writer, stats,
                )
        connection.commit()
        connection.execute('PRAGMA optimize')
        connection.execute('VACUUM')
        checks = validate_database(connection)
        failed = {
            key: value for key, value in checks.items()
            if (key == 'integrity_check' and value != 'ok')
            or (key != 'integrity_check' and value != 0)
        }
        if failed:
            raise ValueError(f'새 DB 무결성 검사 실패: {failed}')
        stats['institution_count'] = connection.execute(
            'SELECT COUNT(*) FROM institution'
        ).fetchone()[0]
    except Exception:
        connection.close()
        if temporary_database.exists():
            temporary_database.unlink()
        raise
    else:
        connection.close()

    if paths.database.exists():
        if not replace:
            temporary_database.unlink(missing_ok=True)
            raise FileExistsError(paths.database)
        paths.database.unlink()
    os.replace(temporary_database, paths.database)

    # 최종 파일 크기는 원자적 교체 뒤에 계산한다.
    summary = _summary_text(
        paths, qualification_path, program_path, reference_date, stats, checks,
    )
    paths.summary.write_text(summary, encoding='utf-8')
    if progress:
        progress(f'새 DB 생성 완료: {paths.database}')
    return paths, stats, checks
