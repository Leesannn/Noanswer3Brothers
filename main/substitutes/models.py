from django.conf import settings
from django.db import models
from django.utils import timezone

from analytics.models import CanonicalSport, Institution


POSITIVE_TAG_CHOICES = ['성실함', '시간엄수', '전문성', '친절함']


class PhoneIdentity(models.Model):
    """전화번호를 기준으로 신청 이력·평판을 누적하는 신원.

    원문 전화번호는 저장하지 않는다. 신청 처리 시점에만 원문을 잠깐 사용해
    해시·마스킹 값을 만들고 그 값만 영구 보관한다. 같은 번호로 다시 신청할
    때는 최초 등록 시 설정한 비밀번호로 본인 확인을 한다.
    """

    phone_hash = models.CharField(max_length=64, unique=True, editable=False)
    phone_masked = models.CharField(max_length=20)
    password_hash = models.CharField(max_length=128, editable=False, default='')
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '전화번호 신원'
        verbose_name_plural = '전화번호 신원'

    def __str__(self):
        return self.phone_masked


class CenterContact(models.Model):
    """단기 대타 공고를 등록할 수 있는 센터 담당자.

    휴대폰 번호로 담당자를 식별하고, 비밀번호로 본인 확인을 한다. 같은
    번호로 다시 공고를 등록하려면 최초 등록 시 설정한 비밀번호가 필요하다.
    """

    phone_hash = models.CharField(max_length=64, unique=True, editable=False)
    phone_masked = models.CharField(max_length=20)
    password_hash = models.CharField(max_length=128, editable=False, default='')
    institution = models.ForeignKey(
        Institution, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='substitute_contacts',
    )
    institution_name = models.CharField(max_length=200)
    business_reg_no = models.CharField(max_length=20, blank=True)
    verified_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = '센터 담당자'
        verbose_name_plural = '센터 담당자'

    def __str__(self):
        return f'{self.institution_name} ({self.phone_masked})'


class Posting(models.Model):
    class Status(models.TextChoices):
        RECRUITING = 'recruiting', '모집중'
        CLOSED = 'closed', '마감'
        COMPLETED = 'completed', '완료'

    class PayUnit(models.TextChoices):
        SESSION = 'session', '회당'
        HOUR = 'hour', '시간당'

    manager = models.ForeignKey(CenterContact, on_delete=models.PROTECT, related_name='postings')
    sport = models.ForeignKey(CanonicalSport, on_delete=models.PROTECT, related_name='substitute_postings')
    work_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    region = models.CharField(max_length=100, blank=True)
    normalized_region = models.CharField(max_length=100, blank=True, db_index=True)
    address = models.CharField(max_length=300)
    required_certifications = models.JSONField(default=list, blank=True)
    pay_amount = models.PositiveIntegerField()
    pay_unit = models.CharField(max_length=10, choices=PayUnit.choices, default=PayUnit.HOUR)
    headcount = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECRUITING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '대타 공고'
        verbose_name_plural = '대타 공고'

    def __str__(self):
        return f'{self.manager.institution_name} · {self.sport} 대타'


class Application(models.Model):
    posting = models.ForeignKey(Posting, on_delete=models.CASCADE, related_name='applications')
    phone_identity = models.ForeignKey(PhoneIdentity, on_delete=models.PROTECT, related_name='applications')
    phone_masked = models.CharField(max_length=20)
    certification_verified = models.BooleanField(default=False)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-applied_at']
        constraints = [
            models.UniqueConstraint(fields=['posting', 'phone_identity'], name='unique_posting_application'),
        ]
        verbose_name = '신청'
        verbose_name_plural = '신청'

    def __str__(self):
        return f'{self.posting} - {self.phone_masked}'


class ReputationRecord(models.Model):
    """센터가 대타 완료 후 남기는 평가 1건.

    운영 원칙상 삭제하지 않는다. 명백한 오류·허위 신고에 대해서만 어드민에서
    사유를 남기고 is_hidden 처리해 노출만 차단하며, 레코드 자체와 사유 이력은
    감사 추적을 위해 보존한다.
    """

    phone_identity = models.ForeignKey(PhoneIdentity, on_delete=models.CASCADE, related_name='reputation_records')
    posting = models.ForeignKey(
        Posting, on_delete=models.SET_NULL, null=True, blank=True, related_name='reputation_records',
    )
    is_no_show = models.BooleanField(default=False)
    is_complaint = models.BooleanField(default=False)
    positive_tags = models.JSONField(default=list, blank=True)
    comment = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        CenterContact, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    is_hidden = models.BooleanField(default=False, db_index=True)
    hidden_reason = models.TextField(blank=True)
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['phone_identity', 'occurred_at'], name='sub_reputation_phone_idx'),
        ]
        verbose_name = '평판 기록'
        verbose_name_plural = '평판 기록'

    def __str__(self):
        flags = []
        if self.is_no_show:
            flags.append('노쇼')
        if self.is_complaint:
            flags.append('컴플레인')
        if self.positive_tags:
            flags.append('긍정')
        return f'{self.phone_identity.phone_masked} - {", ".join(flags) or "기록"}'
