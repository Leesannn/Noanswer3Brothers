import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from app.models import ProgramCleanup


class Command(BaseCommand):
    help = '원본 프로그램과 정리 결과를 하나의 UTF-8 BOM CSV로 내보냅니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default='exports/cleaned_programs_202607.csv',
            help='프로젝트 루트 기준 또는 절대 출력 경로',
        )

    def handle(self, *args, **options):
        output = Path(options['output'])
        if not output.is_absolute():
            output = Path.cwd() / output
        output.parent.mkdir(parents=True, exist_ok=True)

        rows = ProgramCleanup.objects.select_related(
            'program__institution', 'matched_sport',
        ).order_by('program_id')

        headers = [
            'program_id', 'source_key', 'source_filename',
            'institution_id', 'institution_name', 'region', 'normalized_region',
            'address', 'institution_type', 'original_program_name',
            'original_sport', 'program_type', 'facility_industry', 'target',
            'weekdays', 'start_time', 'end_time', 'start_date', 'end_date',
            'original_status', 'cleaned_name', 'canonical_sport_id',
            'canonical_sport_name', 'operating_status', 'is_usable',
            'exclusion_reason', 'evidence', 'applied_rules', 'reference_date',
        ]

        count = 0
        with output.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            for cleanup in rows.iterator(chunk_size=2000):
                program = cleanup.program
                institution = program.institution
                writer.writerow([
                    program.pk,
                    program.source_key,
                    program.source_filename,
                    institution.pk,
                    institution.name,
                    institution.region,
                    institution.normalized_region,
                    institution.address,
                    institution.institution_type,
                    program.name,
                    program.sport,
                    program.program_type,
                    program.facility_industry,
                    program.target,
                    program.weekdays,
                    program.start_time,
                    program.end_time,
                    program.start_date,
                    program.end_date,
                    program.status,
                    cleanup.cleaned_name,
                    cleanup.matched_sport_id or '',
                    cleanup.matched_sport.name if cleanup.matched_sport else '',
                    cleanup.operating_status,
                    cleanup.is_usable,
                    cleanup.exclusion_reason,
                    cleanup.evidence,
                    json.dumps(cleanup.rules, ensure_ascii=False),
                    cleanup.reference_date,
                ])
                count += 1

        self.stdout.write(self.style.SUCCESS(
            f'{count:,}건을 내보냈습니다: {output}',
        ))
