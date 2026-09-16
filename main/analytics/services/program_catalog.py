from django.db.models import Count, Q, Sum

from analytics.models import Institution, ProgramCleanup, QualificationAggregate


def _value(params, key):
    return str(params.get(key, '') or '').strip()


def filtered_cleanups(params, include_usage_filter=True):
    rows = ProgramCleanup.objects.select_related(
        'program__institution', 'matched_sport', 'detail',
    )
    region = _value(params, 'region')
    sport = _value(params, 'sport')
    institution = _value(params, 'institution')
    search = _value(params, 'q')
    if region:
        rows = rows.filter(program__institution__normalized_region=region)
    if sport:
        rows = rows.filter(matched_sport__normalized_name=sport)
    if institution.isdigit():
        rows = rows.filter(program__institution_id=int(institution))
    if search:
        rows = rows.filter(Q(program__name__icontains=search) | Q(cleaned_name__icontains=search))
    if include_usage_filter:
        view = _value(params, 'catalog_status') or 'usable'
        if view == 'usable':
            rows = rows.filter(operating_status='active', is_usable=True)
        elif view == 'active':
            rows = rows.filter(operating_status='active')
        elif view == 'ended':
            rows = rows.filter(operating_status='ended')
        elif view == 'upcoming':
            rows = rows.filter(operating_status='upcoming')
        elif view == 'unknown':
            rows = rows.filter(operating_status='unknown')
        elif view == 'multi_sport':
            rows = rows.filter(exclusion_reason='multi_sport')
        elif view == 'unmatched':
            rows = rows.filter(exclusion_reason='unmatched')
    return rows


def catalog_summary(params):
    rows = filtered_cleanups(params, include_usage_filter=False)
    return rows.aggregate(
        total=Count('id'),
        usable=Count('id', filter=Q(operating_status='active', is_usable=True)),
        active=Count('id', filter=Q(operating_status='active')),
        ended=Count('id', filter=Q(operating_status='ended')),
        upcoming=Count('id', filter=Q(operating_status='upcoming')),
        unknown=Count('id', filter=Q(operating_status='unknown')),
        multi_sport=Count('id', filter=Q(exclusion_reason='multi_sport')),
        unmatched=Count('id', filter=Q(exclusion_reason='unmatched')),
    )


def regional_program_qualification_comparison(params):
    region = _value(params, 'region')
    sport = _value(params, 'sport')
    year = _value(params, 'year')

    cleanups = ProgramCleanup.objects.filter(
        operating_status='active', is_usable=True, matched_sport__isnull=False,
    )
    qualifications = QualificationAggregate.objects.all()
    if region:
        cleanups = cleanups.filter(program__institution__normalized_region=region)
        qualifications = qualifications.filter(normalized_region=region)
    if sport:
        cleanups = cleanups.filter(matched_sport__normalized_name=sport)
        qualifications = qualifications.filter(normalized_sport=sport)
    if year.isdigit():
        qualifications = qualifications.filter(acquisition_year=int(year))

    program_groups = cleanups.values(
        'program__institution__normalized_region',
        'matched_sport__normalized_name', 'matched_sport__name',
    ).annotate(total=Count('id'))
    qualification_groups = qualifications.values(
        'normalized_region', 'normalized_sport', 'sport',
    ).annotate(total=Sum('acquisition_count'))

    stats = {}
    for row in program_groups:
        key = (
            row['program__institution__normalized_region'],
            row['matched_sport__normalized_name'],
        )
        stats.setdefault(key, {
            'region_key': key[0], 'sport_key': key[1],
            'sport': row['matched_sport__name'],
            'program_count': 0, 'qualification_count': 0,
        })['program_count'] += row['total']
    for row in qualification_groups:
        key = (row['normalized_region'], row['normalized_sport'])
        stats.setdefault(key, {
            'region_key': key[0], 'sport_key': key[1],
            'sport': row['sport'] or row['normalized_sport'] or '미상',
            'program_count': 0, 'qualification_count': 0,
        })['qualification_count'] += row['total'] or 0

    region_labels = {}
    for key, label in Institution.objects.exclude(normalized_region='').values_list(
        'normalized_region', 'region',
    ).order_by('normalized_region', 'region'):
        region_labels.setdefault(key, label or key)
    for row in stats.values():
        row['region'] = region_labels.get(row['region_key'], row['region_key'] or '미상')
        row['supply_per_program'] = (
            row['qualification_count'] / row['program_count']
            if row['program_count'] else None
        )

    summary_source = filtered_cleanups({'region': region}, include_usage_filter=False)
    summary = summary_source.aggregate(
        total=Count('id'),
        usable=Count('id', filter=Q(operating_status='active', is_usable=True)),
        unknown=Count('id', filter=Q(operating_status='unknown')),
        multi_sport=Count('id', filter=Q(exclusion_reason='multi_sport')),
        unmatched=Count('id', filter=Q(exclusion_reason='unmatched')),
    )
    summary['qualification_count'] = qualifications.aggregate(total=Sum('acquisition_count'))['total'] or 0
    rows = sorted(stats.values(), key=lambda row: (row['region'], row['sport']))
    return rows, summary
