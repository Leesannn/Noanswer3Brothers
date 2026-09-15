import json
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from app.models import CanonicalSport, Program, QualificationAggregate
from app.services.sport_matching import SportMatcher, matching_key, sync_taxonomy


class Command(BaseCommand):
    help = '자격 종목 taxonomy와 관리형 규칙으로 프로그램 종목을 결정론적으로 매칭합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=2000)
        parser.add_argument('--limit', type=int)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        taxonomy_keys = set(QualificationAggregate.objects.exclude(normalized_sport='').values_list('normalized_sport', flat=True))
        total = Program.objects.count()
        baseline = Program.objects.filter(normalized_sport__in=taxonomy_keys).count()
        taxonomy = list(sync_taxonomy()) if not options['dry_run'] else list(CanonicalSport.objects.filter(is_active=True))
        if not taxonomy:
            self.stderr.write(self.style.ERROR('자격 종목 taxonomy가 없습니다. 자격 데이터를 먼저 가져오세요.'))
            return
        matcher = SportMatcher(taxonomy)
        sports_by_key = {matching_key(item.normalized_name): item for item in taxonomy}
        queryset = Program.objects.select_related('institution').filter(match_is_manual=False).order_by('pk')
        if options['limit']:
            queryset = queryset[:options['limit']]
        pending = []
        counts = Counter()
        cache = {}
        now = timezone.now()
        update_sql = '''
            UPDATE app_program
               SET matched_sport_id = %s,
                   match_grade = %s,
                   match_confidence = %s,
                   match_reason = %s,
                   match_rules = %s,
                   match_candidates = %s,
                   match_updated_at = %s
             WHERE id = %s AND match_is_manual = 0
        '''

        def flush(rows):
            if options['dry_run'] or not rows:
                return
            # SQLite에서 bulk_update의 거대한 CASE 문보다 결정론적인 executemany가
            # 대용량 단순 갱신에 훨씬 효율적이다. WHERE가 수동 확정을 이중 보호한다.
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.executemany(update_sql, rows)

        for program in queryset.iterator(chunk_size=options['batch_size']):
            signature = (program.name, program.sport, program.program_type, program.facility_industry, program.institution.institution_type)
            result = cache.get(signature)
            if result is None:
                result = matcher.match(
                    name=program.name, sport=program.sport, program_type=program.program_type,
                    facility_industry=program.facility_industry,
                    institution_type=program.institution.institution_type,
                )
                cache[signature] = result
            counts[result.grade] += 1
            matched = sports_by_key.get(result.canonical_key)
            pending.append((
                matched.pk if matched else None, result.grade, result.confidence,
                result.reason, json.dumps(result.rules, ensure_ascii=False),
                json.dumps(result.candidates, ensure_ascii=False), now, program.pk,
            ))
            if len(pending) >= options['batch_size']:
                flush(pending)
                pending.clear()
                processed_so_far = sum(counts.values())
                if processed_so_far % 50000 < options['batch_size']:
                    self.stdout.write(f'처리 중: {processed_so_far:,}건')
        flush(pending)

        processed = sum(counts.values())
        matched = counts['exact'] + counts['similar']
        self.stdout.write(f'기존 문자열 일치: {baseline:,}/{total:,} ({baseline / total * 100 if total else 0:.2f}%)')
        for grade in ('exact', 'similar', 'review', 'unmatched'):
            self.stdout.write(f'{grade}: {counts[grade]:,} ({counts[grade] / processed * 100 if processed else 0:.2f}%)')
        self.stdout.write(self.style.SUCCESS(f'자동 확정 매칭: {matched:,}/{processed:,} ({matched / processed * 100 if processed else 0:.2f}%)'))
