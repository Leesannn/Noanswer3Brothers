from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.shortcuts import render
from django.utils import timezone

from .models import Application, CenterContact, PhoneIdentity, Posting, ReputationRecord


class HideReasonForm(forms.Form):
    reason = forms.CharField(
        label='숨김 사유', widget=forms.Textarea,
        help_text='명백한 오류·허위 신고인 경우에만 사용하세요. 기록은 삭제되지 않고 노출만 차단됩니다.',
    )


@admin.register(PhoneIdentity)
class PhoneIdentityAdmin(admin.ModelAdmin):
    list_display = ('phone_masked', 'first_seen_at')
    search_fields = ('phone_masked',)
    readonly_fields = ('phone_hash', 'phone_masked', 'first_seen_at')


@admin.register(CenterContact)
class CenterContactAdmin(admin.ModelAdmin):
    list_display = ('institution_name', 'phone_masked', 'institution', 'verified_at')
    search_fields = ('institution_name', 'phone_masked', 'business_reg_no')
    list_filter = ('verified_at',)
    autocomplete_fields = ('institution',)
    readonly_fields = ('phone_hash', 'phone_masked')


@admin.register(Posting)
class PostingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'manager', 'work_date', 'status', 'pay_amount', 'headcount')
    search_fields = ('manager__institution_name', 'sport__name', 'address')
    list_filter = ('status', 'sport', 'pay_unit')
    date_hierarchy = 'work_date'
    autocomplete_fields = ('manager', 'sport')


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('posting', 'phone_masked', 'certification_verified', 'applied_at')
    search_fields = ('phone_masked', 'posting__manager__institution_name')
    list_filter = ('certification_verified', 'applied_at')
    readonly_fields = ('phone_identity', 'phone_masked', 'applied_at')


@admin.register(ReputationRecord)
class ReputationRecordAdmin(admin.ModelAdmin):
    list_display = (
        'phone_identity', 'posting', 'is_no_show', 'is_complaint', 'positive_tags',
        'occurred_at', 'is_hidden',
    )
    search_fields = ('phone_identity__phone_masked', 'comment')
    list_filter = ('is_no_show', 'is_complaint', 'is_hidden', 'occurred_at')
    readonly_fields = (
        'phone_identity', 'posting', 'is_no_show', 'is_complaint', 'positive_tags',
        'comment', 'occurred_at', 'created_by', 'hidden_at', 'hidden_by',
    )
    actions = ('hide_with_reason', 'unhide')

    @admin.action(description='선택한 기록을 사유와 함께 숨김 처리 (삭제 아님)')
    def hide_with_reason(self, request, queryset):
        if 'apply' in request.POST:
            form = HideReasonForm(request.POST)
            if form.is_valid():
                updated = queryset.update(
                    is_hidden=True, hidden_reason=form.cleaned_data['reason'],
                    hidden_at=timezone.now(), hidden_by=request.user,
                )
                self.message_user(request, f'{updated}건을 숨김 처리했습니다.', messages.SUCCESS)
                return None
        else:
            form = HideReasonForm()
        return render(request, 'substitutes/admin_hide_reason.html', {
            'records': queryset,
            'form': form,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
            'title': '평판 기록 숨김 처리',
        })

    @admin.action(description='선택한 기록의 숨김을 해제')
    def unhide(self, request, queryset):
        updated = queryset.update(is_hidden=False, hidden_reason='', hidden_at=None, hidden_by=None)
        self.message_user(request, f'{updated}건의 숨김을 해제했습니다.', messages.SUCCESS)
