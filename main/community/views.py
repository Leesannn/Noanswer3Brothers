from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render

from . import selectors
from .forms import CommentForm, PasswordConfirmForm, PostEditForm, PostForm
from .models import Post


def job_postings(request):
    return render(request, 'community/coming_soon.html', {
        'page_title': '일자리 공고',
        'page_description': '일자리 공고 서비스는 준비 중입니다.',
    })


def mentoring(request):
    return render(request, 'community/coming_soon.html', {
        'page_title': '멘토·멘티',
        'page_description': '멘토·멘티 서비스는 준비 중입니다.',
    })


def post_list(request):
    posts = selectors.apply_post_filters(request.GET)
    page_obj = Paginator(posts, 20).get_page(request.GET.get('page'))
    context = {
        'page_obj': page_obj, 'current': request.GET,
        'category_choices': Post.Category.choices,
    }
    return render(request, 'community/list.html', context)


def post_detail(request, pk):
    Post.objects.filter(pk=pk).update(view_count=F('view_count') + 1)
    post = get_object_or_404(Post, pk=pk)

    if request.method == 'POST':
        comment_form = CommentForm(request.POST)
        if comment_form.is_valid():
            comment_form.save(post=post)
            messages.success(request, '댓글이 등록되었습니다.')
            return redirect('community:post_detail', pk=post.pk)
    else:
        comment_form = CommentForm()

    return render(request, 'community/detail.html', {
        'post': post,
        'comments': post.comments.all(),
        'comment_form': comment_form,
    })


def post_create(request):
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save()
            messages.success(request, '게시글이 등록되었습니다.')
            return redirect('community:post_detail', pk=post.pk)
    else:
        form = PostForm()
    return render(request, 'community/create.html', {'form': form})


def post_edit(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == 'POST':
        form = PostEditForm(request.POST, instance=post, password_hash=post.password_hash)
        if form.is_valid():
            form.save()
            messages.success(request, '게시글을 수정했습니다.')
            return redirect('community:post_detail', pk=post.pk)
    else:
        form = PostEditForm(instance=post, password_hash=post.password_hash)
    return render(request, 'community/edit.html', {'form': form, 'post': post})


def post_delete(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == 'POST':
        form = PasswordConfirmForm(request.POST, password_hash=post.password_hash)
        if form.is_valid():
            post.delete()
            messages.success(request, '게시글을 삭제했습니다.')
            return redirect('community:post_list')
        messages.error(request, '비밀번호가 일치하지 않습니다.')
    return redirect('community:post_detail', pk=pk)


def comment_delete(request, pk, comment_id):
    post = get_object_or_404(Post, pk=pk)
    comment = get_object_or_404(post.comments, pk=comment_id)
    if request.method == 'POST':
        form = PasswordConfirmForm(request.POST, password_hash=comment.password_hash)
        if form.is_valid():
            comment.delete()
            messages.success(request, '댓글을 삭제했습니다.')
        else:
            messages.error(request, '비밀번호가 일치하지 않습니다.')
    return redirect('community:post_detail', pk=pk)
