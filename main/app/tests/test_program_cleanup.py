from datetime import date
from io import StringIO

from django.core.management import call_command
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from app.models import CanonicalSport, Institution, Program, ProgramCleanup, QualificationAggregate
from app.services.program_catalog import regional_program_qualification_comparison
from app.services.program_cleanup import ProgramCleaner


class ProgramCleanupTests(TestCase):
    reference_date = date(2026, 7, 31)

    def setUp(self):
        names = ['수영', '축구', '농구', '탁구', '배드민턴', '테니스', '보디빌딩', '체조', '빙상', '사이클']
        self.sports = {
            name: CanonicalSport.objects.create(name=name, normalized_name=name, qualification_count=1)
            for name in names
        }
        self.institution = Institution.objects.create(
            name='서울센터', normalized_name='서울센터',
            region='서울특별시', normalized_region='서울', address='서울시 테스트로 1',
        )
        self.qualification = QualificationAggregate.objects.create(
            acquisition_year=2026, region='서울특별시', normalized_region='서울',
            sport='수영', normalized_sport='수영', qualification_type='생활스포츠지도사',
            grade='2급', acquisition_count=7, source_filename='qualification.csv',
        )
        self.cleaner = ProgramCleaner(list(self.sports.values()))
        self.sequence = 0

    def program(self, name, **kwargs):
        self.sequence += 1
        defaults = {
            'institution': self.institution,
            'source_key': f'program-{self.sequence}',
            'name': name,
            'normalized_name': name.replace(' ', ''),
            'start_date': date(2026, 7, 1),
            'end_date': date(2026, 8, 31),
        }
        defaults.update(kwargs)
        return Program.objects.create(**defaults)

    def test_original_program_region_and_qualification_are_preserved(self):
        program = self.program('성인수영 초급 월수금')
        original = (program.name, program.normalized_name)
        region = (self.institution.region, self.institution.normalized_region, self.institution.address)
        qualification = (
            self.qualification.normalized_region, self.qualification.sport,
            self.qualification.acquisition_count,
        )
        call_command('clean_program_data', stdout=StringIO())
        program.refresh_from_db()
        self.institution.refresh_from_db()
        self.qualification.refresh_from_db()
        self.assertEqual((program.name, program.normalized_name), original)
        self.assertEqual((self.institution.region, self.institution.normalized_region, self.institution.address), region)
        self.assertEqual((self.qualification.normalized_region, self.qualification.sport, self.qualification.acquisition_count), qualification)

    def test_active_single_sport_is_usable(self):
        result = self.cleaner.clean(self.program('성인수영 초급 월수금'), self.reference_date)
        self.assertEqual(result.operating_status, 'active')
        self.assertTrue(result.is_usable)
        self.assertEqual(result.cleaned_name, '수영')
        self.assertEqual(result.canonical_key, '수영')

    def test_ended_by_name_or_date_is_excluded(self):
        named = self.cleaner.clean(self.program('폐강 필라테스'), self.reference_date)
        dated = self.cleaner.clean(self.program('수영', end_date=date(2026, 6, 30)), self.reference_date)
        self.assertEqual(named.operating_status, 'ended')
        self.assertEqual(named.exclusion_reason, 'ended')
        self.assertFalse(named.is_usable)
        self.assertEqual(dated.operating_status, 'ended')

    def test_incomplete_or_future_date_is_unknown(self):
        incomplete = self.cleaner.clean(self.program('수영', end_date=None), self.reference_date)
        future = self.cleaner.clean(self.program('수영', start_date=date(2026, 8, 1)), self.reference_date)
        self.assertEqual(incomplete.operating_status, 'unknown')
        self.assertEqual(future.operating_status, 'unknown')
        self.assertFalse(incomplete.is_usable)

    def test_multiple_sports_are_excluded_without_forced_match(self):
        for name in ('탁구/농구', '축구·농구', '탁구, 축구, 농구', '배드민턴+탁구', '종합 구기 프로그램'):
            with self.subTest(name=name):
                result = self.cleaner.clean(self.program(name), self.reference_date)
                self.assertEqual(result.exclusion_reason, 'multi_sport')
                self.assertFalse(result.is_usable)
                self.assertIsNone(result.canonical_key)

    def test_name_normalization_examples(self):
        cases = {
            '성인수영 초급 월수금': ('수영', '수영'),
            '어린이수영': ('수영', '수영'),
            '자유수영': ('수영', '수영'),
            '수영강습': ('수영', '수영'),
            '아쿠아피트니스': ('아쿠아로빅', '수영'),
            '헬스장 이용': ('헬스', '보디빌딩'),
            '피트니스 프로그램': ('헬스', '보디빌딩'),
            '초등 풋살': ('풋살', '축구'),
            '기구 필라테스': ('필라테스', '체조'),
            '요가 교실': ('요가', '체조'),
            '피겨스케이팅 초급': ('피겨스케이팅', '빙상'),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                result = self.cleaner.clean(self.program(name), self.reference_date)
                self.assertEqual((result.cleaned_name, result.canonical_key), expected)

    def test_unclear_program_remains_unmatched(self):
        result = self.cleaner.clean(self.program('주말 문화 특별반'), self.reference_date)
        self.assertEqual(result.exclusion_reason, 'unmatched')
        self.assertIsNone(result.canonical_key)
        self.assertFalse(result.is_usable)

    def test_nonessential_variant_is_collapsed_to_canonical_name(self):
        result = self.cleaner.clean(self.program('테니스 A반'), self.reference_date)
        self.assertEqual(result.cleaned_name, '테니스')
        self.assertEqual(result.canonical_key, '테니스')

    def test_command_is_idempotent(self):
        self.program('수영')
        call_command('clean_program_data', stdout=StringIO())
        first_id = ProgramCleanup.objects.get().pk
        call_command('clean_program_data', stdout=StringIO())
        self.assertEqual(ProgramCleanup.objects.count(), 1)
        self.assertEqual(ProgramCleanup.objects.get().pk, first_id)

    def test_regional_comparison_uses_only_usable_and_preserves_qualification_total(self):
        self.program('수영')
        self.program('탁구/농구')
        self.program('폐강 수영')
        call_command('clean_program_data', stdout=StringIO())
        rows, summary = regional_program_qualification_comparison({'region': '서울'})
        swimming = next(row for row in rows if row['sport_key'] == '수영')
        self.assertEqual(swimming['program_count'], 1)
        self.assertEqual(swimming['qualification_count'], 7)
        self.assertEqual(swimming['supply_per_program'], 7)
        self.assertEqual(summary['qualification_count'], 7)
        self.assertEqual(QualificationAggregate.objects.aggregate(total=Sum('acquisition_count'))['total'], 7)

    def test_zero_program_supply_is_safe(self):
        QualificationAggregate.objects.create(
            acquisition_year=2026, region='서울특별시', normalized_region='서울',
            sport='축구', normalized_sport='축구', qualification_type='생활스포츠지도사',
            acquisition_count=3, source_filename='qualification.csv',
        )
        rows, _ = regional_program_qualification_comparison({'region': '서울', 'sport': '축구'})
        self.assertEqual(rows[0]['program_count'], 0)
        self.assertIsNone(rows[0]['supply_per_program'])

    def test_new_pages_render(self):
        self.program('수영')
        call_command('clean_program_data', stdout=StringIO())
        self.assertEqual(self.client.get(reverse('analytics:current_programs')).status_code, 200)
        self.assertEqual(self.client.get(reverse('analytics:demand_supply'), {'region': '서울'}).status_code, 200)
