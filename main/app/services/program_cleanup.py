import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from app.models import ProgramCleanup
from app.services.sport_matching import SportMatcher, load_rules as load_sport_rules, matching_key


RULES_PATH = Path(__file__).resolve().parent.parent / 'program_cleanup_rules.json'
SPACE_RE = re.compile(r'\s+')
PAREN_RE = re.compile(r'[\(\[\{][^\)\]\}]*[\)\]\}]')
TIME_RE = re.compile(r'(?<!\d)\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?|(?<!\d)\d{1,2}:\d{2}')
DAY_RE = re.compile(r'(?:월|화|수|목|금|토|일){2,7}(?:요일)?|주말|평일|매일')
AUDIENCE_RE = re.compile(r'성인|청소년|어린이|유아|초등(?:학생)?|중등(?:학생)?|고등(?:학생)?|남성|여성(?:전용)?')
LEVEL_RE = re.compile(r'초급|중급|고급|입문|기초|초중급|중상급|상급')
GENERIC_RE = re.compile(r'교실|강좌|강습|수업|프로그램|이용|회원')
PUNCT_RE = re.compile(r'[_|:;~\-]+')


@lru_cache(maxsize=1)
def load_cleanup_rules():
    with RULES_PATH.open(encoding='utf-8') as handle:
        return json.load(handle)


def cleanup_reference_date(value=None):
    if isinstance(value, date):
        return value
    configured = value or settings.PROGRAM_CLEANUP_REFERENCE_DATE
    return date.fromisoformat(configured)


@dataclass(frozen=True)
class CleanupDecision:
    cleaned_name: str
    canonical_key: str | None
    operating_status: str
    is_usable: bool
    exclusion_reason: str
    evidence: str
    rules: list[str] = field(default_factory=list)


