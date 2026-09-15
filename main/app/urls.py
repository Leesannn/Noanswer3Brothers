from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'analytics'

urlpatterns = [
    path('', RedirectView.as_view(
        pattern_name='analytics:recommendation_start', permanent=False,
    ), name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('recommendations/', views.recommendation_start, name='recommendation_start'),
    path('recommendations/licensed/', views.licensed_recommendation_form, name='licensed_recommendation_form'),
    path('recommendations/licensed/results/', views.licensed_recommendation_results, name='licensed_recommendation_results'),
    path('recommendations/unlicensed/', views.unlicensed_recommendation_form, name='unlicensed_recommendation_form'),
    path('recommendations/unlicensed/results/', views.unlicensed_recommendation_results, name='unlicensed_recommendation_results'),
    path('recommendations/qualifications/<int:pk>/', views.qualification_recommendation_detail, name='qualification_recommendation_detail'),
    path('upload/', views.upload_data, name='upload'),
    path('upload/<int:batch_id>/mapping/', views.map_upload, name='upload_mapping'),
    path('upload/<int:batch_id>/errors.csv', views.download_errors, name='download_errors'),
    path('instructors/', views.instructor_status, name='instructors'),
    path('exam-info/', views.exam_info, name='exam_info'),
    path('programs/', views.program_status, name='programs'),
    path('current-programs/', views.current_programs, name='current_programs'),
    path('institutions/<int:pk>/', views.institution_detail, name='institution_detail'),
    path('applications/', views.application_status, name='applications'),
    path('demand-supply/', views.demand_supply, name='demand_supply'),
]
