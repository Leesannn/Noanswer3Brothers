from django.db import models


class UploadBatch(models.Model):
    class DatasetType(models.TextChoices):
        AUTO = 'auto', '자동 감지'
        QUALIFICATION = 'qualification', '지도자 자격 취득 현황'
        PROGRAM = 'program', '기관·운영 프로그램 현황'
        APPLICATION = 'application', '프로그램 신청 현황'

    class Status(models.TextChoices):
        PREVIEW = 'preview', '미리보기'
        VALIDATED = 'validated', '검증 완료'
        COMPLETED = 'completed', '저장 완료'
        FAILED = 'failed', '실패'

    dataset_type = models.CharField(max_length=20, choices=DatasetType.choices)
    original_filename = models.CharField(max_length=255)
    temporary_file = models.FileField(upload_to='uploads/%Y/%m/%d/', blank=True)
    sheet_name = models.CharField(max_length=200, blank=True)
    encoding = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREVIEW)
    row_count = models.PositiveBigIntegerField(default=0)
    success_count = models.PositiveBigIntegerField(default=0)
    failure_count = models.PositiveBigIntegerField(default=0)
    duplicate_count = models.PositiveBigIntegerField(default=0)
    columns = models.JSONField(default=list, blank=True)
    missing_counts = models.JSONField(default=dict, blank=True)
    preview_rows = models.JSONField(default=list, blank=True)
    field_mapping = models.JSONField(default=dict, blank=True)
    errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '업로드 이력'
        verbose_name_plural = '업로드 이력'

    def __str__(self):
        return f'{self.original_filename} ({self.get_status_display()})'


class Institution(models.Model):
    name = models.CharField(max_length=300)
    # (normalized_name, normalized_region) 고유 인덱스의 선두 열이므로 단일 인덱스는 중복이다.
    normalized_name = models.CharField(max_length=300)
    region = models.CharField(max_length=100, blank=True)
    normalized_region = models.CharField(max_length=100, blank=True, db_index=True)
    address = models.CharField(max_length=500, blank=True)
    normalized_address = models.CharField(max_length=500, blank=True)
    institution_type = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['normalized_name', 'normalized_region', 'normalized_address'],
                name='unique_institution_region_address',
            )
        ]
        verbose_name = '기관'
        verbose_name_plural = '기관'

    def __str__(self):
        return self.name


class CanonicalSport(models.Model):
    """자격 종목 데이터에서 만든 프로그램 매칭용 기준 종목."""

    name = models.CharField(max_length=150)
    normalized_name = models.CharField(max_length=150, unique=True)
    qualification_count = models.PositiveBigIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = '기준 종목'
        verbose_name_plural = '기준 종목'

    def __str__(self):
        return self.name


class DataSource(models.Model):
    """반복되는 원본 파일명을 프로그램마다 저장하지 않기 위한 출처 사전."""

    filename = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ['filename']
        verbose_name = '데이터 출처'
        verbose_name_plural = '데이터 출처'

    def __str__(self):
        return self.filename


class ProgramMatchPayload(models.Model):
    """수십만 프로그램에 반복되는 자동 매칭 규칙·후보 묶음."""

    payload_key = models.CharField(max_length=32, unique=True)
    rules = models.JSONField(default=list, blank=True)
    candidates = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = '프로그램 매칭 상세'
        verbose_name_plural = '프로그램 매칭 상세'

    def __str__(self):
        return self.payload_key


