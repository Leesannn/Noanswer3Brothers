from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from analytics.models import CanonicalSport, Program, ProgramCleanup, ProgramCleanupDetail
from analytics.services.program_cleanup import (
    ProgramCleaner, cleanup_detail_key, cleanup_reference_date,
)
from analytics.services.sport_matching import matching_key


class Command(BaseCommand):
    help = '원본 Program을 변경하지 않고 1:1 분석용 정리 결과를 생성하거나 갱신합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--reference-date', help='판정 기준일(YYYY-MM-DD)')
        parser.add_argument('--batch-size', type=int, default=5000)
        parser.add_argument('--limit', type=int)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            reference_date = cleanup_reference_date(options['reference_date'])
        except ValueError as exc:
            raise CommandError('기준일은 YYYY-MM-DD 형식이어야 합니다.') from exc
        taxonomy = list(CanonicalSport.objects.filter(is_active=True))
        if not taxonomy:
            raise CommandError('기존 자격 종목 taxonomy가 없습니다.')
        cleaner = ProgramCleaner(taxonomy)
        sports_by_key = {matching_key(item.normalized_name): item.pk for item in taxonomy}
        queryset = Program.objects.select_related('institution', 'matched_sport').order_by('pk')
        if options['limit']:
            queryset = queryset[:options['limit']]

        table = connection.ops.quote_name(ProgramCleanup._meta.db_table)
        sql = f'''
            INSERT INTO {table}
                (program_id, cleaned_name, matched_sport_id, operating_status,
                 is_usable, exclusion_reason, detail_id, reference_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(program_id) DO UPDATE SET
                cleaned_name=excluded.cleaned_name,
                matched_sport_id=excluded.matched_sport_id,
                operating_status=excluded.operating_status,
                is_usable=excluded.is_usable,
                exclusion_reason=excluded.exclusion_reason,
                detail_id=excluded.detail_id,
                reference_date=excluded.reference_date
        '''
        pending = []
        statuses = Counter()
        exclusions = Counter()
        cache = {}
        details = {}

        def flush(rows):
            if options['dry_run'] or not rows:
                return
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.executemany(sql, rows)

        for program in queryset.iterator(chunk_size=options['batch_size']):
            signature = (
                program.name, program.sport, program.program_type,
                program.start_date, program.end_date, program.status,
                program.matched_sport_id, program.match_grade,
                program.institution.institution_type,
            )
            decision = cache.get(signature)
            if decision is None:
                decision = cleaner.clean(program, reference_date)
                cache[signature] = decision
            statuses[decision.operating_status] += 1
            exclusions[decision.exclusion_reason or 'usable'] += 1
            detail_key = cleanup_detail_key(decision.evidence, decision.rules)
            if detail_key not in details and not options['dry_run']:
                details[detail_key], _ = ProgramCleanupDetail.objects.get_or_create(
                    detail_key=detail_key,
                    defaults={'evidence': decision.evidence, 'rules': decision.rules},
                )
            pending.append((
                program.pk, decision.cleaned_name,
                sports_by_key.get(decision.canonical_key), decision.operating_status,
                decision.is_usable, decision.exclusion_reason,
                details[detail_key].pk if detail_key in details else None,
                reference_date,
            ))
            if len(pending) >= options['batch_size']:
                flush(pending)
                pending.clear()
                processed = sum(statuses.values())
                if processed % 50000 < options['batch_size']:
                    self.stdout.write(f'처리 중: {processed:,}건')
        flush(pending)

        total = sum(statuses.values())
        self.stdout.write(f'기준일: {reference_date}')
        for key in ('active', 'ended', 'unknown'):
            self.stdout.write(f'{key}: {statuses[key]:,}')
        for key in ('usable', 'multi_sport', 'unmatched', 'ended', 'unknown'):
            self.stdout.write(f'{key}: {exclusions[key]:,}')
        self.stdout.write(self.style.SUCCESS(f'정리 결과 {total:,}건을 처리했습니다.'))
