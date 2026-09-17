from django.test import TestCase
from django.urls import reverse

from analytics.models import Institution, Program


class DashboardViewTests(TestCase):
    def setUp(self):
        institution = Institution.objects.create(name='서울센터', normalized_name='서울센터', region='서울', normalized_region='서울')
        Program.objects.create(institution=institution, source_key='seoul', name='수영', normalized_name='수영', sport='수영', normalized_sport='수영')
        institution2 = Institution.objects.create(name='부산센터', normalized_name='부산센터', region='부산', normalized_region='부산')
        Program.objects.create(institution=institution2, source_key='busan', name='축구', normalized_name='축구', sport='축구', normalized_sport='축구')

    def test_filter_changes_aggregate(self):
        response = self.client.get(reverse('analytics:dashboard'), {'region': '서울'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['metrics']['program_total'], 1)

    def test_major_pages_render(self):
        for name in ('dashboard', 'instructors', 'programs', 'applications', 'demand_supply'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f'analytics:{name}')).status_code, 200)
