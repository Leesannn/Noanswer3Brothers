from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

from django.db.models import Sum

from analytics.models import (
    ApplicationStatus,
    CanonicalSport,
    Program,
    ProgramCleanup,
    QualificationAggregate,
)
from analytics.services.normalizers import normalize_sport, normalized_contains, normalized_key


RECENT_APPLICATION_LIMIT = 6
TARGET_KEYWORDS = {
    '유아·아동': ('유아', '어린이', '아동', '초등'),
    '청소년': ('청소년', '중학생', '고등학생', '중고생'),
    '성인': ('성인', '직장인', '대학생'),
    '어르신': ('어르신', '노인', '시니어', '고령'),
    '장애인': ('장애',),
}


@dataclass
class RecommendationResult:
    target: object
    total_score: int
    component_scores: dict
    reasons: list
    metrics: dict
    missing_data: list
    synthetic_data_used: bool


def score_application_rate(rate, maximum=15):
    if rate is None or rate < 50:
        return 0
    if maximum == 15:
        if rate >= 100:
            return 15
        if rate >= 90:
            return 12
        if rate >= 70:
            return 8
        return 4
    if rate >= 100:
        return 20
    if rate >= 90:
        return 16
    if rate >= 70:
        return 12
    return 6


def score_region(mobility, selected_region, institution_region, district='', address=''):
    if mobility == 'any':
        return 10
    if selected_region != institution_region:
        return 0
    if mobility == 'district' and district:
        return 25 if normalized_contains(address, district) else 0
    return 15


def score_sport_match(program, sport):
    source_key = normalized_key(normalize_sport(program.sport))
    selected_key = normalized_key(sport.normalized_name or sport.name)
    if program.match_grade == Program.MatchGrade.EXACT or (
        source_key and source_key == selected_key
    ):
        return 40
    return 25


def _target_matches(programs, preference):
    if not preference:
        return False
    keywords = TARGET_KEYWORDS.get(preference, (preference,))
    return any(
        any(normalized_contains(program.target, keyword) for keyword in keywords)
        for program in programs if program.target
    )


def _weekday_matches(programs, selected_days):
    if not selected_days:
        return None
    return any(any(day in (program.weekdays or '') for day in selected_days) for program in programs)


def _time_matches(programs, time_band):
    if not time_band:
        return None
    for program in programs:
        if program.start_time is None:
            continue
        hour = program.start_time.hour
        if time_band == 'morning' and hour < 12:
            return True
        if time_band == 'afternoon' and 12 <= hour < 18:
            return True
        if time_band == 'evening' and hour >= 18:
            return True
    return False


def _recent_application_stats(program_ids):
    stats = defaultdict(lambda: {
        'rates': [], 'waitlist_count': 0, 'synthetic': False, 'row_count': 0,
    })
    if not program_ids:
        return stats
    seen = Counter()
    rows = ApplicationStatus.objects.filter(program_id__in=program_ids).values(
        'program_id', 'capacity', 'applicants', 'waitlist', 'is_synthetic',
    ).order_by('program_id', '-reference_date', '-pk')
    for row in rows.iterator(chunk_size=5000):
        program_id = row['program_id']
        if seen[program_id] >= RECENT_APPLICATION_LIMIT:
            continue
        seen[program_id] += 1
        item = stats[program_id]
        item['row_count'] += 1
        item['synthetic'] = item['synthetic'] or row['is_synthetic']
        if (row['waitlist'] or 0) > 0:
            item['waitlist_count'] += 1
        if row['capacity'] and row['applicants'] is not None:
            item['rates'].append(row['applicants'] / row['capacity'] * 100)
    return stats


def _combined_application_metrics(programs, application_stats):
    rates = []
    waitlist_count = 0
    synthetic = False
    row_count = 0
    for program in programs:
        item = application_stats.get(program.pk)
        if not item:
            continue
        rates.extend(item['rates'])
        waitlist_count += item['waitlist_count']
        synthetic = synthetic or item['synthetic']
        row_count += item['row_count']
    return {
        'average_rate': sum(rates) / len(rates) if rates else None,
        'waitlist_count': waitlist_count,
        'synthetic': synthetic,
        'row_count': row_count,
    }


