from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'analytics'

urlpatterns = [
    path('', RedirectView.as_view(
        pattern_name='recommendations:recommendation_start', permanent=False,
    ), name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('instructors/', views.instructor_status, name='instructors'),
    path('exam-info/', views.exam_info, name='exam_info'),
    path('programs/', views.program_status, name='programs'),
    path('current-programs/', views.current_programs, name='current_programs'),
    path('institutions/<int:pk>/', views.institution_detail, name='institution_detail'),
    path('applications/', views.application_status, name='applications'),
    path('demand-supply/', views.demand_supply, name='demand_supply'),
]
