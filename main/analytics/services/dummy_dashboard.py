"""대시보드 시연용 더미 신청 현황 로더.

실제 ApplicationStatus 데이터가 없을 때만 대시보드에서 사용한다. DB 용량을 늘리지
않기 위해 DB에는 저장하지 않고 data/dashboard_demo_applications.csv에서만 읽는다.
"""
import csv
import functools
from datetime import date

from django.conf import settings

from .analytics import application_rate, demand_status


def _csv_path():
    return settings.BASE_DIR / 'data' / 'dashboard_demo_applications.csv'


@functools.lru_cache(maxsize=1)
def _load_rows():
    path = _csv_path()
    if not path.exists():
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = []
        for raw in csv.DictReader(f):
            capacity = int(raw['capacity'])
            applicants = int(raw['applicants'])
            rate = application_rate(capacity, applicants)
            rows.append({
                'institution_name': raw['institution_name'],
                'region': raw['region'],
                'program_name': raw['program_name'],
                'sport': raw['sport'],
                'capacity': capacity,
                'applicants': applicants,
                'waitlist': int(raw['waitlist']),
                'reference_date': date.fromisoformat(raw['reference_date']),
                'rate': rate,
                'demand_status': demand_status(capacity, applicants),
            })
        return rows


def dummy_has_data():
    return bool(_load_rows())


@functools.lru_cache(maxsize=64)
def dummy_filtered_rows(region='', sport='', institution_name='', search=''):
    """대시보드 검색 옵션(지역·종목·기관·검색어)에 맞춰 더미 CSV 행을 걸러낸다."""
    region = (region or '').strip()
    sport = (sport or '').strip()
    institution_name = (institution_name or '').strip()
    search = (search or '').strip()

    def matches(row):
        if region and row['region'] != region:
            return False
        if sport and row['sport'] != sport:
            return False
        if institution_name and row['institution_name'] != institution_name:
            return False
        if search:
            haystack = f"{row['institution_name']} {row['program_name']} {row['sport']}"
            if search not in haystack:
                return False
        return True

    return [row for row in _load_rows() if matches(row)]


def dummy_dashboard_metrics(rows=None):
    """대시보드 상단 지표 카드용 합계. 더미 CSV(또는 필터 결과)가 없으면 None."""
    rows = _load_rows() if rows is None else rows
    if not rows:
        return None
    capacity_total = sum(row['capacity'] for row in rows)
    applicant_total = sum(row['applicants'] for row in rows)
    full_total = sum(1 for row in rows if row['applicants'] >= row['capacity'])
    return {
        'capacity_total': capacity_total,
        'applicant_total': applicant_total,
        'average_rate': applicant_total / capacity_total * 100 if capacity_total else None,
        'full_program_total': full_total,
    }


def dummy_application_rows(rows=None, limit=None):
    """'프로그램별 신청 현황' 표용 행. 실제 Program 레코드가 아닌 표시 전용 dict.

    rows가 매우 클 수 있어(수십만 건) 화면에 실제로 나열할 목적이라면 limit으로
    미리 잘라 표시용 dict 생성 비용을 제한한다. 합계 계산에는 limit을 넘기지 않는다.
    """
    rows = _load_rows() if rows is None else rows
    if limit is not None:
        rows = rows[:limit]
    return [
        {
            'program': {
                'institution': {'name': row['institution_name']},
                'name': row['program_name'],
                'sport': row['sport'],
                'synthetic_analysis': (
                    f"시연용 더미 데이터 기준: 신청률 {row['rate']:.1f}%로 '{row['demand_status']}' 상태입니다."
                    if row['rate'] is not None else None
                ),
            },
            'capacity': row['capacity'],
            'applicants': row['applicants'],
            'waitlist': row['waitlist'],
            'reference_date': row['reference_date'],
            'application_rate': row['rate'],
            'demand_status': row['demand_status'],
            'is_synthetic': True,
        }
        for row in rows
    ]


def dummy_ranked_application_rows(rows=None, limit=10, full_limit=20):
    """신청률 상위/하위, 정원 마감 표용 (top_items, bottom_items, full_items).

    rows가 수십만 건일 수 있어, 정렬·필터는 원본 dict(가벼움)로 먼저 추리고
    표시용 dict 생성(dummy_application_rows)은 실제로 보여줄 소수 항목에만 적용한다.
    """
    raw_rows = _load_rows() if rows is None else rows
    rated = [row for row in raw_rows if row['rate'] is not None]
    top_raw = sorted(rated, key=lambda row: row['rate'], reverse=True)[:limit]
    bottom_raw = sorted(rated, key=lambda row: row['rate'])[:limit]
    full_raw = [row for row in raw_rows if row['applicants'] >= row['capacity']][:full_limit]
    return (
        dummy_application_rows(top_raw),
        dummy_application_rows(bottom_raw),
        dummy_application_rows(full_raw),
    )


@functools.lru_cache(maxsize=8)
def dummy_grouped_rates(group_by, rows=None):
    """'sport' 또는 'institution' 기준 합계 신청률. applications.html의 by_sport/by_institution 형태."""
    rows = _load_rows() if rows is None else rows
    field = 'sport' if group_by == 'sport' else 'institution_name'
    label_key = 'program__sport' if group_by == 'sport' else 'program__institution__name'
    totals = {}
    for row in rows:
        entry = totals.setdefault(row[field], {'capacity': 0, 'applicants': 0})
        entry['capacity'] += row['capacity']
        entry['applicants'] += row['applicants']
    ranked = sorted(totals.items(), key=lambda item: item[1]['applicants'], reverse=True)[:15]
    return [
        {
            label_key: name,
            'capacity_total': values['capacity'],
            'applicant_total': values['applicants'],
            'rate': values['applicants'] / values['capacity'] * 100 if values['capacity'] else None,
        }
        for name, values in ranked
    ]


def dummy_latest_period(rows=None):
    rows = _load_rows() if rows is None else rows
    if not rows:
        return None
    return max(row['reference_date'] for row in rows)
