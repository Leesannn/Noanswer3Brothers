"""sqms.kspo.or.kr 요청 공통 처리.

공공기관 사이트이므로 매 요청 사이 딜레이를 두고, User-Agent를 명시하며,
실패 시 예외로 알려 호출부(관리 명령어)가 기존 캐시를 보존하도록 한다.
"""
import time

import requests

USER_AGENT = 'Mozilla/5.0 (compatible; SportsCareerCompassBot/1.0)'
REQUEST_TIMEOUT = 10
REQUEST_DELAY_SECONDS = 1.5


class KspoFetchError(Exception):
    """sqms.kspo.or.kr에서 데이터를 가져오거나 파싱하지 못했을 때."""


def fetch(url, *, delay=REQUEST_DELAY_SECONDS):
    """요청 사이 딜레이를 두고 페이지를 가져온다. 실패 시 KspoFetchError."""
    if delay:
        time.sleep(delay)
    try:
        response = requests.get(
            url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise KspoFetchError(f'{url} 요청 실패: {exc}') from exc
    response.encoding = response.apparent_encoding or 'utf-8'
    return response.text
