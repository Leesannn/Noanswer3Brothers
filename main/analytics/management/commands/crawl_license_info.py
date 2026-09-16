import csv

from django.conf import settings
from django.core.management.base import BaseCommand

from analytics.services.kspo_client import KspoFetchError
from analytics.services.kspo_grades import GRADE_CODES
from analytics.services.kspo_license import fetch_license_info


GRADE_FIELDS = [
    'grade_code', 'grade_name', 'definition', 'legal_basis', 'written_subjects',
    'sport_events_summary', 'exam_agency', 'training_agency', 'pass_criteria',
]
ELIGIBILITY_FIELDS = [
    'grade_code', 'course_type', 'eligibility', 'acquisition_process', 'submitted_documents',
]


class Command(BaseCommand):
    help = (
        '체육지도자 자격검정 사이트(sqms.kspo.or.kr)의 자격제도안내를 크롤링해 '
        'data/kspo_license_grades.csv, data/kspo_license_eligibility_paths.csv, '
        'data/kspo_disqualification.txt로 저장합니다. 자주 바뀌지 않는 정보이므로 '
        '평소에는 수동으로 1회성 실행하면 됩니다.'
    )

    def handle(self, *args, **options):
        data_dir = settings.BASE_DIR / 'data'
        data_dir.mkdir(exist_ok=True)

        grade_rows = []
        eligibility_rows = []
        disqualification_text = ''
        failures = []

        for code in GRADE_CODES:
            try:
                summary, paths, disqual = fetch_license_info(code)
            except KspoFetchError as exc:
                failures.append(code)
                self.stderr.write(self.style.WARNING(f'{code} 크롤링 실패: {exc}'))
                continue

            grade_rows.append(summary)
            eligibility_rows.extend(paths)
            if disqual and not disqualification_text:
                disqualification_text = disqual
            self.stdout.write(self.style.SUCCESS(f'{code} 완료 (응시자격 경로 {len(paths)}개)'))

        if not grade_rows:
            self.stderr.write(self.style.ERROR('모든 등급 크롤링에 실패해 CSV를 생성하지 않았습니다.'))
            return

        with open(data_dir / 'kspo_license_grades.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=GRADE_FIELDS)
            writer.writeheader()
            writer.writerows(grade_rows)

        with open(data_dir / 'kspo_license_eligibility_paths.csv', 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=ELIGIBILITY_FIELDS)
            writer.writeheader()
            writer.writerows(eligibility_rows)

        if disqualification_text:
            with open(data_dir / 'kspo_disqualification.txt', 'w', encoding='utf-8') as f:
                f.write(disqualification_text)

        self.stdout.write(self.style.SUCCESS(
            f'등급 {len(grade_rows)}개, 응시자격 경로 {len(eligibility_rows)}행을 CSV로 저장했습니다.'
        ))
        if failures:
            self.stdout.write(self.style.WARNING(f'실패한 등급: {", ".join(failures)}'))
