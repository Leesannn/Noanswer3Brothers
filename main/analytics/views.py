import json

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, ExpressionWrapper, F, FloatField, Max, Q, Sum
from django.db.models.functions import ExtractHour
from django.shortcuts import get_object_or_404, render

from .models import (
    ApplicationStatus, CanonicalSport, Institution, Program,
    QualificationAggregate,
)
from .selectors import apply_filters, exam_schedule_fetch_status, filter_options, group_exam_schedule
from .services.analytics import sport_analysis, summary
from .services.dummy_dashboard import (
    dummy_application_rows, dummy_dashboard_metrics, dummy_filtered_rows, dummy_grouped_rates,
    dummy_has_data, dummy_latest_period, dummy_ranked_application_rows,
)
from .services.kspo_grades import GRADES
from .services.license_info import get_disqualification_text, get_eligibility_paths, get_license_grades
from .services.program_catalog import (
    catalog_summary, filtered_cleanups, regional_program_qualification_comparison,
)


def _page(request, queryset, size=30):
    return Paginator(queryset, size).get_page(request.GET.get('page'))


def _base_context(request):
    context = filter_options()
    context['current'] = request.GET
    return context


def _attach_synthetic_insights(programs):
    """현재 페이지의 프로그램에만 최근 합성 현황과 6개월 안내문을 붙인다."""
    programs = list(programs)
    program_map = {program.pk: program for program in programs}
    rates = {program_id: [] for program_id in program_map}
    # program_id 선택성을 우선해 대량 합성 인덱스 전체 스캔을 피한다.
    rows = ApplicationStatus.objects.filter(
        program_id__in=program_map,
    ).order_by('program_id', '-reference_date')
    for item in rows:
        if not item.is_synthetic:
            continue
        program = program_map[item.program_id]
        if not hasattr(program, 'latest_application'):
            program.latest_application = item
        if item.application_rate is not None and len(rates[item.program_id]) < 6:
            rates[item.program_id].append(item.application_rate)
    for program_id, values in rates.items():
        program = program_map[program_id]
        program.synthetic_analysis = None
        if not values:
            continue
        average = sum(values) / len(values)
        if average >= 90:
            action = '증설 검토 대상입니다.'
        elif average >= 50:
            action = '유지·관찰 대상입니다.'
        else:
            action = '시간 또는 대상 개선 검토 대상입니다.'
        program.synthetic_analysis = (
            f'합성 데이터 기준: 최근 6개월 평균 신청률이 {average:.1f}%로 {action}'
        )
    return programs


def dashboard(request):
    qualifications, programs, applications = apply_filters(request.GET)
    shows_synthetic = applications.filter(is_synthetic=True).exists()
    dashboard_applications = applications.filter(is_synthetic=True) if shows_synthetic else applications
    latest_period = dashboard_applications.exclude(reference_date=None).aggregate(
        value=Max('reference_date'),
    )['value']
    if latest_period:
        dashboard_applications = dashboard_applications.filter(reference_date=latest_period)
    metrics = summary(qualifications, programs, dashboard_applications)
    # 프로그램 관련 지표만 별도 정리 결과를 사용한다. 자격증/신청 통계와
    # 기존 원본 Program 행은 그대로 유지한다.
    # 마이그레이션 직후처럼 정리 결과를 아직 생성하지 않은 설치 환경은
    # 기존 지표로 자연스럽게 동작하도록 호환성을 유지한다.
    if filtered_cleanups({}, include_usage_filter=False).exists():
        current_programs = filtered_cleanups(
            request.GET, include_usage_filter=False,
        ).filter(operating_status='active', is_usable=True)
        metrics['program_total'] = current_programs.count()
        metrics['institution_total'] = current_programs.values(
            'program__institution_id',
        ).distinct().count()
    application_rows = list(dashboard_applications.order_by()[:100])
    _attach_synthetic_insights([item.program for item in application_rows])

    # 실제 신청 현황이 전혀 없으면 DB에 쓰지 않고 CSV 더미 데이터로만 화면을 채운다.
    # 검색 옵션(지역·종목·기관·검색어)은 지표 카드·프로그램별 신청 현황 표에 그대로 반영한다.
    using_demo_applications = False
    if not applications.exists() and dummy_has_data():
        using_demo_applications = True
        institution_id = request.GET.get('institution', '').strip()
        institution_name = ''
        if institution_id.isdigit():
            institution_name = Institution.objects.filter(pk=int(institution_id)).values_list(
                'name', flat=True,
            ).first() or ''
        demo_rows = dummy_filtered_rows(
            region=request.GET.get('region', ''),
            sport=request.GET.get('sport', ''),
            institution_name=institution_name,
            search=request.GET.get('q', ''),
        )
        metrics.update(dummy_dashboard_metrics(demo_rows) or {
            'capacity_total': 0, 'applicant_total': 0,
            'average_rate': None, 'full_program_total': 0,
        })
        # 더미 CSV가 수십만 건 규모라 화면에는 앞부분 표본만 나열한다. 집계(metrics)는 전체 기준이다.
        application_rows = dummy_application_rows(demo_rows, limit=100)
        latest_period = dummy_latest_period(demo_rows) or dummy_latest_period()
        shows_synthetic = True

    context = _base_context(request)
    context.update({
        'metrics': metrics,
        'application_rows': application_rows, 'latest_period': latest_period,
        'shows_synthetic': shows_synthetic,
        'using_demo_applications': using_demo_applications,
    })
    return render(request, 'analytics/dashboard.html', context)


