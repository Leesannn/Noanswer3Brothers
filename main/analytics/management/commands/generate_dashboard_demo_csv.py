import csv
import random
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count

from analytics.models import ProgramCleanup, QualificationAggregate

SEED = 2026
BATCH_SIZE = 2000
CAPACITY_CHOICES = (10, 12, 15, 18, 20, 25, 30, 35, 40)
LEVELS = (
    '초급반', '중급반', '고급반', '입문반', '주말반', '저녁반', '새벽반',
    '오전반', '오후반', '동호인반', '교실', '클래스', '기초반', '심화반',
)
AUDIENCE_PREFIXES = ('성인', '어린이', '청소년', '유아', '시니어', '여성', '')


class Command(BaseCommand):
    help = (
        '대시보드 시연용 신청 현황 CSV(data/dashboard_demo_applications.csv)를 재생성합니다. '
        '대시보드의 "프로그램 수" 지표와 같은 기준(ProgramCleanup의 운영 중·사용 가능 프로그램)으로 '
        '기관·종목 조합과 개수를 뽑기 때문에, 특정 조합으로 검색했을 때 나오는 신청 현황 행 수가 '
        '해당 조합의 실제 프로그램 수와 1:1로 맞아떨어진다.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=SEED)

    def handle(self, *args, **options):
        rng = random.Random(options['seed'])

        # 대시보드 "프로그램 수" 지표(analytics.views.dashboard)와 동일하게
        # ProgramCleanup의 운영 중(active)·사용 가능(is_usable) 행만 기준으로 삼는다.
        pairs = list(
            ProgramCleanup.objects.filter(
                operating_status='active', is_usable=True, matched_sport__isnull=False,
            ).values(
                'program__institution_id', 'program__institution__name',
                'program__institution__region', 'matched_sport__name',
            ).annotate(program_count=Count('id'))
        )
        if not pairs:
            self.stderr.write('사용 가능한 ProgramCleanup 데이터가 없어 CSV를 생성할 수 없습니다.')
            return
        years = sorted(set(
            QualificationAggregate.objects.exclude(acquisition_year=None).values_list('acquisition_year', flat=True)
        ))
        if not years:
            years = [date.today().year]

        path = settings.BASE_DIR / 'data' / 'dashboard_demo_applications.csv'
        path.parent.mkdir(parents=True, exist_ok=True)

        def make_row(institution_name, region, sport, year):
            capacity = rng.choice(CAPACITY_CHOICES)
            rate = rng.uniform(20, 115)
            applicants = max(0, round(capacity * rate / 100))
            if applicants > capacity:
                waitlist = applicants - capacity
            elif rng.random() < 0.08:
                waitlist = rng.randint(1, 3)
            else:
                waitlist = 0
            reference_date = date(year, rng.randint(1, 12), 1)
            name_parts = [part for part in (rng.choice(AUDIENCE_PREFIXES), sport, rng.choice(LEVELS)) if part]
            program_name = ' '.join(name_parts)
            return [
                institution_name, region, program_name, sport,
                capacity, applicants, waitlist, reference_date.isoformat(),
            ]

        written = 0
        year_cursor = 0

        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'institution_name', 'region', 'program_name', 'sport',
                'capacity', 'applicants', 'waitlist', 'reference_date',
            ])

            batch = []
            for pair in pairs:
                # 기관·종목 조합마다 정확히 실제 프로그램 수(program_count)만큼만 행을 만든다.
                # (검색 결과의 "프로그램 수"와 "신청 현황 행 수"가 항상 일치하도록)
                for _ in range(pair['program_count']):
                    year = years[year_cursor % len(years)]
                    year_cursor += 1
                    batch.append(make_row(
                        pair['program__institution__name'],
                        pair['program__institution__region'],
                        pair['matched_sport__name'],
                        year,
                    ))
                    written += 1
                if len(batch) >= BATCH_SIZE:
                    writer.writerows(batch)
                    f.flush()
                    batch.clear()
            if batch:
                writer.writerows(batch)
                f.flush()

        size_mb = path.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f'{path} 에 {written:,}행, {size_mb:.1f}MB 규모로 생성했습니다 '
            f'(실제 기관·종목 조합 {len(pairs):,}개, 연도 {len(years)}개 모두 최소 1회 포함).'
        ))
