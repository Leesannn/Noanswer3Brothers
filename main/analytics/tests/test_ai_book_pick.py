import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from analytics.services.gemini_book_picks import BookPickError, _validate_payload

SAMPLE_PAYLOAD = {
    'bestMatch': {
        'title': '체육측정평가 총론',
        'author': '홍길동',
        'publisher': '대한미디어',
        'year': '2024',
        'reason': '실기와 필기를 함께 다뤄 시험 범위를 촘촘히 짚어줍니다.',
        'coveredSubjects': ['스포츠영양학', '트레이닝론'],
    },
    'alsoGood': [
        {'title': '운동상해 핵심노트', 'author': '김철수', 'category': '요약서', 'reason': '핵심만 빠르게 복습하기 좋습니다.'},
        {'title': '체육측정평가론 기출문제집', 'author': '이영희', 'category': '기출문제집', 'reason': '최근 5개년 기출을 유형별로 정리했습니다.'},
    ],
}

WRITTEN_SUBJECTS = ['스포츠영양학', '운동상해', '체육측정평가론', '트레이닝론']


class ValidatePayloadTests(TestCase):
    """Gemini 응답 파싱/검증 로직 단위 테스트."""

    def test_valid_payload_passes_through(self):
        result = _validate_payload(SAMPLE_PAYLOAD, WRITTEN_SUBJECTS)
        self.assertEqual(result['bestMatch']['title'], '체육측정평가 총론')
        self.assertEqual(len(result['alsoGood']), 2)

    def test_covered_subjects_filtered_to_known_written_subjects(self):
        payload = json.loads(json.dumps(SAMPLE_PAYLOAD))
        payload['bestMatch']['coveredSubjects'] = ['스포츠영양학', '존재하지않는과목']
        result = _validate_payload(payload, WRITTEN_SUBJECTS)
        self.assertEqual(result['bestMatch']['coveredSubjects'], ['스포츠영양학'])

    def test_missing_best_match_field_raises(self):
        payload = json.loads(json.dumps(SAMPLE_PAYLOAD))
        payload['bestMatch']['title'] = ''
        with self.assertRaises(BookPickError):
            _validate_payload(payload, WRITTEN_SUBJECTS)

    def test_also_good_must_have_exactly_two_items(self):
        payload = json.loads(json.dumps(SAMPLE_PAYLOAD))
        payload['alsoGood'] = payload['alsoGood'][:1]
        with self.assertRaises(BookPickError):
            _validate_payload(payload, WRITTEN_SUBJECTS)

    def test_non_dict_payload_raises(self):
        with self.assertRaises(BookPickError):
            _validate_payload(['not', 'a', 'dict'], WRITTEN_SUBJECTS)


