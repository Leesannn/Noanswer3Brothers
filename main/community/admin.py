from django.contrib import admin

from .models import Comment, Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'nickname', 'view_count', 'is_notice', 'created_at')
    search_fields = ('title', 'content', 'nickname')
    list_filter = ('category', 'is_notice', 'created_at')
    readonly_fields = ('password_hash', 'view_count', 'created_at', 'updated_at')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('post', 'nickname', 'content', 'created_at')
    search_fields = ('content', 'nickname', 'post__title')
    list_filter = ('created_at',)
    readonly_fields = ('password_hash', 'created_at')