def instructor_status(request):
    qualifications, _, _ = apply_filters(request.GET)
    sort_map = {'year': 'acquisition_year', '-year': '-acquisition_year', 'sport': 'sport', '-sport': '-sport', 'count': 'acquisition_count', '-count': '-acquisition_count'}
    qualifications = qualifications.order_by(sort_map.get(request.GET.get('sort'), '-acquisition_year'))
    by_sport = list(qualifications.values('sport').annotate(total=Sum('acquisition_count')).order_by('-total')[:20])
    by_year = qualifications.values('acquisition_year').annotate(total=Sum('acquisition_count')).order_by('acquisition_year')
    by_qualification = qualifications.values('qualification_type', 'grade').annotate(total=Sum('acquisition_count')).order_by('-total')[:15]
    by_region = qualifications.values('region').annotate(total=Sum('acquisition_count')).order_by('-total')[:15]
    context = _base_context(request)
    context.update({
        'page_obj': _page(request, qualifications), 'by_sport': by_sport, 'by_year': by_year,
        'by_qualification': by_qualification, 'by_region': by_region,
        'chart_labels': json.dumps([row['sport'] or '미분류' for row in by_sport], ensure_ascii=False),
        'chart_values': json.dumps([row['total'] for row in by_sport]),
    })
    return render(request, 'analytics/instructors.html', context)


CIRCLED_NUMBERS = '①②③④⑤⑥⑦⑧⑨⑩'


def _label_eligibility_paths(paths):
    """같은 과정 구분(예: 특별과정)이 여러 번 나오면 번호를 붙여 구분할 수 있게 한다."""
    counts = {}
    for path in paths:
        counts[path['course_type']] = counts.get(path['course_type'], 0) + 1

    seen = {}
    labeled = []
    for path in paths:
        course_type = path['course_type']
        if counts[course_type] > 1:
            seen[course_type] = seen.get(course_type, 0) + 1
            index = seen[course_type] - 1
            suffix = CIRCLED_NUMBERS[index] if index < len(CIRCLED_NUMBERS) else str(index + 1)
            display_label = f'{course_type} {suffix}'
        else:
            display_label = course_type
        labeled.append({**path, 'display_label': display_label})
    return labeled


def exam_info(request):
    grade_code = request.GET.get('grade', '').upper()
    valid_codes = {code for code, _ in GRADES}
    if grade_code not in valid_codes:
        grade_code = GRADES[0][0]

    license_grades = get_license_grades()
    return render(request, 'analytics/exam_info.html', {
        'grades': GRADES,
        'grade_code': grade_code,
        'license': license_grades.get(grade_code),
        'eligibility_paths': _label_eligibility_paths(get_eligibility_paths(grade_code)),
        'disqualification_text': get_disqualification_text(),
        'schedule_sections': group_exam_schedule(grade_code),
        'fetch_status': exam_schedule_fetch_status(grade_code),
    })


