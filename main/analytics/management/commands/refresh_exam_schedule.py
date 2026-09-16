from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from analytics.models import ExamSchedule, ExamScheduleFetchStatus
from analytics.services.kspo_client import KspoFetchError
from analytics.services.kspo_grades import GRADE_CODES
from analytics.services.kspo_schedule import fetch_schedule


class Command(BaseCommand):
    help = (
        '체육지도자 자격검정 사이트(sqms.kspo.or.kr)의 연간일정계획을 갱신해 캐시(DB)에 '
        '저장합니다. 일정 주기(예: 1시간)로 실행하도록 스케줄러(cron/작업 스케줄러)에 등록하세요.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--grade', help='특정 등급 코드만 갱신 (예: LSC2). 생략하면 9개 등급 전체.')

    def handle(self, *args, **options):
        codes = [options['grade'].upper()] if options.get('grade') else GRADE_CODES
        success_count = 0

        for code in codes:
            status, _ = ExamScheduleFetchStatus.objects.get_or_create(grade_code=code)
            status.last_checked_at = timezone.now()

            try:
                rows = fetch_schedule(code)
            except KspoFetchError as exc:
                status.last_error = str(exc)
                status.save(update_fields=['last_checked_at', 'last_error'])
                self.stderr.write(self.style.WARNING(
                    f'{code} 갱신 실패 — 기존 캐시를 유지합니다: {exc}',
                ))
                continue

            if not rows:
                status.last_error = '파싱 결과가 비어 있습니다 (사이트 구조 변경 가능성)'
                status.save(update_fields=['last_checked_at', 'last_error'])
                self.stderr.write(self.style.WARNING(f'{code} 갱신 실패 — {status.last_error}'))
                continue

            with transaction.atomic():
                ExamSchedule.objects.filter(grade_code=code).delete()
                ExamSchedule.objects.bulk_create(ExamSchedule(**row) for row in rows)

            status.last_error = ''
            status.last_success_at = timezone.now()
            status.save(update_fields=['last_checked_at', 'last_error', 'last_success_at'])
            success_count += 1
            self.stdout.write(self.style.SUCCESS(f'{code} 갱신 완료 ({len(rows)}건)'))

        self.stdout.write(f'{success_count}/{len(codes)}개 등급 갱신 성공')
