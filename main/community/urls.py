from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'community'

urlpatterns = [
    path('', RedirectView.as_view(
        pattern_name='community:post_list', permanent=False,
    ), name='home'),
    path('community_board/', views.post_list, name='post_list'),
    path('jobs/', views.job_postings, name='job_postings'),
    path('mentoring/', views.mentoring, name='mentoring'),
    path('community_board/posts/new/', views.post_create, name='post_create'),
    path('community_board/posts/<int:pk>/', views.post_detail, name='post_detail'),
    path('community_board/posts/<int:pk>/edit/', views.post_edit, name='post_edit'),
    path('community_board/posts/<int:pk>/delete/', views.post_delete, name='post_delete'),
    path(
        'community_board/posts/<int:pk>/comments/<int:comment_id>/delete/',
        views.comment_delete, name='comment_delete',
    ),
]
