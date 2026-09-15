import hashlib
import random
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from app.models import ApplicationStatus, Program


SEED = 2026
CAPACITIES = (15, 20, 25, 30, 40)
BATCH_SIZE = 2000


def recent_months(today=None):
    current = (today or timezone.localdate()).replace(day=1)
    months = []
    for offset in range(5, -1, -1):
        month_index = current.year * 12 + current.month - 1 - offset
        months.append(date(month_index // 12, month_index % 12 + 1, 1))
    return months


class Command(BaseCommand):
    help = '기존 프로그램별 최근 6개월의 시연용 합성 신청 현황을 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh', action='store_true',
            help='기존 합성 데이터만 삭제하고 고정 시드로 다시 생성합니다.',
        )

    def handle(self, *args, **options):
        if ApplicationStatus.objects.filter(is_synthetic=True).exists():
            if not options['refresh']:
                self.stdout.write('합성 데이터가 이미 존재합니다.')
                return
            deleted, _ = ApplicationStatus.objects.filter(is_synthetic=True).delete()
            self.stdout.write(f'기존 합성 데이터 {deleted:,}건을 삭제했습니다.')

        rng = random.Random(SEED)
        periods = recent_months()
        pending = []

        with transaction.atomic():
            for index, program_id in enumerate(
                Program.objects.order_by('pk').values_list('pk', flat=True).iterator(chunk_size=BATCH_SIZE)
            ):
                capacity = rng.choice(CAPACITIES)
                group = index % 4
                if group == 0:  # 약 25%: 인기
                    low, high = 90, 120
                elif group == 1:  # 약 25%: 개선 필요
                    low, high = 30, 59
                else:  # 약 50%: 보통
                    low, high = 60, 89
                baseline = rng.uniform(low + 3, high - 3)

                for period in periods:
                    target_rate = min(high, max(low, baseline + rng.uniform(-5, 5)))
                    applicants = max(0, round(capacity * target_rate / 100))
                    if applicants > capacity:
                        waitlist = applicants - capacity
                    elif rng.random() < 0.08:
                        waitlist = rng.randint(1, 2)
                    else:
                        waitlist = 0
                    source_key = hashlib.sha256(
                        f'demo:{program_id}:{period.isoformat()}'.encode('utf-8')
                    ).hexdigest()
                    pending.append(ApplicationStatus(
                        program_id=program_id,
                        source_key=source_key,
                        reference_date=period,
                        recruitment_year=period.year,
                        capacity=capacity,
                        applicants=applicants,
                        waitlist=waitlist,
                        is_synthetic=True,
                        source_filename='generated_demo_data',
                    ))
                if len(pending) >= BATCH_SIZE:
                    ApplicationStatus.objects.bulk_create(
                        pending, batch_size=BATCH_SIZE, ignore_conflicts=True,
                    )
                    pending.clear()

            if pending:
                ApplicationStatus.objects.bulk_create(
                    pending, batch_size=BATCH_SIZE, ignore_conflicts=True,
                )

        created = ApplicationStatus.objects.filter(is_synthetic=True).count()
        self.stdout.write(self.style.SUCCESS(f'합성 신청 현황 {created:,}건을 생성했습니다.'))
