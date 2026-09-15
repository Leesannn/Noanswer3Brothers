from django.db.models import Q

from .models import Post


def apply_post_filters(params):
    posts = Post.objects.all()

    category = params.get('category', '').strip()
    search = params.get('q', '').strip()

    if category:
        posts = posts.filter(category=category)
    if search:
        posts = posts.filter(Q(title__icontains=search) | Q(content__icontains=search))
    return posts
