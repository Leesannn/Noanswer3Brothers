from django.urls import path

from . import views

app_name = 'substitutes'

urlpatterns = [
    path('', views.posting_list, name='posting_list'),
    path('postings/new/', views.posting_create, name='posting_create'),
    path('postings/<int:pk>/', views.posting_detail, name='posting_detail'),
    path('postings/<int:pk>/apply/', views.application_apply, name='application_apply'),
    path('postings/<int:pk>/manage/<str:token>/', views.applicant_manage, name='applicant_manage'),
    path(
        'postings/<int:pk>/manage/<str:token>/applications/<int:application_id>/evaluate/',
        views.application_evaluate, name='application_evaluate',
    ),
]
