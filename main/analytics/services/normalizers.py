import re


SPACE_RE = re.compile(r'\s+')
PUNCT_RE = re.compile(r'[^0-9A-Za-z가-힣]')

SPORT_ALIASES = {
    '수영장': '수영',
    'swimming': '수영',
    '헬스': '헬스',
    '헬스장': '헬스',
    'fitness': '헬스',
    '축구장': '축구',
    '풋살': '축구',
    '풋살장': '축구',
    '테니스장': '테니스',
}


def clean_text(value):
    if value is None:
        return ''
    return SPACE_RE.sub(' ', str(value).replace('<br>', ' ')).strip()


def normalized_key(value):
    return PUNCT_RE.sub('', clean_text(value)).lower()


def normalize_sport(value):
    cleaned = clean_text(value)
    key = normalized_key(cleaned)
    for alias, canonical in SPORT_ALIASES.items():
        if normalized_key(alias) == key:
            return canonical
    return cleaned


def normalize_region(value):
    cleaned = clean_text(value)
    replacements = {
        '서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구',
        '인천광역시': '인천', '광주광역시': '광주', '대전광역시': '대전',
        '울산광역시': '울산', '세종특별자치시': '세종', '경기도': '경기',
        '강원특별자치도': '강원', '충청북도': '충북', '충청남도': '충남',
        '전북특별자치도': '전북', '전라북도': '전북', '전라남도': '전남',
        '경상북도': '경북', '경상남도': '경남', '제주특별자치도': '제주',
    }
    return replacements.get(cleaned, cleaned)


def normalized_contains(value, query):
    """공백과 문장부호 차이를 무시하고 지역·대상 문자열 포함 여부를 본다."""
    query_key = normalized_key(query)
    return bool(query_key and query_key in normalized_key(value))


def normalize_institution(value):
    cleaned = clean_text(value)
    cleaned = re.sub(r'^\([^)]*\)', '', cleaned).strip()
    return cleaned


def split_qualification(value):
    cleaned = clean_text(value)
    match = re.match(r'^(\d+급)\s*(.*)$', cleaned)
    if match:
        return match.group(2).strip(), match.group(1)
    return cleaned, ''