def recommend_institutions(criteria, limit=5):
    sport = CanonicalSport.objects.get(pk=criteria['sport_id'], is_active=True)
    region = criteria['region']
    mobility = criteria.get('mobility') or 'province'
    district = criteria.get('district', '').strip()
    target_preference = criteria.get('target', '')

    cleanups = ProgramCleanup.objects.filter(
        operating_status=ProgramCleanup.OperatingStatus.ACTIVE,
        is_usable=True,
        matched_sport=sport,
    ).select_related('program__institution', 'matched_sport')
    if mobility != 'any':
        cleanups = cleanups.filter(program__institution__normalized_region=region)

    groups = defaultdict(list)
    for cleanup in cleanups.iterator(chunk_size=2000):
        institution = cleanup.program.institution
        if mobility == 'district' and district and not normalized_contains(
            f'{institution.address} {institution.name}', district,
        ):
            continue
        groups[institution.pk].append(cleanup)

    program_ids = [row.program_id for rows in groups.values() for row in rows]
    application_stats = _recent_application_stats(program_ids)
    results = []
    for rows in groups.values():
        institution = rows[0].program.institution
        programs = [row.program for row in rows]
        sport_points = max(score_sport_match(program, sport) for program in programs)
        region_points = score_region(
            mobility, region, institution.normalized_region, district,
            f'{institution.address} {institution.name}',
        )
        target_has_data = any(program.target for program in programs)
        target_match = _target_matches(programs, target_preference)
        target_points = 10 if target_preference and target_match else 0
        application = _combined_application_metrics(programs, application_stats)
        rate_points = score_application_rate(application['average_rate'])
        waitlist_points = 10 if application['waitlist_count'] else 0
        components = {
            '종목 일치': sport_points,
            '지역 일치': region_points,
            '대상 일치': target_points,
            '최근 평균 신청률': rate_points,
            '대기자 발생': waitlist_points,
        }
        reasons = [
            '선택 종목과 정확히 일치' if sport_points == 40 else '정규화된 유사 종목과 일치',
        ]
        if region_points == 25:
            reasons.append('희망 시·군·구와 동일')
        elif region_points == 15:
            reasons.append('희망 시·도와 동일')
        else:
            reasons.append('지역 무관 조건을 적용')
        if target_preference:
            reasons.append(
                f'희망 지도 대상({target_preference})과 일치'
                if target_match else f'희망 지도 대상({target_preference}) 일치 정보 없음'
            )
        if application['average_rate'] is not None:
            reasons.append(f"최근 프로그램 평균 신청률 {application['average_rate']:.1f}%")
        if application['waitlist_count']:
            reasons.append(f"최근 대기자 발생 {application['waitlist_count']}회")
        weekdays_match = _weekday_matches(programs, criteria.get('weekdays', []))
        time_match = _time_matches(programs, criteria.get('time_band', ''))
        if weekdays_match:
            reasons.append('선택한 활동 가능 요일과 운영 요일이 겹침')
        if time_match:
            reasons.append('선호 시간대에 운영 프로그램이 있음')

        missing = []
        if not target_has_data:
            missing.append('대상 데이터 없음')
        if application['average_rate'] is None:
            missing.append('신청 데이터 없음')
        if criteria.get('time_band') and not any(p.start_time for p in programs):
            missing.append('시간 데이터 없음')
        program_names = []
        for program in programs:
            if program.name not in program_names:
                program_names.append(program.name)
            if len(program_names) == 3:
                break
        results.append(RecommendationResult(
            target=institution,
            total_score=min(100, sum(components.values())),
            component_scores=components,
            reasons=reasons,
            metrics={
                'program_names': program_names,
                'program_count': len(programs),
                'sport_match': '정확 일치' if sport_points == 40 else '유사 종목 일치',
                'target_match': (
                    '일치' if target_match else ('불일치' if target_has_data else '대상 데이터 없음')
                ),
                'average_rate': application['average_rate'],
                'waitlist_count': application['waitlist_count'],
                'weekday_match': weekdays_match,
                'time_match': time_match,
            },
            missing_data=missing,
            synthetic_data_used=application['synthetic'],
        ))
    results.sort(key=lambda result: (
        -result.total_score,
        -result.component_scores['종목 일치'],
        -result.component_scores['지역 일치'],
        -(result.metrics['average_rate'] if result.metrics['average_rate'] is not None else -1),
        result.target.name,
        result.target.pk,
    ))
    return results[:limit]


