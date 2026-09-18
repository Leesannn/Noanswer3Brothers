from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from analytics.models import ApplicationStatus, Institution, Program, QualificationAggregate, UploadBatch
from analytics.services.analytics import application_rate, demand_status, sport_analysis
from analytics.services.importers import ImportValidationError, import_batch, iter_table, preview, suggest_mapping
from analytics.services.normalizers import normalize_sport


class AnalyticsTests(TestCase):
    def test_application_rate(self):
        self.assertEqual(application_rate(100, 75), 75)
        self.assertEqual(demand_status(100, 100), '마감·대기')
        self.assertEqual(demand_status(100, 90), '수요 높음')
        self.assertEqual(demand_status(100, 50), '보통')
        self.assertEqual(demand_status(100, 49), '개선 검토')

    def test_zero_capacity(self):
        self.assertIsNone(application_rate(0, 10))
        self.assertEqual(demand_status(0, 10), '데이터 부족')

    def test_sport_normalization(self):
        self.assertEqual(normalize_sport('수영장'), '수영')
        self.assertEqual(normalize_sport(' 풋살 '), '축구')

    def test_classification_thresholds(self):
        institution = Institution.objects.create(name='가', normalized_name='가')
        program = Program.objects.create(institution=institution, source_key='p', name='수영', normalized_name='수영', sport='수영', normalized_sport='수영', capacity=10)
        ApplicationStatus.objects.create(program=program, source_key='a', capacity=10, applicants=10)
        result, thresholds = sport_analysis(QualificationAggregate.objects.none(), Program.objects.all(), ApplicationStatus.objects.select_related('program'))
        self.assertEqual(result[0]['rate'], 100)
        self.assertIn(result[0]['diagnosis'], ('증설 검토 가능', '현재 수준 관찰'))


class ImporterTests(TestCase):
    def setUp(self):
        super().setUp()
        self.temporary_media = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.temporary_media.name)
        self.media_override.enable()
        self.addCleanup(self.temporary_media.cleanup)
        self.addCleanup(self.media_override.disable)

    def make_batch(self, content, dataset_type='program', name='sample.csv'):
        batch = UploadBatch(dataset_type=dataset_type, original_filename=name)
        batch.temporary_file.save(name, ContentFile(content), save=False)
        batch.save()
        self.addCleanup(lambda: batch.temporary_file.delete(save=False) if batch.temporary_file else None)
        return batch

    def test_csv_utf8_and_mapping(self):
        content = '기관명,프로그램명,종목,정원\n행복센터,아침수영,수영,20\n'.encode('utf-8-sig')
        batch = self.make_batch(content)
        result = preview(batch.temporary_file.path, requested_type='program')
        self.assertEqual(result['encoding'], 'utf-8-sig')
        self.assertEqual(result['row_count'], 1)
        self.assertEqual(result['suggested_mapping']['institution'], '기관명')

    def test_csv_cp949(self):
        content = '기관명,프로그램명\n행복센터,수영\n'.encode('cp949')
        batch = self.make_batch(content)
        result = preview(batch.temporary_file.path, requested_type='program')
        self.assertEqual(result['encoding'], 'cp949')

    def test_column_mapping_and_duplicate_update(self):
        content = '기관,강좌,종목,정원\n센터,수영,수영,20\n센터,수영,수영,20\n'.encode('utf-8')
        batch = self.make_batch(content)
        mapping = {'institution': '기관', 'program': '강좌', 'sport': '종목', 'capacity': '정원'}
        import_batch(batch, mapping)
        self.assertEqual(Program.objects.count(), 1)
        self.assertEqual(batch.duplicate_count, 1)

    def test_failed_upload_rolls_back(self):
        content = '기관,강좌,정원\n센터,정상,20\n센터,오류,문자\n'.encode('utf-8')
        batch = self.make_batch(content)
        with self.assertRaises(ImportValidationError):
            import_batch(batch, {'institution': '기관', 'program': '강좌', 'capacity': '정원'})
        self.assertEqual(Program.objects.count(), 0)
        self.assertEqual(Institution.objects.count(), 0)

    def test_application_csv_links_existing_program_and_marks_demo_data(self):
        institution = Institution.objects.create(
            name='행복센터', normalized_name='행복센터',
            region='서울', normalized_region='서울',
        )
        program = Program.objects.create(
            institution=institution, source_key='existing-program',
            name='아침수영', normalized_name='아침수영',
            sport='수영', normalized_sport='수영', capacity=20,
        )
        content = (
            '기관명,지역,프로그램명,종목,기준일,정원,신청인원,대기인원,시연데이터\n'
            '행복센터,서울,아침수영,수영,2026-09-01,20,22,2,true\n'
        ).encode('utf-8')
        batch = self.make_batch(content, dataset_type='application')
        result = preview(batch.temporary_file.path, requested_type='application')
        import_batch(batch, result['suggested_mapping'])

        self.assertEqual(Program.objects.count(), 1)
        application = ApplicationStatus.objects.get()
        self.assertEqual(application.program, program)
        self.assertTrue(application.is_synthetic)
        self.assertEqual(application.applicants, 22)

    def test_xlsx_reading(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest('openpyxl이 설치되지 않았습니다.')
        path = settings.BASE_DIR / 'data' / 'test_sample.xlsx'
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '프로그램'
        sheet.append(['기관명', '프로그램명'])
        sheet.append(['센터', '수영'])
        workbook.save(path)
        headers, rows, encoding = iter_table(path, '프로그램')
        self.assertEqual(headers, ['기관명', '프로그램명'])
        self.assertEqual(next(rows)['프로그램명'], '수영')
        rows.close()
        self.assertEqual(encoding, 'xlsx')

    def test_suggest_mapping_for_real_headers(self):
        mapping = suggest_mapping('program', ['FCLTY_NM', 'PROGRM_NM', 'PROGRM_RCRIT_NMPR_CO'])
        self.assertEqual(mapping['institution'], 'FCLTY_NM')
        self.assertEqual(mapping['capacity'], 'PROGRM_RCRIT_NMPR_CO')
