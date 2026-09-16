from django.urls import path

from . import views

app_name = 'recommendations'

urlpatterns = [
    path('', views.recommendation_start, name='recommendation_start'),
    path('licensed/', views.licensed_recommendation_form, name='licensed_recommendation_form'),
    path('licensed/results/', views.licensed_recommendation_results, name='licensed_recommendation_results'),
    path('unlicensed/', views.unlicensed_recommendation_form, name='unlicensed_recommendation_form'),
    path('unlicensed/results/', views.unlicensed_recommendation_results, name='unlicensed_recommendation_results'),
    path('qualifications/<int:pk>/', views.qualification_recommendation_detail, name='qualification_recommendation_detail'),
]
