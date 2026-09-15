import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from django.db.models import Sum

from app.models import CanonicalSport, QualificationAggregate


RULES_PATH = Path(__file__).resolve().parent.parent / 'sport_matching_rules.json'
NON_WORD_RE = re.compile(r'[^0-9a-z가-힣]+')


@lru_cache(maxsize=1)
def load_rules():
    with RULES_PATH.open(encoding='utf-8') as handle:
        return json.load(handle)


def matching_key(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return NON_WORD_RE.sub('', value)


@dataclass(frozen=True)
class MatchResult:
    canonical_key: str | None
    grade: str
    confidence: int
    reason: str
    rules: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


class SportMatcher:
    FIELD_LABELS = {
        'name': '프로그램명', 'program_type': '프로그램 유형',
        'sport': '기존 프로그램 종목', 'facility_industry': '시설 업종',
        'institution_type': '시설 유형',
    }
    FIELD_SCORES = {
        'sport': 91, 'program_type': 90, 'name': 84,
        'facility_industry': 72, 'institution_type': 68,
    }

    def __init__(self, canonical_sports, rules=None):
        self.rules = rules or load_rules()
        self.taxonomy = {
            matching_key(item.normalized_name if hasattr(item, 'normalized_name') else item): item
            for item in canonical_sports
        }
        self.names = {
            key: item.name if hasattr(item, 'name') else str(item)
            for key, item in self.taxonomy.items()
        }
        self.low_information = {
            matching_key(term) for term in self.rules['low_information_terms']
        }

    def _target(self, configured_targets):
        for target in configured_targets:
            key = matching_key(target)
            if key in self.taxonomy:
                return key
        return None

    @staticmethod
    def _candidate_list(scores, names):
        return [
            {'sport': names[key], 'score': score}
            for key, score in sorted(scores.items(), key=lambda item: (-item[1], names[item[0]]))[:5]
        ]

    def _rule_matches(self, rule, field_keys, default_fields=None):
        allowed = rule.get('fields') or default_fields or list(field_keys)
        matched = []
        for field_name in allowed:
            text = field_keys.get(field_name, '')
            for term in rule['terms']:
                term_key = matching_key(term)
                if term_key and term_key in text:
                    matched.append((field_name, term))
                    break
        return matched

    def match(self, *, name='', sport='', program_type='', facility_industry='', institution_type=''):
        values = {
            'name': name, 'sport': sport, 'program_type': program_type,
            'facility_industry': facility_industry, 'institution_type': institution_type,
        }
        field_keys = {key: matching_key(value) for key, value in values.items()}

        # 1. 원문 완전 일치. 현재 분류 필드를 프로그램명보다 우선한다.
        exact = {}
        for field_name in ('sport', 'program_type', 'name'):
            key = field_keys[field_name]
            if key in self.taxonomy:
                raw_equal = str(values[field_name]).strip().casefold() == self.names[key].strip().casefold()
                exact[key] = max(exact.get(key, 0), 100 if raw_equal else 98)
        if len(exact) == 1:
            key, score = next(iter(exact.items()))
            source = next(field for field in ('sport', 'program_type', 'name') if field_keys[field] == key)
            rule = 'exact_name' if score == 100 else 'normalized_exact'
            return MatchResult(key, 'exact', score, f'{self.FIELD_LABELS[source]}이 기준 종목 “{self.names[key]}”과 일치합니다.', [rule])
        if len(exact) > 1:
            return MatchResult(None, 'review', 55, '입력 필드에서 서로 다른 기준 종목이 확인되어 검토가 필요합니다.', ['exact_conflict'], self._candidate_list(exact, self.names))

        # 2. 신뢰할 수 있는 동의어.
        for rule in self.rules['synonyms']:
            target = self._target(rule['targets'])
            if not target:
                continue
            matched = self._rule_matches(rule, field_keys, ('sport', 'program_type', 'name'))
            if matched:
                source, term = matched[0]
                return MatchResult(target, 'exact', rule['score'], f'{self.FIELD_LABELS[source]}의 “{term}”을 동의어 규칙으로 “{self.names[target]}”에 연결했습니다.', [f'synonym:{term}->{self.names[target]}'])

        # 3. 세부 프로그램을 실제 자격 taxonomy에 존재하는 상위 종목으로 변환.
        for rule in self.rules['parent_mappings']:
            target = self._target(rule['targets'])
            if not target:
                continue
            matched = self._rule_matches(rule, field_keys, ('sport', 'program_type', 'name'))
            if matched:
                source, term = matched[0]
                return MatchResult(target, 'similar', rule['score'], f'{self.FIELD_LABELS[source]}의 세부 표현 “{term}”을 상위 자격 종목 “{self.names[target]}”으로 통합했습니다.', [f'parent:{term}->{self.names[target]}'])

        # 4. 여러 필드에서 taxonomy 명칭과 관리형 문맥 규칙의 근거를 합산한다.
        scores = {}
        evidence = {}
        for key, canonical_name in self.names.items():
            if len(key) < 2 or key in self.low_information:
                continue
            for field_name, text in field_keys.items():
                if key and key in text:
                    score = self.FIELD_SCORES[field_name]
                    if score > scores.get(key, 0):
                        scores[key] = score
                        evidence[key] = f'{self.FIELD_LABELS[field_name]}에 “{canonical_name}” 포함'
        for rule in self.rules['context_rules']:
            target = self._target(rule['targets'])
            if not target:
                continue
            matched = self._rule_matches(rule, field_keys)
            if matched and rule['score'] > scores.get(target, 0):
                source, term = matched[0]
                scores[target] = rule['score']
                evidence[target] = f'{self.FIELD_LABELS[source]}의 “{term}” 문맥'

        ranked = sorted(scores, key=lambda key: (-scores[key], self.names[key]))
        if len(ranked) >= 2 and scores[ranked[1]] >= scores[ranked[0]] - 8:
            return MatchResult(None, 'review', min(69, scores[ranked[0]]), '둘 이상의 종목 근거가 비슷하게 나타나 대표 종목을 자동 확정하지 않았습니다.', ['context_conflict'], self._candidate_list(scores, self.names))
        if ranked:
            key = ranked[0]
            score = scores[key]
            if score >= 80:
                return MatchResult(key, 'similar', score, f'{evidence[key]} 근거로 “{self.names[key]}”이 가장 유력합니다.', ['multi_field_context'], self._candidate_list(scores, self.names))
            return MatchResult(None, 'review', score, f'{evidence[key]}만 확인되어 자동 확정하기에는 근거가 부족합니다.', ['weak_context'], self._candidate_list(scores, self.names))

        return MatchResult(None, 'unmatched', 0, '기준 종목을 추론할 식별력 있는 근거를 찾지 못했습니다.', ['no_evidence'])


def sync_taxonomy():
    """자격 데이터의 종목만 기준표에 반영하며 임의 종목은 생성하지 않는다."""
    rows = QualificationAggregate.objects.exclude(normalized_sport='').values(
        'normalized_sport', 'sport',
    ).annotate(total=Sum('acquisition_count')).order_by('normalized_sport', '-total', 'sport')
    selected = {}
    totals = {}
    for row in rows:
        key = matching_key(row['normalized_sport'] or row['sport'])
        if not key:
            continue
        totals[key] = totals.get(key, 0) + (row['total'] or 0)
        selected.setdefault(key, row['sport'])
    for key in sorted(selected):
        CanonicalSport.objects.update_or_create(
            normalized_name=key,
            defaults={'name': selected[key], 'qualification_count': totals[key], 'is_active': True},
        )
    CanonicalSport.objects.exclude(normalized_name__in=selected).update(is_active=False)
    return CanonicalSport.objects.filter(is_active=True)