class ProgramCleaner:
    """원본을 수정하지 않고 분석용 프로그램 정리 결과를 결정한다."""

    def __init__(self, canonical_sports, rules=None):
        self.rules = rules or load_cleanup_rules()
        self.taxonomy = {
            matching_key(item.normalized_name): item for item in canonical_sports if item.is_active
        }
        self.names = {key: item.name for key, item in self.taxonomy.items()}
        self.matcher = SportMatcher(canonical_sports)
        self.term_targets = self._build_term_targets()

    def _target(self, targets):
        for target in targets:
            key = matching_key(target)
            if key in self.taxonomy:
                return key
        return None

    def _build_term_targets(self):
        terms = []
        for key, name in self.names.items():
            if len(key) >= 2:
                terms.append((key, key, name))
        for collection in ('synonyms', 'parent_mappings'):
            for rule in load_sport_rules()[collection]:
                target = self._target(rule['targets'])
                if target:
                    for term in rule['terms']:
                        key = matching_key(term)
                        if key:
                            terms.append((key, target, term))
        for rule in self.rules['name_mappings']:
            target = self._target(rule['targets'])
            if target:
                for term in rule['terms']:
                    key = matching_key(term)
                    if key:
                        terms.append((key, target, term))
        # 긴 표현을 먼저 선택해 수상스키/스키, 아이스하키/하키의 중복을 막는다.
        return sorted(set(terms), key=lambda item: (-len(item[0]), item[0], item[1]))

    def _field_sports(self, value):
        text = matching_key(value)
        candidates = []
        for term, target, label in self.term_targets:
            start = text.find(term)
            while start >= 0:
                candidates.append((start, start + len(term), target, label))
                start = text.find(term, start + 1)
        selected = []
        occupied = []
        for start, end, target, label in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0], item[2])):
            if any(start < used_end and used_start < end for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            selected.append((target, label))
        return selected

    def detect_multiple_sports(self, program):
        raw_fields = (program.name, program.sport, program.program_type)
        phrases = [matching_key(value) for value in self.rules['multi_sport_phrases']]
        for raw in raw_fields:
            text_key = matching_key(raw)
            if any(phrase and phrase in text_key for phrase in phrases):
                return True, [], '복수 종목을 뜻하는 종합·복합 표현이 확인됐습니다.'
            hits = self._field_sports(raw)
            targets = {target for target, _ in hits}
            has_separator = any(separator in str(raw or '') for separator in self.rules['multi_sport_separators'])
            if has_separator and len(targets) >= 2:
                labels = sorted({self.names[target] for target in targets})
                return True, labels, f'한 필드에서 서로 다른 종목 {", ".join(labels)}이 함께 확인됐습니다.'
        return False, [], ''

    def operating_status(self, program, reference_date):
        status_text = f'{program.name} {program.status}'
        for term in self.rules['ended_terms']:
            if matching_key(term) in matching_key(status_text):
                return ProgramCleanup.OperatingStatus.ENDED, f'종료 표현 “{term}”이 확인됐습니다.', f'ended_term:{term}'
        if program.start_date and program.end_date:
            if program.start_date <= reference_date <= program.end_date:
                return ProgramCleanup.OperatingStatus.ACTIVE, f'{program.start_date}~{program.end_date}에 기준일 {reference_date}이 포함됩니다.', 'date_range_active'
            if program.end_date < reference_date:
                return ProgramCleanup.OperatingStatus.ENDED, f'종료일 {program.end_date}이 기준일 {reference_date}보다 이전입니다.', 'date_range_ended'
            return ProgramCleanup.OperatingStatus.UNKNOWN, f'시작일 {program.start_date}이 기준일 {reference_date}보다 이후입니다.', 'date_range_future'
        return ProgramCleanup.OperatingStatus.UNKNOWN, '시작일 또는 종료일이 없어 운영 여부를 확정할 수 없습니다.', 'date_incomplete'

    def name_mapping(self, program):
        fields = (('프로그램명', program.name), ('현재 분류', program.sport), ('프로그램 유형', program.program_type))
        for rule in self.rules['name_mappings']:
            for label, value in fields:
                text = matching_key(value)
                for term in rule['terms']:
                    if matching_key(term) in text:
                        target = self._target(rule['targets'])
                        return rule['cleaned_name'], target, f'{label}의 “{term}” 정규화 규칙을 적용했습니다.', f'name:{term}->{rule["cleaned_name"]}'
        return '', None, '', ''

    def basic_clean_name(self, value):
        text = unicodedata.normalize('NFKC', str(value or '')).replace('<br>', ' ')
        for term in self.rules['ended_terms']:
            text = text.replace(term, ' ')
        text = PAREN_RE.sub(' ', text)
        text = TIME_RE.sub(' ', text)
        text = DAY_RE.sub(' ', text)
        text = AUDIENCE_RE.sub(' ', text)
        text = LEVEL_RE.sub(' ', text)
        text = GENERIC_RE.sub(' ', text)
        text = PUNCT_RE.sub(' ', text)
        text = SPACE_RE.sub(' ', text).strip(' /·,+&')
        return text or str(value or '').strip()

    def clean(self, program, reference_date=None):
        reference_date = cleanup_reference_date(reference_date)
        evidence = []
        applied_rules = []
        status, status_evidence, status_rule = self.operating_status(program, reference_date)
        evidence.append(status_evidence)
        applied_rules.append(status_rule)

        is_multiple, multiple_candidates, multiple_evidence = self.detect_multiple_sports(program)
        if is_multiple:
            evidence.append(multiple_evidence)
            applied_rules.append('exclude:multi_sport')

        cleaned_name, canonical_key, name_evidence, name_rule = self.name_mapping(program)
        has_explicit_name_mapping = bool(cleaned_name)
        if name_evidence:
            evidence.append(name_evidence)
            applied_rules.append(name_rule)
        if not cleaned_name:
            cleaned_name = self.basic_clean_name(program.name)
            applied_rules.append('name:basic_cleanup')

        if not canonical_key and program.matched_sport_id and program.match_grade in ('exact', 'similar'):
            candidate = matching_key(program.matched_sport.normalized_name)
            if candidate in self.taxonomy:
                canonical_key = candidate
                evidence.append(f'기존 검증된 매칭 “{self.names[candidate]}”을 재사용했습니다.')
                applied_rules.append('taxonomy:existing_match')
        if not canonical_key:
            result = self.matcher.match(
                name=cleaned_name, sport=program.sport, program_type=program.program_type,
                facility_industry=program.facility_industry,
                institution_type=program.institution.institution_type,
            )
            if result.canonical_key and result.grade in ('exact', 'similar') and result.confidence >= 80:
                canonical_key = result.canonical_key
                evidence.append(result.reason)
                applied_rules.extend(result.rules)

        if canonical_key and not has_explicit_name_mapping:
            cleaned_name = self.names[canonical_key]
            evidence.append(f'세부 운영 표현을 제거하고 상위 종목명 “{cleaned_name}”으로 통일했습니다.')
            applied_rules.append('name:canonical_group')

        if status == ProgramCleanup.OperatingStatus.ENDED:
            exclusion_reason = ProgramCleanup.ExclusionReason.ENDED
        elif is_multiple:
            exclusion_reason = ProgramCleanup.ExclusionReason.MULTI_SPORT
            canonical_key = None
            cleaned_name = ''
        elif status == ProgramCleanup.OperatingStatus.UNKNOWN:
            exclusion_reason = ProgramCleanup.ExclusionReason.UNKNOWN
        elif not canonical_key:
            exclusion_reason = ProgramCleanup.ExclusionReason.UNMATCHED
        else:
            exclusion_reason = ProgramCleanup.ExclusionReason.NONE
        is_usable = status == ProgramCleanup.OperatingStatus.ACTIVE and exclusion_reason == '' and canonical_key is not None
        if multiple_candidates:
            evidence.append('후보 종목: ' + ', '.join(multiple_candidates))
        return CleanupDecision(
            cleaned_name=cleaned_name, canonical_key=canonical_key,
            operating_status=status, is_usable=is_usable,
            exclusion_reason=exclusion_reason, evidence=' '.join(evidence),
            rules=applied_rules,
        )
