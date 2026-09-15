from django.urls import path

from . import views

app_name = 'community'

urlpatterns = [
    path('', views.post_list, name='post_list'),
    path('posts/new/', views.post_create, name='post_create'),
    path('posts/<int:pk>/', views.post_detail, name='post_detail'),
    path('posts/<int:pk>/edit/', views.post_edit, name='post_edit'),
    path('posts/<int:pk>/delete/', views.post_delete, name='post_delete'),
    path('posts/<int:pk>/comments/<int:comment_id>/delete/', views.comment_delete, name='comment_delete'),
]
