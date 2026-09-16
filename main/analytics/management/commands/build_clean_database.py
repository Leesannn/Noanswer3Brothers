from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.services.clean_database_builder import build_clean_database


class Command(BaseCommand):
    help = '자격증·프로그램 원본 CSV만 사용해 별도의 경량 SQLite DB를 새로 만듭니다.'

    def add_arguments(self, parser):
        parser.add_argument('qualification_csv')
        parser.add_argument('program_csv')
        parser.add_argument(
            '--output-dir',
            default='exports/rebuilt_202607',
            help='DB와 검토 CSV, 요약 보고서를 저장할 디렉터리',
        )
        parser.add_argument('--reference-date', help='운영 상태 기준일(YYYY-MM-DD)')
        parser.add_argument('--replace', action='store_true', help='기존 결과 DB가 있으면 교체')

    def handle(self, *args, **options):
        try:
            paths, _, _ = build_clean_database(
                options['qualification_csv'], options['program_csv'],
                Path(options['output_dir']),
                reference_date=options['reference_date'],
                replace=options['replace'],
                progress=self.stdout.write,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'완료: {paths.database}'))
