import sqlite3
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from analytics.models import (
    CanonicalSport, DataSource, Institution, Program, ProgramCleanup,
    QualificationAggregate,
)


class Command(BaseCommand):
    help = '정제 전용 SQLite DB를 현재 Django DB 구조로 적재합니다.'

    def add_arguments(self, parser):
        parser.add_argument('clean_database')
        parser.add_argument('--batch-size', type=int, default=5000)
        parser.add_argument('--reference-date', default='2026-07-31')

    def handle(self, *args, **options):
        source_path = Path(options['clean_database']).resolve()
        if not source_path.is_file():
            raise CommandError(f'정제 DB를 찾을 수 없습니다: {source_path}')
        try:
            reference_date = date.fromisoformat(options['reference_date'])
        except ValueError as exc:
            raise CommandError('기준일은 YYYY-MM-DD 형식이어야 합니다.') from exc
        if any(model.objects.exists() for model in (
            Program, Institution, CanonicalSport, QualificationAggregate,
        )):
            raise CommandError('대상 DB에 스포츠 데이터가 이미 있습니다. 빈 신규 DB에서 실행하세요.')

        source = sqlite3.connect(source_path)
        source.row_factory = sqlite3.Row
        try:
            self._load(source, reference_date, options['batch_size'])
            self._validate(source)
        finally:
            source.close()
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA optimize')
        self.stdout.write(self.style.SUCCESS('정제 데이터를 Django 서비스 DB에 연결했습니다.'))

    @transaction.atomic
    def _load(self, source, reference_date, batch_size):
        qualification_filename = 'KS_PTDRCTOR_PSEXAM_INFO_202607.csv'
        program_filename = 'KS_PUBLIC_ALSFC_PROGRM_INFO_202607.csv'
        data_source = DataSource.objects.create(filename=program_filename)

        qualification_totals = dict(source.execute(
            'SELECT sport_id, SUM(acquisition_count) FROM qualification_aggregate GROUP BY sport_id'
        ))
        sports = [
            CanonicalSport(
                id=row['id'], name=row['name'], normalized_name=row['normalized_name'],
                qualification_count=qualification_totals.get(row['id'], 0), is_active=True,
            )
            for row in source.execute('SELECT id, name, normalized_name FROM canonical_sport')
        ]
        CanonicalSport.objects.bulk_create(sports, batch_size=batch_size)
        self.stdout.write(f'자격 종목 {len(sports):,}개 적재')

        qualifications = [
            QualificationAggregate(
                acquisition_year=row['acquisition_year'], region=row['region'],
                normalized_region=row['normalized_region'], sport=row['sport_name'],
                normalized_sport=row['sport_key'],
                qualification_type=row['qualification_type'], grade=row['grade'],
                acquisition_count=row['acquisition_count'],
                source_filename=qualification_filename,
            )
            for row in source.execute(
                '''SELECT q.*, s.name sport_name, s.normalized_name sport_key
                   FROM qualification_aggregate q
                   JOIN canonical_sport s ON s.id=q.sport_id'''
            )
        ]
        QualificationAggregate.objects.bulk_create(qualifications, batch_size=batch_size)
        self.stdout.write(f'자격 집계 {len(qualifications):,}건 적재')

        institutions = [
            Institution(
                id=row['id'], name=row['name'], normalized_name=row['normalized_name'],
                region=row['region'], normalized_region=row['normalized_region'],
                address=row['address'], normalized_address=row['normalized_address'],
                institution_type=row['institution_type'],
            )
            for row in source.execute('SELECT * FROM institution')
        ]
        Institution.objects.bulk_create(institutions, batch_size=batch_size)
        self.stdout.write(f'기관 {len(institutions):,}개 적재')

        cursor = source.execute(
            '''SELECT pp.id period_id, pp.start_date, pp.end_date, pp.capacity,
                      pp.operating_status, pp.source_key,
                      p.institution_id, p.sport_id, p.name, p.normalized_name,
                      s.name sport_name, s.normalized_name sport_key
               FROM program_period pp
               JOIN program p ON p.id=pp.program_id
               JOIN canonical_sport s ON s.id=p.sport_id
               ORDER BY pp.id'''
        )
        program_total = 0
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            programs = []
            cleanups = []
            for row in rows:
                status = row['operating_status']
                programs.append(Program(
                    id=row['period_id'], institution_id=row['institution_id'],
                    source_key=row['source_key'], name=row['name'],
                    normalized_name=row['normalized_name'], sport=row['sport_name'],
                    normalized_sport=row['sport_key'], start_date=row['start_date'],
                    end_date=row['end_date'], capacity=row['capacity'], status=status,
                    source_id=data_source.id, program_type=row['sport_name'],
                    matched_sport_id=row['sport_id'],
                    match_grade=Program.MatchGrade.EXACT, match_confidence=100,
                ))
                exclusion_reason = '' if status == ProgramCleanup.OperatingStatus.ACTIVE else status
                cleanups.append(ProgramCleanup(
                    program_id=row['period_id'], cleaned_name=row['name'],
                    matched_sport_id=row['sport_id'], operating_status=status,
                    is_usable=status == ProgramCleanup.OperatingStatus.ACTIVE,
                    exclusion_reason=exclusion_reason, reference_date=reference_date,
                ))
            Program.objects.bulk_create(programs, batch_size=batch_size)
            ProgramCleanup.objects.bulk_create(cleanups, batch_size=batch_size)
            program_total += len(rows)
            if program_total % 50000 < batch_size:
                self.stdout.write(f'프로그램 기간 {program_total:,}건 적재')

    def _validate(self, source):
        expected = {
            'sports': source.execute('SELECT COUNT(*) FROM canonical_sport').fetchone()[0],
            'institutions': source.execute('SELECT COUNT(*) FROM institution').fetchone()[0],
            'qualifications': source.execute('SELECT COUNT(*) FROM qualification_aggregate').fetchone()[0],
            'programs': source.execute('SELECT COUNT(*) FROM program_period').fetchone()[0],
        }
        actual = {
            'sports': CanonicalSport.objects.count(),
            'institutions': Institution.objects.count(),
            'qualifications': QualificationAggregate.objects.count(),
            'programs': Program.objects.count(),
        }
        if expected != actual:
            raise CommandError(f'적재 건수 검증 실패: expected={expected}, actual={actual}')
        if ProgramCleanup.objects.count() != expected['programs']:
            raise CommandError('ProgramCleanup 1:1 적재 검증에 실패했습니다.')
