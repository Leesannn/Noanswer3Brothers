"""연간일정계획(schedPlan.kspo) 파싱.

내부 API가 없고 QF_GRADE_CD 쿼리 파라미터로 폼을 다시 제출(GET)하면 서버가
그 등급의 표를 통째로 렌더링해서 내려주므로, 정적 HTML 파싱만으로 충분하다.
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup
from django.utils import timezone

from .kspo_client import fetch
from .kspo_grades import GRADE_NAMES, schedule_url


PHASE_MAP = {
    '필기시험': '필기시험',
    '연수': '연수',
    '최종 합격자 발표 및 자격증발급(예정)': '최종발표',
}
DATE_RE = re.compile(r'(\d{4})\.(\d{2})\.(\d{2})(?:\s+(\d{2}):(\d{2}))?')


def _text(node):
    if node is None:
        return ''
    for br in node.find_all('br'):
        br.replace_with('\n')
    return '\n'.join(line.strip() for line in node.get_text().split('\n') if line.strip())


def _parse_phase_heading(heading_text):
    """'실기 · 구술 시험 - 동계(설상)' -> ('실기구술시험', '동계(설상)')."""
    heading_text = heading_text.strip()
    if heading_text.startswith('실기'):
        if ' - ' in heading_text:
            _, season = heading_text.split(' - ', 1)
            return '실기구술시험', season.strip()
        return '실기구술시험', ''
    return PHASE_MAP.get(heading_text, heading_text), ''


def _parse_datetime_part(part):
    part = part.strip()
    if not part:
        return None
    match = DATE_RE.search(part)
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    naive = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0))
    return timezone.make_aware(naive)


def _parse_range(raw_text):
    """'2026.04.02 10:00 (목) ~ 2026.04.02 18:00 (목)' -> (start_iso, end_iso)."""
    if '~' in raw_text:
        left, right = raw_text.split('~', 1)
        return _parse_datetime_part(left), _parse_datetime_part(right)
    return None, _parse_datetime_part(raw_text)


def parse_schedule_html(html, grade_code):
    """schedPlan.kspo 응답 HTML -> ExamSchedule에 저장할 dict 리스트."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = []

    for heading in soup.select('div.comContTit h5.contTit'):
        heading_text = heading.get_text(strip=True)
        if heading_text == '자격등급 선택':
            continue
        phase, season = _parse_phase_heading(heading_text)

        table_container = heading.find_parent('div', class_='comContTit')
        table = None
        for sibling in table_container.find_next_siblings('div'):
            table = sibling.find('table', class_='tableType')
            if table:
                break
        if table is None:
            continue

        for tr in table.select('tbody tr'):
            course_type = ''
            cells = tr.find_all(['th', 'td'])
            milestone_cells = cells
            first_cell = cells[0] if cells else None
            if first_cell is not None and 'bgBlue' in (first_cell.get('class') or []):
                course_type = _text(first_cell.select_one('.cont'))
                milestone_cells = cells[1:]

            for cell in milestone_cells:
                tit = cell.select_one('.tit')
                cont = cell.select_one('.cont')
                milestone = tit.get_text(strip=True) if tit else ''
                raw_text = _text(cont)
                if not milestone:
                    continue
                start_at, end_at = _parse_range(raw_text)
                rows.append({
                    'grade_code': grade_code,
                    'grade_name': GRADE_NAMES.get(grade_code, grade_code),
                    'phase': phase,
                    'season': season,
                    'course_type': course_type,
                    'milestone': milestone,
                    'start_at': start_at,
                    'end_at': end_at,
                    'raw_text': raw_text,
                })
    return rows


def fetch_schedule(grade_code):
    """네트워크 요청 + 파싱을 함께 수행. 실패 시 KspoFetchError가 전파된다."""
    html = fetch(schedule_url(grade_code))
    return parse_schedule_html(html, grade_code)
