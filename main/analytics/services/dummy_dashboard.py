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
                'program_name': raw['program_name'],
                'sport': raw['sport'],
                'capacity': capacity,
                'applicants': applicants,
                'waitlist': int(raw['waitlist']),
                'reference_date': raw['reference_date'],
                'rate': rate,
                'demand_status': demand_status(capacity, applicants),
            })
        return rows


def dummy_dashboard_metrics():
    """대시보드 상단 지표 카드용 합계. 더미 CSV가 없으면 None."""
    rows = _load_rows()
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


def dummy_sport_chart(limit=10):
    """'종목별 평균 신청률' 차트용 (labels, rates)."""
    totals = {}
    for row in _load_rows():
        entry = totals.setdefault(row['sport'], {'capacity': 0, 'applicants': 0})
        entry['capacity'] += row['capacity']
        entry['applicants'] += row['applicants']
    ranked = sorted(totals.items(), key=lambda item: item[1]['applicants'], reverse=True)[:limit]
    labels = [name for name, _ in ranked]
    rates = [
        round(values['applicants'] / values['capacity'] * 100, 1) if values['capacity'] else 0.0
        for _, values in ranked
    ]
    return labels, rates


def dummy_application_rows():
    """'프로그램별 신청 현황' 표용 행. 실제 Program 레코드가 아닌 표시 전용 dict."""
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
            'application_rate': row['rate'],
            'demand_status': row['demand_status'],
            'is_synthetic': True,
        }
        for row in _load_rows()
    ]


def dummy_latest_period():
    rows = _load_rows()
    if not rows:
        return None
    return date.fromisoformat(max(row['reference_date'] for row in rows))
