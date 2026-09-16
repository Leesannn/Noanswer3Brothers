from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from analytics.models import CanonicalSport, Institution, Program, QualificationAggregate
from analytics.services.sport_matching import SportMatcher


class SportMatcherRuleTests(TestCase):
    def matcher(self):
        names = ['수영', '축구', '농구', '보디빌딩', '생활체조', '빙상', '사이클']
        sports = [CanonicalSport(name=name, normalized_name=name) for name in names]
        return SportMatcher(sports)

    def assert_match(self, expected, **fields):
        result = self.matcher().match(**fields)
        self.assertEqual(result.canonical_key, expected)
        self.assertIn(result.grade, ('exact', 'similar'))
        self.assertGreaterEqual(result.confidence, 80)
        self.assertTrue(result.reason)
        self.assertTrue(result.rules)

    def test_swimming_pool_free_swimming(self):
        self.assert_match('수영', name='수영장 자유수영')

    def test_aqua_aerobics(self):
        self.assert_match('수영', name='아쿠아로빅 교실')

    def test_futsal(self):
        self.assert_match('축구', name='풋살 강습')

    def test_gym(self):
        self.assert_match('보디빌딩', name='헬스장 이용')

    def test_fitness(self):
        self.assert_match('보디빌딩', name='피트니스 프로그램')

    def test_pilates(self):
        self.assert_match('생활체조', name='필라테스 수업')

    def test_yoga(self):
        self.assert_match('생활체조', name='요가 교실')

    def test_parent_rule_uses_existing_taxonomy_fallback(self):
        sports = [CanonicalSport(name='체조', normalized_name='체조')]
        result = SportMatcher(sports).match(name='필라테스 수업')
        self.assertEqual(result.canonical_key, '체조')
        self.assertEqual(result.grade, 'similar')

    def test_composite_program_requires_review(self):
        result = self.matcher().match(name='축구·농구 복합 프로그램')
        self.assertEqual(result.grade, 'review')
        self.assertIsNone(result.canonical_key)
        self.assertEqual({item['sport'] for item in result.candidates}, {'축구', '농구'})

    def test_no_evidence_is_unmatched(self):
        result = self.matcher().match(name='주말 특별 프로그램')
        self.assertEqual(result.grade, 'unmatched')
        self.assertIsNone(result.canonical_key)


class ManualMatchPreservationTests(TestCase):
    def test_manual_match_is_not_overwritten(self):
        QualificationAggregate.objects.create(
            acquisition_year=2026, sport='수영', normalized_sport='수영',
            qualification_type='생활스포츠지도사', acquisition_count=1,
            source_filename='test.csv',
        )
        canonical = CanonicalSport.objects.create(name='수영', normalized_name='수영', qualification_count=1)
        institution = Institution.objects.create(name='센터', normalized_name='센터')
        program = Program.objects.create(
            institution=institution, source_key='manual', name='풋살 강습',
            normalized_name='풋살강습', matched_sport=canonical,
            match_grade=Program.MatchGrade.EXACT, match_confidence=100,
            match_reason='관리자 확정', match_is_manual=True,
        )
        call_command('match_program_sports', stdout=StringIO())
        program.refresh_from_db()
        self.assertEqual(program.matched_sport_id, canonical.id)
        self.assertEqual(program.match_reason, '관리자 확정')
        self.assertTrue(program.match_is_manual)