def program_status(request):
    _, programs, _ = apply_filters(request.GET)
    stats_programs = programs
    match_grade = request.GET.get('match_grade', '').strip()
    if match_grade in dict(Program.MatchGrade.choices):
        programs = programs.filter(match_grade=match_grade)
    sort_map = {'institution': 'institution__name', '-institution': '-institution__name', 'name': 'name', '-name': '-name', 'sport': 'sport', '-sport': '-sport', 'capacity': 'capacity', '-capacity': '-capacity'}
    programs = programs.order_by(sort_map.get(request.GET.get('sort'), 'institution__name'), 'name')
    by_sport = list(programs.values('sport').annotate(total=Count('id')).order_by('-total')[:20])
    by_region = programs.values('institution__region').annotate(total=Count('id')).order_by('-total')[:15]
    by_target = programs.exclude(target='').values('target').annotate(total=Count('id')).order_by('-total')[:15]
    by_hour = programs.exclude(start_time=None).annotate(hour=ExtractHour('start_time')).values('hour').annotate(total=Count('id')).order_by('hour')
    match_stats = stats_programs.aggregate(
        total=Count('id'),
        exact=Count('id', filter=Q(match_grade=Program.MatchGrade.EXACT)),
        similar=Count('id', filter=Q(match_grade=Program.MatchGrade.SIMILAR)),
        review=Count('id', filter=Q(match_grade=Program.MatchGrade.REVIEW)),
        unmatched=Count('id', filter=Q(match_grade=Program.MatchGrade.UNMATCHED)),
    )
    total = match_stats['total'] or 0
    match_stats['rows'] = [
        {'key': key, 'label': label, 'count': match_stats[key], 'rate': match_stats[key] / total * 100 if total else 0}
        for key, label in Program.MatchGrade.choices
    ]
    taxonomy_keys = CanonicalSport.objects.filter(is_active=True).values_list('normalized_name', flat=True)
    baseline = stats_programs.filter(normalized_sport__in=taxonomy_keys).count()
    automatic = match_stats['exact'] + match_stats['similar']
    match_stats.update({
        'baseline_count': baseline, 'baseline_rate': baseline / total * 100 if total else 0,
        'automatic_count': automatic, 'automatic_rate': automatic / total * 100 if total else 0,
        'improvement': (automatic - baseline) / total * 100 if total else 0,
    })
    page_obj = _page(request, programs)
    _attach_synthetic_insights(page_obj.object_list)

    # 실제 신청 현황이 전혀 없으면 프로그램 목록 옆에 CSV 더미 신청 현황을 참고용으로 보여준다.
    using_demo_applications = False
    demo_application_rows = []
    if not ApplicationStatus.objects.exists():
        demo_application_rows = dummy_application_rows(limit=100)
        using_demo_applications = bool(demo_application_rows)

    context = _base_context(request)
    context.update({
        'page_obj': page_obj, 'by_sport': by_sport, 'by_region': by_region,
        'by_target': by_target, 'by_hour': by_hour,
        'chart_labels': json.dumps([row['sport'] or '미분류' for row in by_sport], ensure_ascii=False),
        'chart_values': json.dumps([row['total'] for row in by_sport]),
        'match_stats': match_stats, 'match_grade': match_grade,
        'demo_application_rows': demo_application_rows,
        'using_demo_applications': using_demo_applications,
    })
    return render(request, 'analytics/programs.html', context)


def current_programs(request):
    rows = filtered_cleanups(request.GET).order_by(
        'program__institution__normalized_region', 'matched_sport__name',
        'cleaned_name', 'program__name',
    )
    context = _base_context(request)
    context.update({
        'page_obj': _page(request, rows),
        'catalog_summary': catalog_summary(request.GET),
        'catalog_status': request.GET.get('catalog_status', 'usable'),
    })
    return render(request, 'analytics/current_programs.html', context)


