from django import forms
from django.contrib.auth.hashers import check_password, make_password

from .models import Comment, Post


def _apply_widget_classes(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            continue
        css_class = 'form-select' if isinstance(widget, forms.Select) else 'form-control'
        widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css_class}".strip()


class PostForm(forms.ModelForm):
    password = forms.CharField(
        label='비밀번호', widget=forms.PasswordInput, min_length=4, max_length=20,
        help_text='수정·삭제할 때 필요하니 잊지 마세요.',
    )

    class Meta:
        model = Post
        fields = ['category', 'title', 'nickname', 'content']
        labels = {'category': '게시판', 'title': '제목', 'nickname': '닉네임', 'content': '내용'}
        widgets = {'content': forms.Textarea(attrs={'rows': 10})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_widget_classes(self.fields)

    def save(self, commit=True):
        post = super().save(commit=False)
        post.password_hash = make_password(self.cleaned_data['password'])
        if commit:
            post.save()
        return post


class PostEditForm(forms.ModelForm):
    password = forms.CharField(label='비밀번호', widget=forms.PasswordInput)

    class Meta:
        model = Post
        fields = ['category', 'title', 'content']
        labels = {'category': '게시판', 'title': '제목', 'content': '내용'}
        widgets = {'content': forms.Textarea(attrs={'rows': 10})}

    def __init__(self, *args, **kwargs):
        self.instance_password_hash = kwargs.pop('password_hash')
        super().__init__(*args, **kwargs)
        _apply_widget_classes(self.fields)

    def clean_password(self):
        password = self.cleaned_data['password']
        if not check_password(password, self.instance_password_hash):
            raise forms.ValidationError('비밀번호가 일치하지 않습니다.')
        return password


class PasswordConfirmForm(forms.Form):
    """게시글·댓글 삭제 시 비밀번호만 확인하는 폼."""

    password = forms.CharField(label='비밀번호', widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        self.instance_password_hash = kwargs.pop('password_hash')
        super().__init__(*args, **kwargs)
        _apply_widget_classes(self.fields)

    def clean_password(self):
        password = self.cleaned_data['password']
        if not check_password(password, self.instance_password_hash):
            raise forms.ValidationError('비밀번호가 일치하지 않습니다.')
        return password


class CommentForm(forms.ModelForm):
    password = forms.CharField(label='비밀번호', widget=forms.PasswordInput, min_length=4, max_length=20)

    class Meta:
        model = Comment
        fields = ['nickname', 'content']
        labels = {'nickname': '닉네임', 'content': '댓글'}
        widgets = {'content': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_widget_classes(self.fields)

    def save(self, post, commit=True):
        comment = super().save(commit=False)
        comment.post = post
        comment.password_hash = make_password(self.cleaned_data['password'])
        if commit:
            comment.save()
        return comment