class Program(models.Model):
    class MatchGrade(models.TextChoices):
        EXACT = 'exact', '정확'
        SIMILAR = 'similar', '유사'
        REVIEW = 'review', '검토 필요'
        UNMATCHED = 'unmatched', '미매칭'

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name='programs')
    source_key = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=400)
    normalized_name = models.CharField(max_length=400, db_index=True)
    sport = models.CharField(max_length=150, blank=True)
    normalized_sport = models.CharField(max_length=150, blank=True, db_index=True)
    target = models.CharField(max_length=300, blank=True)
    weekdays = models.CharField(max_length=100, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=50, blank=True, default='운영')
    source = models.ForeignKey(
        DataSource, on_delete=models.PROTECT, null=True, blank=True,
        related_name='programs',
    )
    # 원본에 별도 컬럼이 있을 때 보존한다. 기존 데이터는 sport/institution_type을
    # 문맥 필드로 사용하므로 빈 값이어도 하위 호환된다.
    program_type = models.CharField(max_length=200, blank=True)
    facility_industry = models.CharField(max_length=200, blank=True)
    matched_sport = models.ForeignKey(
        CanonicalSport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='matched_programs',
    )
    match_grade = models.CharField(
        max_length=20, choices=MatchGrade.choices,
        default=MatchGrade.UNMATCHED, db_index=True,
    )
    match_confidence = models.PositiveSmallIntegerField(default=0)
    match_reason = models.TextField(blank=True)
    match_payload = models.ForeignKey(
        ProgramMatchPayload, on_delete=models.PROTECT, null=True, blank=True,
        related_name='programs',
    )
    # 대부분 False인 불리언 단일 인덱스는 선택도가 낮아 공간만 크게 사용한다.
    match_is_manual = models.BooleanField(default=False)

    class Meta:
        ordering = ['institution__name', 'name']
        verbose_name = '운영 프로그램'
        verbose_name_plural = '운영 프로그램'

    def __str__(self):
        return f'{self.institution.name} - {self.name}'

    @property
    def source_filename(self):
        return self.source.filename if self.source_id else ''

    @property
    def match_rules(self):
        return self.match_payload.rules if self.match_payload_id else []

    @property
    def match_candidates(self):
        return self.match_payload.candidates if self.match_payload_id else []


class ProgramCleanupDetail(models.Model):
    """반복되는 프로그램 정리 근거 문장·규칙 묶음."""

    detail_key = models.CharField(max_length=32, unique=True)
    evidence = models.TextField(blank=True)
    rules = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = '프로그램 정리 상세'
        verbose_name_plural = '프로그램 정리 상세'

    def __str__(self):
        return self.detail_key


class ProgramCleanup(models.Model):
    """원본 Program을 변경하지 않고 보관하는 분석용 1:1 정리 결과."""

    class OperatingStatus(models.TextChoices):
        ACTIVE = 'active', '운영 중'
        ENDED = 'ended', '운영 종료'
        UPCOMING = 'upcoming', '운영 예정'
        UNKNOWN = 'unknown', '미확인'

    class ExclusionReason(models.TextChoices):
        NONE = '', '사용'
        ENDED = 'ended', '운영 종료'
        UPCOMING = 'upcoming', '운영 예정'
        UNKNOWN = 'unknown', '운영 여부 미확인'
        MULTI_SPORT = 'multi_sport', '복수 종목'
        UNMATCHED = 'unmatched', '자격 종목 미매칭'
        OTHER = 'other', '기타 제외'

    program = models.OneToOneField(
        Program, on_delete=models.CASCADE, related_name='cleanup',
    )
    cleaned_name = models.CharField(max_length=400, blank=True)
    matched_sport = models.ForeignKey(
        CanonicalSport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cleaned_programs', db_index=False,
    )
    operating_status = models.CharField(
        max_length=20, choices=OperatingStatus.choices, db_index=True,
    )
    is_usable = models.BooleanField(default=False, db_index=True)
    exclusion_reason = models.CharField(
        max_length=30, choices=ExclusionReason.choices, blank=True, db_index=True,
    )
    detail = models.ForeignKey(
        ProgramCleanupDetail, on_delete=models.PROTECT, null=True, blank=True,
        related_name='cleanups',
    )
    reference_date = models.DateField()

    class Meta:
        ordering = ['program__institution__name', 'cleaned_name']
        indexes = [
            models.Index(
                fields=['matched_sport', 'is_usable'],
                name='app_cleanup_sport_idx',
            ),
        ]
        verbose_name = '프로그램 정리 결과'
        verbose_name_plural = '프로그램 정리 결과'

    def __str__(self):
        return f'{self.program.name} → {self.cleaned_name or "제외"}'

    @property
    def evidence(self):
        return self.detail.evidence if self.detail_id else ''

    @property
    def rules(self):
        return self.detail.rules if self.detail_id else []


