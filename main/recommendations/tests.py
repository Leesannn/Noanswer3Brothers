from datetime import date

from django.test import TestCase
from django.urls import reverse

from analytics.models import (
    ApplicationStatus,
    CanonicalSport,
    Institution,
    Program,
    ProgramCleanup,
    QualificationAggregate,
)
from recommendations.services import (
    recommend_institutions,
    recommend_qualification_directions,
    score_region,
    score_sport_match,
)


class RecommendationTests(TestCase):
    def setUp(self):
        self.sport = CanonicalSport.objects.create(
            name='수영', normalized_name='수영', qualification_count=120,
        )
        self.institution = Institution.objects.create(
            name='가나다 체육센터', normalized_name='가나다체육센터',
            region='서울특별시', normalized_region='서울', address='서울특별시 성동구 테스트로 1',
        )
        self.program = self.make_program(self.institution, 'program-1')
        QualificationAggregate.objects.create(
            acquisition_year=2026, region='서울특별시', normalized_region='서울',
            sport='수영', normalized_sport='수영', qualification_type='생활스포츠지도사',
            grade='2급', acquisition_count=120, source_filename='test.csv',
        )

    def make_program(self, institution, source_key, with_cleanup=True, exact=True):
        program = Program.objects.create(
            institution=institution, source_key=source_key,
            name='성인 수영', normalized_name='성인수영', sport='수영', normalized_sport='수영',
            target='성인', weekdays='월수금', matched_sport=self.sport,
            match_grade=Program.MatchGrade.EXACT if exact else Program.MatchGrade.SIMILAR,
        )
        if with_cleanup:
            ProgramCleanup.objects.create(
                program=program, cleaned_name='수영', matched_sport=self.sport,
                operating_status=ProgramCleanup.OperatingStatus.ACTIVE,
                is_usable=True, reference_date=date(2026, 7, 31),
            )
        return program

    def add_applications(self, program, rate=95, waiting=True, synthetic=True):
        for month in range(1, 7):
            ApplicationStatus.objects.create(
                program=program, source_key=f'{program.source_key}-app-{month}',
                reference_date=date(2026, month, 1),
                capacity=100, applicants=rate, waitlist=1 if waiting and month == 6 else 0,
                is_synthetic=synthetic,
            )

    def licensed_criteria(self, **overrides):
        values = {
            'qualification_type': '생활스포츠지도사', 'sport_id': self.sport.pk,
            'region': '서울', 'district': '', 'mobility': 'province',
            'target': '성인', 'weekdays': ['월'], 'time_band': '',
        }
        values.update(overrides)
        return values

    def unlicensed_criteria(self, **overrides):
        values = {
            'region': '서울', 'primary_sport_id': self.sport.pk,
            'additional_sport_ids': [], 'experience': 'hobby',
            'target': '성인', 'time_band': '',
        }
        values.update(overrides)
        return values

    def test_licensed_institution_score(self):
        self.add_applications(self.program, rate=95, waiting=True)
        result = recommend_institutions(self.licensed_criteria())[0]
        self.assertEqual(result.total_score, 87)
        self.assertEqual(result.component_scores, {
            '종목 일치': 40, '지역 일치': 15, '대상 일치': 10,
            '최근 평균 신청률': 12, '대기자 발생': 10,
        })

    def test_unlicensed_direction_score(self):
        self.add_applications(self.program, rate=95, waiting=False)
        result = recommend_qualification_directions(self.unlicensed_criteria())[0]
        self.assertEqual(result.total_score, 91)
        self.assertEqual(result.component_scores['관심 종목 일치'], 35)
        self.assertEqual(result.component_scores['지역 일치'], 20)
        self.assertEqual(result.component_scores['지역 내 평균 신청률'], 16)
        self.assertEqual(result.component_scores['프로그램 공급 부족도'], 10)
        self.assertEqual(result.component_scores['지도 대상 일치'], 10)
        self.assertEqual(result.metrics['qualifications'][0]['label'], '생활스포츠지도사 2급')

    def test_sport_and_region_match_scores(self):
        self.assertEqual(score_sport_match(self.program, self.sport), 40)
        self.program.match_grade = Program.MatchGrade.SIMILAR
        self.program.sport = '아쿠아 프로그램'
        self.assertEqual(score_sport_match(self.program, self.sport), 25)
        self.assertEqual(score_region('district', '서울', '서울', '성동구', self.institution.address), 25)
        self.assertEqual(score_region('province', '서울', '서울'), 15)
        self.assertEqual(score_region('any', '서울', '부산'), 10)

    def test_missing_application_data_does_not_error(self):
        result = recommend_institutions(self.licensed_criteria())[0]
        self.assertIsNone(result.metrics['average_rate'])
        self.assertEqual(result.component_scores['최근 평균 신청률'], 0)
        self.assertIn('신청 데이터 없음', result.missing_data)

    def test_empty_result_page(self):
        empty_sport = CanonicalSport.objects.create(name='컬링', normalized_name='컬링')
        session = self.client.session
        session['licensed_recommendation_input'] = self.licensed_criteria(sport_id=empty_sport.pk)
        session.save()
        response = self.client.get(reverse('recommendations:licensed_recommendation_results'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '입력한 조건과 일치하는 기관을 찾지 못했습니다.')

    def test_synthetic_data_notice_is_rendered(self):
        self.add_applications(self.program, synthetic=True)
        session = self.client.session
        session['licensed_recommendation_input'] = self.licensed_criteria()
        session.save()
        response = self.client.get(reverse('recommendations:licensed_recommendation_results'))
        self.assertContains(response, '서비스 기능 시연을 위해 생성한 합성 데이터')
        self.assertContains(response, '합성 데이터 기반')

    def test_recommendation_pages_are_public(self):
        names = (
            'recommendation_start', 'licensed_recommendation_form',
            'unlicensed_recommendation_form',
        )
        for name in names:
            with self.subTest(name=name):
                response = self.client.get(reverse(f'recommendations:{name}'))
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(response.status_code, (301, 302, 403))
        detail = self.client.get(reverse(
            'recommendations:qualification_recommendation_detail', args=[self.sport.pk],
        ))
        self.assertEqual(detail.status_code, 200)

    def test_root_redirects_to_recommendation_home(self):
        response = self.client.get('/')
        self.assertRedirects(
            response, reverse('recommendations:recommendation_start'),
            fetch_redirect_response=False,
        )
        home = self.client.get(reverse('recommendations:recommendation_start'))
        self.assertContains(home, '스포츠 지도자의 다음 기회')
        self.assertContains(home, 'href="/recommendations/"', count=None)
        self.assertContains(home, 'href="/static/analytics/app.css"')
        self.assertNotContains(home, '/recommendations/static/analytics/app.css')

    def test_order_is_deterministic_for_same_input(self):
        second = Institution.objects.create(
            name='나다라 체육센터', normalized_name='나다라체육센터',
            region='서울특별시', normalized_region='서울', address='서울특별시 성동구 테스트로 2',
        )
        second_program = self.make_program(second, 'program-2')
        self.add_applications(self.program, rate=80, waiting=False)
        self.add_applications(second_program, rate=80, waiting=False)
        first_run = [item.target.pk for item in recommend_institutions(self.licensed_criteria())]
        second_run = [item.target.pk for item in recommend_institutions(self.licensed_criteria())]
        self.assertEqual(first_run, second_run)
        self.assertEqual(first_run, [self.institution.pk, second.pk])
