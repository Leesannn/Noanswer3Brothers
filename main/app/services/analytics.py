from statistics import median

from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Q, Sum

from app.models import ApplicationStatus, Program, QualificationAggregate


def application_rate(capacity, applicants):
    if capacity in (None, 0) or applicants is None:
        return None
    return applicants / capacity * 100


def demand_status(capacity, applicants):
    rate = application_rate(capacity, applicants)
    if rate is None:
        return '데이터 부족'
    if rate >= 100:
        return '마감·대기'
    if rate >= 90:
        return '수요 높음'
    if rate >= 50:
        return '보통'
    return '개선 검토'


def summary(qualifications, programs, applications):
    qualification_total = qualifications.aggregate(total=Sum('acquisition_count'))['total'] or 0
    rate_expression = ExpressionWrapper(
        100.0 * F('applicants') / F('capacity'), output_field=FloatField(),
    )
    application_totals = applications.aggregate(
        capacity_total=Sum('capacity'),
        applicant_total=Sum('applicants'),
        rate=Avg(
            rate_expression,
            filter=Q(capacity__gt=0, applicants__isnull=False),
        ),
        full=Count(
            'id', filter=Q(capacity__gt=0, applicants__gte=F('capacity')),
        ),
    )
    return {
        'qualification_total': qualification_total,
        'institution_total': programs.values('institution_id').distinct().count(),
        'program_total': programs.count(),
        'capacity_total': application_totals['capacity_total'] or 0,
        'applicant_total': application_totals['applicant_total'] or 0,
        'average_rate': application_totals['rate'],
        'full_program_total': application_totals['full'],
    }


def sport_analysis(qualifications=None, programs=None, applications=None):
    qualifications = qualifications if qualifications is not None else QualificationAggregate.objects.all()
    programs = programs if programs is not None else Program.objects.all()
    applications = applications if applications is not None else ApplicationStatus.objects.all()
    stats = {}
    for row in qualifications.values('normalized_sport', 'sport').annotate(total=Sum('acquisition_count')):
        key = row['normalized_sport'] or row['sport'] or '미분류'
        stats.setdefault(key, {'sport': row['sport'] or '미분류', 'instructors': 0, 'programs': 0, 'capacity': 0, 'applicants': 0, 'rated': 0, 'full': 0})
        stats[key]['instructors'] += row['total'] or 0
    for row in programs.values('matched_sport__normalized_name', 'matched_sport__name', 'normalized_sport', 'sport').annotate(total=Count('id')):
        key = row['matched_sport__normalized_name'] or row['normalized_sport'] or row['sport'] or '미분류'
        label = row['matched_sport__name'] or row['sport'] or '미분류'
        stats.setdefault(key, {'sport': label, 'instructors': 0, 'programs': 0, 'capacity': 0, 'applicants': 0, 'rated': 0, 'full': 0})
        stats[key]['programs'] += row['total']
    application_groups = applications.values(
        'program__matched_sport__normalized_name', 'program__matched_sport__name',
        'program__normalized_sport', 'program__sport',
    ).annotate(
        capacity_total=Sum('capacity', filter=Q(capacity__gt=0, applicants__isnull=False)),
        applicant_total=Sum('applicants', filter=Q(capacity__gt=0, applicants__isnull=False)),
        rated_total=Count('id', filter=Q(capacity__gt=0, applicants__isnull=False)),
        full_total=Count('id', filter=Q(capacity__gt=0, applicants__gte=F('capacity'))),
    )
    for row in application_groups:
        key = row['program__matched_sport__normalized_name'] or row['program__normalized_sport'] or row['program__sport'] or '미분류'
        label = row['program__matched_sport__name'] or row['program__sport'] or '미분류'
        current = stats.setdefault(key, {
            'sport': label, 'instructors': 0,
            'programs': 0, 'capacity': 0, 'applicants': 0, 'rated': 0, 'full': 0,
        })
        current['capacity'] += row['capacity_total'] or 0
        current['applicants'] += row['applicant_total'] or 0
        current['rated'] += row['rated_total']
        current['full'] += row['full_total']
    instructor_values = [value['instructors'] for value in stats.values() if value['instructors'] > 0]
    program_values = [value['programs'] for value in stats.values() if value['programs'] > 0]
    instructor_mid = median(instructor_values) if instructor_values else None
    program_mid = median(program_values) if program_values else None
    results = []
    for value in stats.values():
        value['rate'] = application_rate(value['capacity'], value['applicants'])
        value['full_rate'] = value['full'] / value['rated'] * 100 if value['rated'] else None
        if value['rate'] is None:
            value['diagnosis'] = '추가 데이터 필요'
        elif instructor_mid is not None and value['instructors'] >= instructor_mid and value['rate'] < 50:
            value['diagnosis'] = '경쟁 과다 가능성'
        elif instructor_mid is not None and value['instructors'] < instructor_mid and value['rate'] >= 90:
            value['diagnosis'] = '지도자 기회 가능성'
        elif program_mid is not None and value['programs'] < program_mid and value['rate'] >= 90:
            value['diagnosis'] = '신규 개설 검토 가능'
        elif program_mid is not None and value['programs'] >= program_mid and value['rate'] < 50:
            value['diagnosis'] = '프로그램 개선 필요'
        elif value['rate'] >= 90 and (value['full_rate'] or 0) >= 50:
            value['diagnosis'] = '증설 검토 가능'
        else:
            value['diagnosis'] = '현재 수준 관찰'
        results.append(value)
    return sorted(results, key=lambda value: (value['rate'] is not None, value['rate'] or -1), reverse=True), {
        'instructor_median': instructor_mid, 'program_median': program_mid,
        'rate_high': 90, 'rate_low': 50, 'full_rate_high': 50,
    }
