from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    ApplicationStatus, CanonicalSport, ExamSchedule, ExamScheduleFetchStatus, Institution,
    Program, QualificationAggregate,
)


def apply_filters(params):
    qualifications = QualificationAggregate.objects.all()
    programs = Program.objects.select_related('institution', 'matched_sport').all()
    applications = ApplicationStatus.objects.select_related('program__institution').all()

    year = params.get('year', '').strip()
    region = params.get('region', '').strip()
    sport = params.get('sport', '').strip()
    institution = params.get('institution', '').strip()
    target = params.get('target', '').strip()
    status = params.get('status', '').strip()
    search = params.get('q', '').strip()

    if year.isdigit():
        qualifications = qualifications.filter(acquisition_year=int(year))
        applications = applications.filter(recruitment_year=int(year))
        programs = programs.filter(Q(start_date__year=int(year)) | Q(start_date__isnull=True))
    if region:
        qualifications = qualifications.filter(normalized_region=region)
        programs = programs.filter(institution__normalized_region=region)
        applications = applications.filter(program__institution__normalized_region=region)
    if sport:
        qualifications = qualifications.filter(normalized_sport=sport)
        programs = programs.filter(
            Q(matched_sport__normalized_name=sport) |
            Q(matched_sport__isnull=True, normalized_sport=sport)
        )
        applications = applications.filter(
            Q(program__matched_sport__normalized_name=sport) |
            Q(program__matched_sport__isnull=True, program__normalized_sport=sport)
        )
    if institution.isdigit():
        programs = programs.filter(institution_id=int(institution))
        applications = applications.filter(program__institution_id=int(institution))
    if target:
        programs = programs.filter(target__icontains=target)
        applications = applications.filter(program__target__icontains=target)
    if status:
        programs = programs.filter(status=status)
        applications = applications.filter(program__status=status)
    if search:
        qualifications = qualifications.filter(Q(sport__icontains=search) | Q(qualification_type__icontains=search))
        programs = programs.filter(Q(name__icontains=search) | Q(institution__name__icontains=search) | Q(sport__icontains=search))
        applications = applications.filter(Q(program__name__icontains=search) | Q(program__institution__name__icontains=search))
    return qualifications, programs, applications


def filter_options():
    return {
        'years': QualificationAggregate.objects.exclude(acquisition_year=None).values_list('acquisition_year', flat=True).distinct().order_by('-acquisition_year'),
        'region_options': Institution.objects.exclude(normalized_region='').values_list('normalized_region', 'region').distinct().order_by('region'),
        'sport_options': CanonicalSport.objects.filter(is_active=True).values_list('normalized_name', 'name').order_by('name'),
        'institutions': Institution.objects.all().order_by('name'),
        'targets': Program.objects.exclude(target='').values_list('target', flat=True).distinct().order_by('target')[:100],
        'statuses': Program.objects.exclude(status='').values_list('status', flat=True).distinct().order_by('status'),
    }


UPCOMING_WINDOW_DAYS = 14


def group_exam_schedule(grade_code):
    """등급의 ExamSchedule 캐시를 화면에 뿌리기 좋은 phase/season/course_type 트리로 묶는다."""
    rows = ExamSchedule.objects.filter(grade_code=grade_code)
    soon_cutoff = timezone.now() + timedelta(days=UPCOMING_WINDOW_DAYS)

    sections = {}
    for row in rows:
        section_key = (row.phase, row.season)
        section = sections.setdefault(section_key, {'phase': row.phase, 'season': row.season, 'courses': {}})
        course = section['courses'].setdefault(row.course_type, {'course_type': row.course_type, 'milestones': []})
        course['milestones'].append({
            'label': row.milestone,
            'text': row.raw_text or '미정',
            'is_upcoming': bool(row.end_at and timezone.now() <= row.end_at <= soon_cutoff),
        })

    ordered_phases = ['필기시험', '실기구술시험', '연수', '최종발표']
    result = []
    for phase in ordered_phases:
        matches = [s for key, s in sections.items() if key[0] == phase]
        matches.sort(key=lambda s: s['season'])
        for section in matches:
            section['courses'] = list(section['courses'].values())
            result.append(section)
    return result


def exam_schedule_fetch_status(grade_code):
    return ExamScheduleFetchStatus.objects.filter(grade_code=grade_code).first()