class AiBookPickSectionRenderTests(TestCase):
    """시험정보 페이지에 AI 추천 교재 섹션이 올바르게 렌더링되는지."""

    def test_closed_bar_renders_with_accessible_toggle(self):
        response = self.client.get(reverse('analytics:exam_info'), {'grade': 'PSC1'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-ai-pick-toggle')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'aria-controls="exam-ai-pick-panel"')
        self.assertContains(response, 'BOOK PICK')
        self.assertContains(response, '추천 교재')
        self.assertContains(response, '1급 전문스포츠지도사 필기 과목 구성에 맞춰 골랐어요')

    def test_context_data_script_carries_certification_and_subjects(self):
        response = self.client.get(reverse('analytics:exam_info'), {'grade': 'PSC1'})
        self.assertContains(response, 'id="exam-ai-pick-data"')
        self.assertContains(response, '"certificationId": "PSC1"')

    def test_section_sits_between_grade_selector_and_license_panel(self):
        response = self.client.get(reverse('analytics:exam_info'), {'grade': 'PSC1'})
        content = response.content.decode()
        selector_end = content.index('</nav>')
        ai_pick_start = content.index('data-ai-pick')
        license_panel_start = content.index('exam-license-panel')
        self.assertTrue(selector_end < ai_pick_start < license_panel_start)


class BookRecommendationsViewTests(TestCase):
    """POST /api/book-recommendations/ 엔드포인트 동작."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _post(self, body):
        return self.client.post(
            reverse('analytics:book_recommendations'),
            data=json.dumps(body),
            content_type='application/json',
        )

    def test_rejects_unknown_certification(self):
        response = self._post({'certificationId': 'ZZZZ', 'certificationName': '', 'writtenSubjects': []})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'invalid_certification')

    def test_rejects_invalid_json_body(self):
        response = self.client.post(
            reverse('analytics:book_recommendations'), data='not-json', content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_body_with_invalid_encoding(self):
        response = self.client.post(
            reverse('analytics:book_recommendations'), data=b'\xb1\xb2\xb3', content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(GEMINI_API_KEY='')
    def test_missing_api_key_surfaces_as_error_without_crashing(self):
        # 로컬에 .env로 실제 키가 설정돼 있어도 이 테스트만큼은 "키 없음" 경로를 강제로 재현한다.
        response = self._post({'certificationId': 'PSC1', 'certificationName': '', 'writtenSubjects': []})
        self.assertEqual(response.status_code, 502)
        self.assertIn('error', response.json())

    @patch('analytics.services.gemini_book_picks._request_from_gemini')
    def test_success_response_includes_bookstore_urls(self, mock_request):
        mock_request.return_value = SAMPLE_PAYLOAD
        response = self._post({'certificationId': 'PSC1', 'certificationName': '1급 전문스포츠지도사', 'writtenSubjects': WRITTEN_SUBJECTS})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['bestMatch']['title'], '체육측정평가 총론')
        self.assertEqual(len(data['alsoGood']), 2)
        self.assertIn('bookstoreUrls', data)
        self.assertIn('kyobobook.co.kr', data['bookstoreUrls']['bestMatch'])
        self.assertEqual(len(data['bookstoreUrls']['alsoGood']), 2)

    @patch('analytics.services.gemini_book_picks._request_from_gemini')
    def test_second_request_for_same_grade_uses_cache(self, mock_request):
        mock_request.return_value = SAMPLE_PAYLOAD
        self._post({'certificationId': 'PSC1', 'certificationName': '1급 전문스포츠지도사', 'writtenSubjects': WRITTEN_SUBJECTS})
        self._post({'certificationId': 'PSC1', 'certificationName': '1급 전문스포츠지도사', 'writtenSubjects': WRITTEN_SUBJECTS})
        self.assertEqual(mock_request.call_count, 1)

    @patch('analytics.services.gemini_book_picks._request_from_gemini')
    def test_refresh_flag_bypasses_cache(self, mock_request):
        mock_request.return_value = SAMPLE_PAYLOAD
        self._post({'certificationId': 'PSC1', 'certificationName': '1급 전문스포츠지도사', 'writtenSubjects': WRITTEN_SUBJECTS})
        self._post({'certificationId': 'PSC1', 'certificationName': '1급 전문스포츠지도사', 'writtenSubjects': WRITTEN_SUBJECTS, 'refresh': True})
        self.assertEqual(mock_request.call_count, 2)

    @patch('analytics.services.gemini_book_picks._request_from_gemini')
    def test_rate_limit_blocks_excess_requests_per_minute(self, mock_request):
        from analytics.views import AI_BOOK_PICK_RATE_LIMIT

        mock_request.return_value = SAMPLE_PAYLOAD
        statuses = []
        for _ in range(AI_BOOK_PICK_RATE_LIMIT + 1):
            statuses.append(self._post({
                'certificationId': 'PSC1', 'certificationName': '1급 전문스포츠지도사', 'writtenSubjects': WRITTEN_SUBJECTS,
                'refresh': True,
            }).status_code)
        self.assertEqual(statuses[-1], 429)
        self.assertTrue(all(code == 200 for code in statuses[:-1]))
