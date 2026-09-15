"""crawl_license_info 커맨드가 만든 CSV를 읽어서 서빙하는 로더.

자격제도안내는 자주 바뀌지 않는 정보라 요청마다 새로 크롤링하지 않고,
1회성으로 만들어 둔 CSV를 프로세스당 한 번만 읽어 메모리에 캐시한다.
"""
import csv
import functools

from django.conf import settings


def _data_dir():
    return settings.BASE_DIR / 'data'


@functools.lru_cache(maxsize=1)
def get_license_grades():
    """{grade_code: row dict} — CSV가 없으면 빈 dict (화면은 안내 문구로 대체)."""
    path = _data_dir() / 'kspo_license_grades.csv'
    if not path.exists():
        return {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        return {row['grade_code']: row for row in csv.DictReader(f)}


@functools.lru_cache(maxsize=1)
def _all_eligibility_paths():
    path = _data_dir() / 'kspo_license_eligibility_paths.csv'
    if not path.exists():
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def get_eligibility_paths(grade_code):
    return [row for row in _all_eligibility_paths() if row['grade_code'] == grade_code]


@functools.lru_cache(maxsize=1)
def get_disqualification_text():
    path = _data_dir() / 'kspo_disqualification.txt'
    if not path.exists():
        return ''
    return path.read_text(encoding='utf-8')