def institution_detail(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    programs = institution.programs.all()
    applications = ApplicationStatus.objects.filter(program__institution=institution).select_related('program')
    capacity = applications.aggregate(total=Sum('capacity'))['total'] or 0
    applicants = applications.aggregate(total=Sum('applicants'))['total'] or 0
    diagnoses = {'유지 검토': [], '개선 필요': [], '증설 검토': []}
    for item in applications:
        if item.demand_status == '개선 검토':
            diagnoses['개선 필요'].append(item)
        elif item.demand_status in ('마감·대기', '수요 높음'):
            diagnoses['증설 검토'].append(item)
        else:
            diagnoses['유지 검토'].append(item)
    sports, thresholds = sport_analysis(
        QualificationAggregate.objects.filter(normalized_region=institution.normalized_region), programs, applications,
    )
    opportunities = [row for row in sports if row['diagnosis'] in ('신규 개설 검토 가능', '지도자 기회 가능성')]
    return render(request, 'analytics/institution_detail.html', {
        'institution': institution, 'programs': programs, 'applications': applications,
        'capacity': capacity, 'applicants': applicants, 'rate': applicants / capacity * 100 if capacity else None,
        'diagnoses': diagnoses, 'opportunities': opportunities, 'thresholds': thresholds,
        'kakao_map_app_key': settings.KAKAO_MAP_APP_KEY,
    })


def application_status(request):
    _, _, applications = apply_filters(request.GET)
    sort_map = {'program': 'program__name', '-program': '-program__name', 'capacity': 'capacity', '-capacity': '-capacity', 'applicants': 'applicants', '-applicants': '-applicants'}
    applications = applications.order_by(sort_map.get(request.GET.get('sort'), '-reference_date'), 'program__name')
    rate_expression = ExpressionWrapper(
        100.0 * F('applicants') / F('capacity'), output_field=FloatField(),
    )
    rated = applications.filter(capacity__gt=0, applicants__isnull=False).annotate(
        calculated_rate=rate_expression,
    )
    by_sport = list(applications.values('program__sport').annotate(capacity_total=Sum('capacity'), applicant_total=Sum('applicants')).order_by('-applicant_total')[:15])
    by_institution = list(applications.values('program__institution__name').annotate(capacity_total=Sum('capacity'), applicant_total=Sum('applicants')).order_by('-applicant_total')[:15])
    for row in by_sport + by_institution:
        row['rate'] = row['applicant_total'] / row['capacity_total'] * 100 if row['capacity_total'] else None
    page_obj = _page(request, applications)
    page_items = list(page_obj.object_list)
    _attach_synthetic_insights([item.program for item in page_items])
    top_items = rated.order_by('-calculated_rate')[:10]
    bottom_items = rated.order_by('calculated_rate')[:10]
    full_items = rated.filter(applicants__gte=F('capacity')).order_by('-reference_date')[:20]

    # 실제 신청 현황이 전혀 없으면 DB에 쓰지 않고 CSV 더미 데이터로만 화면을 채운다.
    # 더미 CSV가 수십만 건 규모라, 페이지네이션은 원본 dict로 먼저 자르고 표시용 dict는
    # 현재 페이지 분량만 만든다.
    using_demo_applications = False
    if not applications.exists():
        demo_raw_rows = dummy_filtered_rows()
        if demo_raw_rows:
            using_demo_applications = True
            top_items, bottom_items, full_items = dummy_ranked_application_rows()
            by_sport = dummy_grouped_rates('sport')
            by_institution = dummy_grouped_rates('institution')
            page_obj = _page(request, demo_raw_rows)
            page_obj.object_list = dummy_application_rows(list(page_obj.object_list))

    context = _base_context(request)
    context.update({
        'page_obj': page_obj,
        'top_items': top_items,
        'bottom_items': bottom_items,
        'full_items': full_items,
        'by_sport': by_sport, 'by_institution': by_institution,
        'using_demo_applications': using_demo_applications,
    })
    return render(request, 'analytics/applications.html', context)


def demand_supply(request):
    rows, comparison_summary = regional_program_qualification_comparison(request.GET)
    context = _base_context(request)
    context.update({
        'page_obj': _page(request, rows, 50),
        'comparison_summary': comparison_summary,
    })
    return render(request, 'analytics/regional_comparison.html', context)