class QualificationAggregate(models.Model):
    # 아래 고유 제약의 선두 열이므로 별도 단일 인덱스가 필요 없다.
    acquisition_year = models.PositiveSmallIntegerField(null=True, blank=True)
    region = models.CharField(max_length=100, blank=True)
    normalized_region = models.CharField(max_length=100, blank=True, db_index=True)
    sport = models.CharField(max_length=150, blank=True)
    normalized_sport = models.CharField(max_length=150, blank=True, db_index=True)
    qualification_type = models.CharField(max_length=200, blank=True)
    grade = models.CharField(max_length=100, blank=True)
    acquisition_count = models.PositiveIntegerField(default=0)
    source_filename = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-acquisition_year', 'normalized_sport']
        constraints = [models.UniqueConstraint(
            fields=['acquisition_year', 'normalized_region', 'normalized_sport', 'qualification_type', 'grade', 'source_filename'],
            name='unique_qualification_aggregate',
        )]
        verbose_name = '지도자 자격 취득 현황'
        verbose_name_plural = '지도자 자격 취득 현황'

    def __str__(self):
        return f'{self.acquisition_year or "연도 미상"} {self.sport} {self.acquisition_count:,}건'


class ApplicationStatus(models.Model):
    # (program, reference_date) 고유 인덱스가 program 조회도 처리한다.
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name='applications', db_index=False,
    )
    source_key = models.CharField(max_length=32, unique=True)
    reference_date = models.DateField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    applicants = models.PositiveIntegerField(null=True, blank=True)
    waitlist = models.PositiveIntegerField(null=True, blank=True)
    is_synthetic = models.BooleanField(default=False)

    class Meta:
        ordering = ['-reference_date', 'program__name']
        constraints = [
            models.UniqueConstraint(
                fields=['program', 'reference_date'],
                name='unique_program_application_period',
            ),
        ]
        indexes = [
            models.Index(
                fields=['is_synthetic', 'reference_date'],
                name='app_demo_period_idx',
            ),
        ]
        verbose_name = '프로그램 신청 현황'
        verbose_name_plural = '프로그램 신청 현황'

    @property
    def application_rate(self):
        if not self.capacity or self.applicants is None:
            return None
        return self.applicants / self.capacity * 100

    @property
    def demand_status(self):
        rate = self.application_rate
        if rate is None:
            return '데이터 부족'
        if rate >= 100:
            return '마감·대기'
        if rate >= 90:
            return '수요 높음'
        if rate >= 50:
            return '보통'
        return '개선 검토'

    def __str__(self):
        return f'{self.program} ({self.demand_status})'


class ExamSchedule(models.Model):
    """sqms.kspo.or.kr 연간일정계획 캐시. refresh_exam_schedule 커맨드가 갱신한다."""

    grade_code = models.CharField(max_length=10, db_index=True)
    grade_name = models.CharField(max_length=100)
    phase = models.CharField(max_length=30)
    season = models.CharField(max_length=30, blank=True)
    course_type = models.CharField(max_length=30, blank=True)
    milestone = models.CharField(max_length=50)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    raw_text = models.CharField(max_length=200, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['grade_code', 'phase', 'season', 'course_type']
        verbose_name = '연간일정계획 캐시'
        verbose_name_plural = '연간일정계획 캐시'

    def __str__(self):
        return f'{self.grade_code} {self.phase} {self.course_type} {self.milestone}'


class ExamScheduleFetchStatus(models.Model):
    """등급별 연간일정계획 갱신 성공/실패 이력. 화면의 안내 배너에 사용한다."""

    grade_code = models.CharField(max_length=10, unique=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        verbose_name = '연간일정계획 갱신 상태'
        verbose_name_plural = '연간일정계획 갱신 상태'

    def __str__(self):
        return self.grade_code
