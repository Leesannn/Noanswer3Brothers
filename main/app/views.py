import csv
import json

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, ExpressionWrapper, F, FloatField, Max, Q, Sum
from django.db.models.functions import ExtractHour
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    LicensedRecommendationForm,
    MappingForm,
    UnlicensedRecommendationForm,
    UploadForm,
)
from .models import (
    ApplicationStatus, CanonicalSport, Institution, Program, ProgramCleanup,
    QualificationAggregate, UploadBatch,
)
from .selectors import apply_filters, exam_schedule_fetch_status, filter_options, group_exam_schedule
from .services.analytics import sport_analysis, summary
from .services.importers import FIELD_LABELS, ImportValidationError, import_batch, preview, suggest_mapping
from .services.kspo_grades import GRADES
from .services.license_info import get_disqualification_text, get_eligibility_paths, get_license_grades
from .services.program_catalog import (
    catalog_summary, filtered_cleanups, regional_program_qualification_comparison,
)
from .services.recommendations import (
    qualification_direction_detail,
    recommend_institutions,
    recommend_qualification_directions,
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
    sports, thresholds = sport_analysis(qualifications, programs, dashboard_applications)
    application_rows = list(dashboard_applications.order_by()[:100])
    _attach_synthetic_insights([item.program for item in application_rows])
    context = _base_context(request)
    context.update({
        'metrics': metrics, 'sports': sports[:15], 'thresholds': thresholds,
        'chart_labels': json.dumps([row['sport'] for row in sports[:10]], ensure_ascii=False),
        'chart_rates': json.dumps([round(row['rate'] or 0, 1) for row in sports[:10]]),
        'application_rows': application_rows, 'latest_period': latest_period,
        'shows_synthetic': shows_synthetic,
        'recent_uploads': UploadBatch.objects.all()[:5],
    })
    return render(request, 'analytics/dashboard.html', context)


def upload_data(request):
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data['file']
            batch = UploadBatch.objects.create(
                dataset_type=form.cleaned_data['dataset_type'], original_filename=uploaded.name,
                temporary_file=uploaded, sheet_name=form.cleaned_data['sheet_name'],
            )
            try:
                result = preview(batch.temporary_file.path, batch.sheet_name, batch.dataset_type)
                batch.dataset_type = result['dataset_type']
                batch.encoding = result['encoding']
                batch.row_count = result['row_count']
                batch.columns = result['columns']
                batch.missing_counts = result['missing_counts']
                batch.preview_rows = result['preview_rows']
                batch.field_mapping = result['suggested_mapping']
                batch.save()
                return redirect('analytics:upload_mapping', batch_id=batch.pk)
            except (ValueError, OSError) as exc:
                batch.status = UploadBatch.Status.FAILED
                batch.errors = [{'row': '', 'message': str(exc)}]
                batch.save(update_fields=['status', 'errors'])
                messages.error(request, str(exc))
    else:
        form = UploadForm()
    return render(request, 'analytics/upload.html', {'form': form, 'uploads': UploadBatch.objects.all()[:20]})


def map_upload(request, batch_id):
    batch = get_object_or_404(UploadBatch, pk=batch_id)
    suggested = batch.field_mapping or suggest_mapping(batch.dataset_type, batch.columns)
    if request.method == 'POST':
        form = MappingForm(request.POST, dataset_type=batch.dataset_type, columns=batch.columns, suggested=suggested)
        if form.is_valid():
            allow_invalid = form.cleaned_data.pop('allow_invalid', False)
            mapping = {key: value for key, value in form.cleaned_data.items() if value}
            try:
                import_batch(batch, mapping, allow_invalid=allow_invalid)
            except ImportValidationError as exc:
                batch.refresh_from_db()
                batch.status = UploadBatch.Status.FAILED
                batch.failure_count = len(exc.errors)
                batch.errors = exc.errors[:10000]
                batch.field_mapping = mapping
                batch.save(update_fields=['status', 'failure_count', 'errors', 'field_mapping'])
                messages.error(request, str(exc))
            except (ValueError, OSError) as exc:
                batch.status = UploadBatch.Status.FAILED
                batch.errors = [{'row': '', 'message': str(exc)}]
                batch.save(update_fields=['status', 'errors'])
                messages.error(request, str(exc))
            else:
                messages.success(request, f'{batch.success_count:,}개 행을 안전하게 처리했습니다. 오류 제외 {batch.failure_count:,}건')
                return redirect('analytics:upload')
    else:
        form = MappingForm(dataset_type=batch.dataset_type, columns=batch.columns, suggested=suggested)
    missing_rows = [{'column': column, 'count': batch.missing_counts.get(column, 0)} for column in batch.columns]
    return render(request, 'analytics/upload_mapping.html', {
        'batch': batch, 'form': form, 'field_labels': FIELD_LABELS[batch.dataset_type], 'missing_rows': missing_rows,
    })


def download_errors(request, batch_id):
    batch = get_object_or_404(UploadBatch, pk=batch_id)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="upload-errors-{batch.pk}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['행', '오류 내용'])
    for error in batch.errors:
        writer.writerow([error.get('row', ''), error.get('message', '')])
    return response


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
    context = _base_context(request)
    context.update({
        'page_obj': page_obj, 'by_sport': by_sport, 'by_region': by_region,
        'by_target': by_target, 'by_hour': by_hour,
        'chart_labels': json.dumps([row['sport'] or '미분류' for row in by_sport], ensure_ascii=False),
        'chart_values': json.dumps([row['total'] for row in by_sport]),
        'match_stats': match_stats, 'match_grade': match_grade,
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
    context = _base_context(request)
    context.update({
        'page_obj': page_obj,
        'top_items': rated.order_by('-calculated_rate')[:10],
        'bottom_items': rated.order_by('calculated_rate')[:10],
        'full_items': rated.filter(applicants__gte=F('capacity')).order_by('-reference_date')[:20],
        'by_sport': by_sport, 'by_institution': by_institution,
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


def recommendation_start(request):
    available = ProgramCleanup.objects.filter(
        operating_status=ProgramCleanup.OperatingStatus.ACTIVE,
        is_usable=True,
        matched_sport__isnull=False,
    )
    home_metrics = available.aggregate(
        program_count=Count('id'),
        institution_count=Count('program__institution_id', distinct=True),
        sport_count=Count('matched_sport_id', distinct=True),
    )
    return render(request, 'recommendations/start.html', {
        'home_metrics': home_metrics,
    })


def licensed_recommendation_form(request):
    initial = request.session.get('licensed_recommendation_input', {})
    if request.method == 'POST':
        form = LicensedRecommendationForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            request.session['licensed_recommendation_input'] = {
                'qualification_type': cleaned['qualification_type'],
                'sport_id': cleaned['sport'].pk,
                'region': cleaned['region'],
                'district': cleaned['district'],
                'mobility': cleaned['mobility'],
                'target': cleaned['target'],
                'weekdays': cleaned['weekdays'],
                'time_band': cleaned['time_band'],
            }
            return redirect('analytics:licensed_recommendation_results')
    else:
        form_initial = {**initial}
        form_initial['sport'] = initial.get('sport_id')
        form = LicensedRecommendationForm(initial=form_initial)
    return render(request, 'recommendations/licensed_form.html', {'form': form})


def _region_label(region_key):
    row = Institution.objects.filter(normalized_region=region_key).values_list(
        'region', flat=True,
    ).order_by('region').first()
    return row or region_key


def licensed_recommendation_results(request):
    criteria = request.session.get('licensed_recommendation_input')
    if not criteria:
        messages.info(request, '추천 조건을 먼저 입력해 주세요.')
        return redirect('analytics:licensed_recommendation_form')
    try:
        results = recommend_institutions(criteria)
        sport = CanonicalSport.objects.get(pk=criteria['sport_id'])
    except (CanonicalSport.DoesNotExist, KeyError, ValueError):
        request.session.pop('licensed_recommendation_input', None)
        messages.info(request, '추천 조건을 다시 입력해 주세요.')
        return redirect('analytics:licensed_recommendation_form')
    return render(request, 'recommendations/institution_results.html', {
        'results': results,
        'criteria': criteria,
        'sport': sport,
        'region_label': _region_label(criteria['region']),
        'shows_synthetic': any(result.synthetic_data_used for result in results),
    })


def unlicensed_recommendation_form(request):
    initial = request.session.get('unlicensed_recommendation_input', {})
    if request.method == 'POST':
        form = UnlicensedRecommendationForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            request.session['unlicensed_recommendation_input'] = {
                'region': cleaned['region'],
                'primary_sport_id': cleaned['primary_sport'].pk,
                'additional_sport_ids': list(cleaned['additional_sports'].values_list('pk', flat=True)),
                'experience': cleaned['experience'],
                'target': cleaned['target'],
                'time_band': cleaned['time_band'],
            }
            return redirect('analytics:unlicensed_recommendation_results')
    else:
        form_initial = {**initial}
        form_initial['primary_sport'] = initial.get('primary_sport_id')
        form_initial['additional_sports'] = initial.get('additional_sport_ids', [])
        form = UnlicensedRecommendationForm(initial=form_initial)
    return render(request, 'recommendations/unlicensed_form.html', {'form': form})


def unlicensed_recommendation_results(request):
    criteria = request.session.get('unlicensed_recommendation_input')
    if not criteria:
        messages.info(request, '추천 조건을 먼저 입력해 주세요.')
        return redirect('analytics:unlicensed_recommendation_form')
    try:
        results = recommend_qualification_directions(criteria)
        selected_sports = CanonicalSport.objects.filter(pk__in=(
            [criteria['primary_sport_id']] + criteria.get('additional_sport_ids', [])
        )).order_by('name')
    except (CanonicalSport.DoesNotExist, KeyError, ValueError):
        request.session.pop('unlicensed_recommendation_input', None)
        messages.info(request, '추천 조건을 다시 입력해 주세요.')
        return redirect('analytics:unlicensed_recommendation_form')
    return render(request, 'recommendations/qualification_results.html', {
        'results': results,
        'criteria': criteria,
        'selected_sports': selected_sports,
        'region_label': _region_label(criteria['region']),
        'shows_synthetic': any(result.synthetic_data_used for result in results),
    })


def qualification_recommendation_detail(request, pk):
    sport = get_object_or_404(CanonicalSport, pk=pk, is_active=True)
    criteria = request.session.get('unlicensed_recommendation_input', {})
    region = criteria.get('region', '')
    detail = qualification_direction_detail(sport, region)
    return render(request, 'recommendations/qualification_detail.html', {
        'sport': sport,
        'region_label': _region_label(region) if region else '',
        **detail,
    })
