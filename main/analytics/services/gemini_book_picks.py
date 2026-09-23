"""시험정보 페이지 "AI 추천 교재" 패널이 쓰는 Gemini 연동.

자격 등급별 필기 과목에 맞는 수험서를 Gemini에게 구조화된 JSON으로 받아온다.
호출 비용과 지연을 줄이기 위해 등급 코드별로 24시간 서버 캐시를 쓰고, 응답이
스키마를 벗어나면(필드 누락, 빈 값, alsoGood 개수 불일치 등) BookPickError로
실패시켜 화면에는 항상 명확한 에러 상태를 보여주게 한다.
"""
import datetime
import json
import urllib.parse

from django.conf import settings
from django.core.cache import cache

CACHE_TTL_SECONDS = 60 * 60 * 24
CACHE_KEY_PREFIX = 'ai-book-pick'

# 사이트 내에 기존 서점 연동이 없어 검색 결과 URL을 조합할 기본 서점으로 교보문고를 쓴다.
BOOKSTORE_SEARCH_URL = 'https://search.kyobobook.co.kr/search'

REQUIRED_BEST_MATCH_FIELDS = ('title', 'author', 'publisher', 'year', 'reason')
REQUIRED_ALSO_GOOD_FIELDS = ('title', 'author', 'category', 'reason')

RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {
        'bestMatch': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'author': {'type': 'string'},
                'publisher': {'type': 'string'},
                'year': {'type': 'string'},
                'reason': {'type': 'string'},
                'coveredSubjects': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['title', 'author', 'publisher', 'year', 'reason', 'coveredSubjects'],
        },
        'alsoGood': {
            'type': 'array',
            'minItems': 2,
            'maxItems': 2,
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'author': {'type': 'string'},
                    'category': {'type': 'string'},
                    'reason': {'type': 'string'},
                },
                'required': ['title', 'author', 'category', 'reason'],
            },
        },
    },
    'required': ['bestMatch', 'alsoGood'],
}


class BookPickError(Exception):
    """Gemini 호출이나 응답 검증에 실패했을 때."""


def _cache_key(grade_code):
    return f'{CACHE_KEY_PREFIX}:{grade_code}'


def bookstore_search_url(title, author):
    query = f'{title} {author}'.strip()
    params = urllib.parse.urlencode({'keyword': query, 'target': 'total'})
    return f'{BOOKSTORE_SEARCH_URL}?{params}'


def _validate_payload(data, written_subjects):
    if not isinstance(data, dict):
        raise BookPickError('응답 형식이 올바르지 않습니다.')

    best = data.get('bestMatch')
    if not isinstance(best, dict):
        raise BookPickError('bestMatch가 없습니다.')
    for field in REQUIRED_BEST_MATCH_FIELDS:
        if not str(best.get(field, '')).strip():
            raise BookPickError(f'bestMatch.{field}가 비어 있습니다.')

    covered = best.get('coveredSubjects')
    if not isinstance(covered, list) or not covered:
        raise BookPickError('bestMatch.coveredSubjects가 비어 있습니다.')
    subject_set = set(written_subjects)
    # 모델이 규칙을 어기고 목록 밖 과목을 적어도, 화면에는 실제 필기 과목만 남긴다.
    covered = [str(s) for s in covered if str(s) in subject_set] or [str(covered[0])]

    also_good = data.get('alsoGood')
    if not isinstance(also_good, list) or len(also_good) != 2:
        raise BookPickError('alsoGood은 정확히 2권이어야 합니다.')

    cleaned_also_good = []
    for item in also_good:
        if not isinstance(item, dict):
            raise BookPickError('alsoGood 항목 형식이 올바르지 않습니다.')
        for field in REQUIRED_ALSO_GOOD_FIELDS:
            if not str(item.get(field, '')).strip():
                raise BookPickError(f'alsoGood.{field}가 비어 있습니다.')
        cleaned_also_good.append({field: str(item[field]) for field in REQUIRED_ALSO_GOOD_FIELDS})

    cleaned_best = {field: str(best[field]) for field in REQUIRED_BEST_MATCH_FIELDS}
    cleaned_best['coveredSubjects'] = covered
    return {'bestMatch': cleaned_best, 'alsoGood': cleaned_also_good}


def _build_prompt(grade_name, written_subjects):
    subjects_text = ', '.join(written_subjects) if written_subjects else '(정보 없음)'
    current_year = datetime.date.today().year
    system_instruction = (
        '너는 한국 체육지도자 자격시험(국민체육진흥공단 주관) 수험서를 추천하는 도우미다. '
        '실제로 출간된 책만 추천하고, 확신이 없으면 추측하지 말고 알고 있는 책 중에서만 골라라. '
        f'오늘은 {current_year}년이다. 같은 시리즈에 더 최근 개정판이 있다는 걸 알고 있다면 '
        '무조건 그 최신 개정판을 추천하고, 오래되어 절판되었거나 개정판이 나온 구판은 추천하지 마라. '
        '연도는 네가 실제로 알고 있는 출간연도만 적고 지어내지 마라. '
        '추천 이유는 한국어로 한두 문장, 60자 안팎으로 짧게 써라. '
        'coveredSubjects는 반드시 아래 "필기 과목" 목록 안에 있는 값만 그대로 사용해라.'
    )
    prompt = (
        f'자격증명: {grade_name}\n'
        f'필기 과목: {subjects_text}\n\n'
        '이 자격증의 필기시험 준비에 가장 잘 맞는 수험서 1권(bestMatch)과, '
        '추가로 참고할 만한 책 정확히 2권(alsoGood)을 추천해줘. '
        f'가능하면 {current_year}년판이나 그 직전 연도에 나온 최신 개정판을 우선해줘.'
    )
    return system_instruction, prompt


def _request_from_gemini(grade_name, written_subjects):
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise BookPickError('GEMINI_API_KEY가 설정되지 않았습니다.')

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise BookPickError('google-genai 패키지가 설치되어 있지 않습니다.') from exc

    system_instruction, prompt = _build_prompt(grade_name, written_subjects)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type='application/json',
                response_schema=RESPONSE_SCHEMA,
                temperature=0.4,
            ),
        )
    except BookPickError:
        raise
    except Exception as exc:  # SDK가 던지는 예외 타입이 다양해 폭넓게 잡아 사용자에게는 통일된 에러로 보여준다.
        raise BookPickError(f'Gemini 호출에 실패했습니다: {exc}') from exc

    text = getattr(response, 'text', None)
    if not text:
        raise BookPickError('Gemini 응답이 비어 있습니다.')

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BookPickError('Gemini 응답을 JSON으로 해석하지 못했습니다.') from exc

    return _validate_payload(data, written_subjects)


def get_book_picks(grade_code, grade_name, written_subjects, *, refresh=False):
    """등급별 추천을 24시간 캐시에서 읽거나, 없거나 refresh=True면 Gemini를 새로 호출한다."""
    key = _cache_key(grade_code)
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    payload = _request_from_gemini(grade_name, written_subjects)
    cache.set(key, payload, CACHE_TTL_SECONDS)
    return payload
