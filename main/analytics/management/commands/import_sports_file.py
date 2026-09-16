from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.models import UploadBatch
from analytics.services.importers import ImportValidationError, import_batch, preview


class Command(BaseCommand):
    help = '대용량 CSV/XLSX를 웹 업로드 복사 없이 검증하고 가져옵니다.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--type', choices=['auto', 'qualification', 'program', 'application'], default='auto')
        parser.add_argument('--sheet', default='')
        parser.add_argument('--allow-invalid', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['path']).resolve()
        if not path.is_file():
            raise CommandError(f'파일을 찾을 수 없습니다: {path}')
        batch = UploadBatch.objects.create(
            dataset_type=options['type'], original_filename=path.name, sheet_name=options['sheet'],
        )
        try:
            result = preview(path, options['sheet'], options['type'])
            batch.dataset_type = result['dataset_type']
            batch.encoding = result['encoding']
            batch.row_count = result['row_count']
            batch.columns = result['columns']
            batch.missing_counts = result['missing_counts']
            batch.preview_rows = result['preview_rows']
            batch.field_mapping = result['suggested_mapping']
            batch.save()
            import_batch(batch, result['suggested_mapping'], allow_invalid=options['allow_invalid'], source_path=path)
        except ImportValidationError as exc:
            batch.status = UploadBatch.Status.FAILED
            batch.failure_count = len(exc.errors)
            batch.errors = exc.errors[:10000]
            batch.save(update_fields=['status', 'failure_count', 'errors'])
            raise CommandError(str(exc)) from exc
        except (OSError, ValueError) as exc:
            batch.status = UploadBatch.Status.FAILED
            batch.errors = [{'row': '', 'message': str(exc)}]
            batch.save(update_fields=['status', 'errors'])
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'완료: {batch.success_count:,}행 처리, {batch.duplicate_count:,}행 중복 병합, {batch.failure_count:,}행 제외'
        ))
