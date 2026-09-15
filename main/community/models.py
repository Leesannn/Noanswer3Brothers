from django.db import models


class Post(models.Model):
    class Category(models.TextChoices):
        FREE = 'free', '자유게시판'
        EXAM_INFO = 'exam_info', '시험정보 공유'
        MATERIALS = 'materials', '기출문제·자료실'
        QNA = 'qna', '자격증 Q&A'

    category = models.CharField(max_length=20, choices=Category.choices, default=Category.FREE, db_index=True)
    title = models.CharField(max_length=200)
    nickname = models.CharField(max_length=30)
    password_hash = models.CharField(max_length=128, editable=False)
    content = models.TextField()
    view_count = models.PositiveIntegerField(default=0)
    is_notice = models.BooleanField(default=False, help_text='체크하면 목록 상단에 고정됩니다.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_notice', '-created_at']
        verbose_name = '게시글'
        verbose_name_plural = '게시글'

    def __str__(self):
        return self.title


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    nickname = models.CharField(max_length=30)
    password_hash = models.CharField(max_length=128, editable=False)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = '댓글'
        verbose_name_plural = '댓글'

    def __str__(self):
        return f'{self.nickname}: {self.content[:20]}'
