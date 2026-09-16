from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from analytics.management.commands.generate_demo_data import recent_months
from analytics.models import ApplicationStatus, Institution, Program, ProgramCleanup


class DemoDataTests(TestCase):
    def setUp(self):
        institution = Institution.objects.create(
            name='시연 체육관', normalized_name='시연체육관',
        )
        self.programs = [
            Program.objects.create(
                institution=institution,
                source_key=f'program-{index}',
                name=f'프로그램 {index}',
                normalized_name=f'프로그램{index}',
                sport='수영', normalized_sport='수영',
            )
            for index in range(4)
        ]

    def test_generate_success_rate_and_unique_period(self):
        call_command('generate_demo_data', stdout=StringIO())
        self.assertEqual(ApplicationStatus.objects.filter(is_synthetic=True).count(), 24)
        self.assertEqual(
            ApplicationStatus.objects.filter(is_synthetic=True).values(
                'program_id', 'reference_date',
            ).distinct().count(),
            24,
        )
        for item in ApplicationStatus.objects.filter(is_synthetic=True):
            self.assertGreater(item.capacity, 0)
            self.assertGreaterEqual(item.applicants, 0)
            self.assertGreaterEqual(item.waitlist, 0)
            self.assertAlmostEqual(
                item.application_rate, item.applicants / item.capacity * 100,
            )

    def test_second_run_does_not_duplicate(self):
        call_command('generate_demo_data', stdout=StringIO())
        output = StringIO()
        call_command('generate_demo_data', stdout=output)
        self.assertEqual(ApplicationStatus.objects.count(), 24)
        self.assertIn('합성 데이터가 이미 존재합니다.', output.getvalue())

    def test_only_usable_active_programs_receive_demo_rows_after_cleanup(self):
        ProgramCleanup.objects.create(
            program=self.programs[0], cleaned_name='수영',
            operating_status=ProgramCleanup.OperatingStatus.ACTIVE,
            is_usable=True, reference_date=date(2026, 7, 31),
        )
        call_command('generate_demo_data', stdout=StringIO())
        rows = ApplicationStatus.objects.filter(is_synthetic=True)
        self.assertEqual(rows.count(), 6)
        self.assertEqual(set(rows.values_list('program_id', flat=True)), {self.programs[0].pk})

    def test_real_data_is_not_deleted(self):
        actual = ApplicationStatus.objects.create(
            program=self.programs[0], source_key='actual',
            reference_date=recent_months()[0],
            capacity=10, applicants=7, waitlist=0, is_synthetic=False,
        )
        call_command('generate_demo_data', stdout=StringIO())
        call_command('generate_demo_data', refresh=True, stdout=StringIO())
        actual.refresh_from_db()
        self.assertFalse(actual.is_synthetic)
        self.assertEqual(actual.applicants, 7)

    def test_dashboard_responds_with_demo_data(self):
        call_command('generate_demo_data', stdout=StringIO())
        response = self.client.get(reverse('analytics:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '시뮬레이션')
