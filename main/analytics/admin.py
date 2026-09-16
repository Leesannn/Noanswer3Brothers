from django.contrib import admin

from .models import (
    ApplicationStatus, CanonicalSport, ExamSchedule, ExamScheduleFetchStatus, Institution,
    Program, ProgramCleanup, QualificationAggregate, UploadBatch,
)


@admin.register(CanonicalSport)
class CanonicalSportAdmin(admin.ModelAdmin):
    list_display = ('name', 'normalized_name', 'qualification_count', 'is_active')
    search_fields = ('name', 'normalized_name')
    list_filter = ('is_active',)
    readonly_fields = ('normalized_name', 'qualification_count')


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'region', 'institution_type')
    search_fields = ('name', 'region', 'address')
    list_filter = ('region', 'institution_type')


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'sport', 'matched_sport', 'match_grade', 'match_confidence', 'match_is_manual', 'status')
    search_fields = ('name', 'institution__name', 'sport', 'matched_sport__name', 'target')
    list_filter = ('match_grade', 'match_is_manual', 'status', 'institution__region')
    date_hierarchy = 'start_date'
    autocomplete_fields = ('matched_sport',)
    readonly_fields = ('match_rules', 'match_candidates')
    actions = ('confirm_matches',)

    @admin.action(description='선택한 매칭을 수동 확정')
    def confirm_matches(self, request, queryset):
        updated = queryset.exclude(matched_sport=None).update(match_is_manual=True)
        self.message_user(request, f'{updated:,}개 매칭을 수동 확정했습니다.')

    def save_model(self, request, obj, form, change):
        match_fields = {'matched_sport', 'match_grade', 'match_confidence', 'match_reason'}
        if change and match_fields.intersection(form.changed_data):
            obj.match_is_manual = True
        super().save_model(request, obj, form, change)


@admin.register(ProgramCleanup)
class ProgramCleanupAdmin(admin.ModelAdmin):
    list_display = (
        'program', 'cleaned_name', 'matched_sport', 'operating_status',
        'is_usable', 'exclusion_reason', 'reference_date',
    )
    search_fields = ('program__name', 'cleaned_name', 'program__institution__name')
    list_filter = (
        'reference_date', 'operating_status', 'is_usable',
        'exclusion_reason', 'matched_sport',
    )
    autocomplete_fields = ('program', 'matched_sport')
    readonly_fields = ('program', 'evidence', 'rules', 'reference_date')


@admin.register(QualificationAggregate)
class QualificationAggregateAdmin(admin.ModelAdmin):
    list_display = ('acquisition_year', 'sport', 'qualification_type', 'grade', 'region', 'acquisition_count')
    search_fields = ('sport', 'qualification_type', 'region')
    list_filter = ('acquisition_year', 'region', 'qualification_type', 'grade')


@admin.register(ApplicationStatus)
class ApplicationStatusAdmin(admin.ModelAdmin):
    list_display = ('program', 'reference_date', 'capacity', 'applicants', 'waitlist', 'demand_status', 'is_synthetic')
    search_fields = ('program__name', 'program__institution__name')
    list_filter = ('is_synthetic', 'reference_date', 'program__sport', 'program__institution__region')
    date_hierarchy = 'reference_date'


@admin.register(ExamSchedule)
class ExamScheduleAdmin(admin.ModelAdmin):
    list_display = ('grade_code', 'phase', 'season', 'course_type', 'milestone', 'end_at', 'fetched_at')
    search_fields = ('grade_code', 'grade_name', 'milestone')
    list_filter = ('grade_code', 'phase')
    readonly_fields = ('fetched_at',)


@admin.register(ExamScheduleFetchStatus)
class ExamScheduleFetchStatusAdmin(admin.ModelAdmin):
    list_display = ('grade_code', 'last_success_at', 'last_checked_at', 'last_error')
    readonly_fields = ('grade_code', 'last_success_at', 'last_checked_at', 'last_error')


@admin.register(UploadBatch)
class UploadBatchAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'dataset_type', 'status', 'row_count', 'success_count', 'failure_count', 'created_at')
    search_fields = ('original_filename',)
    list_filter = ('dataset_type', 'status', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'completed_at')