def _qualification_map(sports):
    keys = [sport.normalized_name for sport in sports]
    rows = QualificationAggregate.objects.filter(
        normalized_sport__in=keys,
    ).exclude(qualification_type='').values(
        'normalized_sport', 'qualification_type', 'grade',
    ).annotate(total=Sum('acquisition_count')).order_by(
        'normalized_sport', '-total', 'qualification_type', 'grade',
    )
    result = defaultdict(list)
    for row in rows:
        label = row['qualification_type']
        if row['grade']:
            label = f"{label} {row['grade']}"
        result[row['normalized_sport']].append({
            'label': label, 'count': row['total'] or 0,
        })
    return result


def _supply_points(program_count, supply_median, average_rate):
    if average_rate is None or supply_median is None:
        return 0
    if program_count < supply_median and average_rate >= 90:
        return 15
    if program_count <= supply_median and average_rate >= 70:
        return 10
    if average_rate >= 70:
        return 5
    if average_rate >= 50:
        return 3
    return 0


def recommend_qualification_directions(criteria, limit=5):
    selected_ids = {int(criteria['primary_sport_id'])}
    selected_ids.update(int(value) for value in criteria.get('additional_sport_ids', []))
    region = criteria['region']

    cleanups = list(ProgramCleanup.objects.filter(
        operating_status=ProgramCleanup.OperatingStatus.ACTIVE,
        is_usable=True,
        matched_sport__isnull=False,
    ).select_related('program__institution', 'matched_sport').iterator(chunk_size=3000))
    by_sport = defaultdict(list)
    local_by_sport = defaultdict(list)
    sports_by_id = {}
    for cleanup in cleanups:
        sport = cleanup.matched_sport
        sports_by_id[sport.pk] = sport
        by_sport[sport.pk].append(cleanup)
        if cleanup.program.institution.normalized_region == region:
            local_by_sport[sport.pk].append(cleanup)

    for sport in CanonicalSport.objects.filter(pk__in=selected_ids, is_active=True):
        sports_by_id[sport.pk] = sport
    sports = [sports_by_id[key] for key in sorted(sports_by_id)]
    qualification_map = _qualification_map(sports)
    program_ids = [cleanup.program_id for cleanup in cleanups]
    application_stats = _recent_application_stats(program_ids)
    local_counts = [len(rows) for rows in local_by_sport.values() if rows]
    global_counts = [len(rows) for rows in by_sport.values() if rows]
    local_median = median(local_counts) if local_counts else None
    global_median = median(global_counts) if global_counts else None

    results = []
    for sport in sports:
        local_rows = local_by_sport.get(sport.pk, [])
        global_rows = by_sport.get(sport.pk, [])
        analysis_rows = local_rows or global_rows
        programs = [row.program for row in analysis_rows]
        application = _combined_application_metrics(programs, application_stats)
        fallback = not bool(local_rows)
        scope_median = global_median if fallback else local_median
        interest_points = 35 if sport.pk in selected_ids else 0
        region_points = 20 if local_rows else 0
        rate_points = score_application_rate(application['average_rate'], maximum=20)
        supply_points = _supply_points(
            len(analysis_rows), scope_median, application['average_rate'],
        )
        target_has_data = any(program.target for program in programs)
        target_match = _target_matches(programs, criteria.get('target', ''))
        target_points = 10 if criteria.get('target') and target_match else 0
        components = {
            '관심 종목 일치': interest_points,
            '지역 일치': region_points,
            '지역 내 평균 신청률': rate_points,
            '프로그램 공급 부족도': supply_points,
            '지도 대상 일치': target_points,
        }
        reasons = []
        if interest_points:
            reasons.append('선택한 관심 종목과 일치')
        if local_rows:
            reasons.append(f'선택 지역에서 운영 프로그램 {len(local_rows):,}개 확인')
        elif global_rows:
            reasons.append('선택 지역 자료가 부족해 전체 지역 데이터를 참고')
        if application['average_rate'] is not None:
            reasons.append(f"최근 프로그램 평균 신청률 {application['average_rate']:.1f}%")
        if supply_points >= 10:
            reasons.append('수요에 비해 프로그램 공급이 적은 편')
        if target_points:
            reasons.append(f"지도 희망 대상({criteria['target']}) 프로그램이 있음")
        time_match = _time_matches(programs, criteria.get('time_band', ''))
        if time_match:
            reasons.append('선택한 활동 가능 시간대에 운영 프로그램이 있음')
        qualifications = qualification_map.get(sport.normalized_name, [])
        if qualifications:
            reasons.append('보유 자격 데이터에서 종목과 연결되는 자격 종류 확인')

        missing = []
        if fallback:
            missing.append('지역별 데이터 부족—전체 데이터 기준')
        if application['average_rate'] is None:
            missing.append('신청 데이터 없음')
        if criteria.get('target') and not target_has_data:
            missing.append('대상 데이터 없음')
        if criteria.get('time_band') and not any(program.start_time for program in programs):
            missing.append('시간 데이터 없음')
        if not qualifications:
            missing.append('정확한 자격 종목 매핑 없음')

        institutions = defaultdict(list)
        for row in analysis_rows:
            institutions[row.program.institution_id].append(row.program)
        institution_options = []
        for institution_programs in institutions.values():
            institution_application = _combined_application_metrics(
                institution_programs, application_stats,
            )
            institution_options.append((
                institution_application['average_rate'] or -1,
                len(institution_programs),
                institution_programs[0].institution,
            ))
        institution_options.sort(key=lambda item: (-item[0], -item[1], item[2].name, item[2].pk))
        suggested_institution = institution_options[0][2] if institution_options else None
        results.append(RecommendationResult(
            target=sport,
            total_score=min(100, sum(components.values())),
            component_scores=components,
            reasons=reasons,
            metrics={
                'local_program_count': len(local_rows),
                'analysis_program_count': len(analysis_rows),
                'average_rate': application['average_rate'],
                'qualification_count': sport.qualification_count,
                'qualifications': qualifications[:5],
                'supply_median': scope_median,
                'suggested_institution': suggested_institution,
                'suggested_region': (
                    suggested_institution.region if suggested_institution else region
                ),
                'used_national_fallback': fallback,
                'target_match': target_match,
                'time_match': time_match,
            },
            missing_data=missing,
            synthetic_data_used=application['synthetic'],
        ))
    results = [result for result in results if result.total_score > 0]
    results.sort(key=lambda result: (
        -result.total_score,
        -result.component_scores['관심 종목 일치'],
        -result.component_scores['지역 일치'],
        -(result.metrics['average_rate'] if result.metrics['average_rate'] is not None else -1),
        result.target.name,
        result.target.pk,
    ))
    return results[:limit]


