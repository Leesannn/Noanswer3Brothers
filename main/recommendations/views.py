from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin

from analytics.models import CanonicalSport, Institution, ProgramCleanup

from .forms import LicensedRecommendationForm, UnlicensedRecommendationForm
from .services import (
    qualification_direction_detail,
    recommend_institutions,
    recommend_qualification_directions,
)


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


@xframe_options_sameorigin
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
            return redirect('recommendations:licensed_recommendation_results')
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
        return redirect('recommendations:licensed_recommendation_form')
    try:
        results = recommend_institutions(criteria)
        sport = CanonicalSport.objects.get(pk=criteria['sport_id'])
    except (CanonicalSport.DoesNotExist, KeyError, ValueError):
        request.session.pop('licensed_recommendation_input', None)
        messages.info(request, '추천 조건을 다시 입력해 주세요.')
        return redirect('recommendations:licensed_recommendation_form')
    return render(request, 'recommendations/institution_results.html', {
        'results': results,
        'criteria': criteria,
        'sport': sport,
        'region_label': _region_label(criteria['region']),
        'shows_synthetic': any(result.synthetic_data_used for result in results),
    })


@xframe_options_sameorigin
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
            return redirect('recommendations:unlicensed_recommendation_results')
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
        return redirect('recommendations:unlicensed_recommendation_form')
    try:
        results = recommend_qualification_directions(criteria)
        selected_sports = CanonicalSport.objects.filter(pk__in=(
            [criteria['primary_sport_id']] + criteria.get('additional_sport_ids', [])
        )).order_by('name')
    except (CanonicalSport.DoesNotExist, KeyError, ValueError):
        request.session.pop('unlicensed_recommendation_input', None)
        messages.info(request, '추천 조건을 다시 입력해 주세요.')
        return redirect('recommendations:unlicensed_recommendation_form')
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