def qualification_direction_detail(sport, region=''):
    qualifications = QualificationAggregate.objects.filter(
        normalized_sport=sport.normalized_name,
    ).exclude(qualification_type='').values(
        'qualification_type', 'grade',
    ).annotate(total=Sum('acquisition_count')).order_by('-total', 'qualification_type', 'grade')
    cleanups = ProgramCleanup.objects.filter(
        operating_status=ProgramCleanup.OperatingStatus.ACTIVE,
        is_usable=True,
        matched_sport=sport,
    ).select_related('program__institution')
    regional = cleanups.filter(program__institution__normalized_region=region) if region else cleanups.none()
    used_fallback = bool(region) and not regional.exists()
    selected = regional if region and not used_fallback else cleanups
    groups = defaultdict(list)
    for cleanup in selected.iterator(chunk_size=2000):
        groups[cleanup.program.institution_id].append(cleanup.program)
    application_stats = _recent_application_stats([
        program.pk for programs in groups.values() for program in programs
    ])
    institutions = []
    synthetic = False
    for programs in groups.values():
        stats = _combined_application_metrics(programs, application_stats)
        synthetic = synthetic or stats['synthetic']
        institutions.append({
            'institution': programs[0].institution,
            'program_count': len(programs),
            'average_rate': stats['average_rate'],
            'synthetic': stats['synthetic'],
        })
    institutions.sort(key=lambda item: (
        -(item['average_rate'] if item['average_rate'] is not None else -1),
        -item['program_count'], item['institution'].name, item['institution'].pk,
    ))
    return {
        'qualifications': list(qualifications),
        'institutions': institutions[:5],
        'used_national_fallback': used_fallback,
        'synthetic_data_used': synthetic,
    }
