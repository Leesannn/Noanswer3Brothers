import csv
import sqlite3
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from analytics.services.clean_database_builder import (
    build_clean_database, normalize_institution, normalize_region,
    operating_status, reference_date_from_filename, split_qualification,
)


class CleanDatabaseBuilderUnitTests(SimpleTestCase):
    def test_normalization_helpers(self):
        self.assertEqual(normalize_institution('(취약시설)(공공) 서울 수영장'), '서울 수영장')
        self.assertEqual(normalize_region('서울특별시'), '서울')
        self.assertEqual(split_qualification('2급 생활스포츠지도사'), ('생활스포츠지도사', '2급'))

    def test_reference_date_and_status(self):
        path = 'KS_PUBLIC_ALSFC_PROGRM_INFO_202607.csv'
        self.assertEqual(reference_date_from_filename(path), date(2026, 7, 31))
        reference = date(2026, 7, 31)
        self.assertEqual(operating_status(date(2026, 7, 1), reference, reference), 'active')
        self.assertEqual(operating_status(date(2025, 1, 1), date(2025, 1, 31), reference), 'ended')
        self.assertEqual(operating_status(date(2026, 8, 1), date(2026, 8, 31), reference), 'upcoming')


class CleanDatabaseBuilderIntegrationTests(SimpleTestCase):
    def test_builds_new_database_without_semantic_name_simplification(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            qualification = root / 'KS_PTDRCTOR_PSEXAM_INFO_202607.csv'
            program = root / 'KS_PUBLIC_ALSFC_PROGRM_INFO_202607.csv'
            with qualification.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    'QUALF_GRAD_NM', 'QUALF_ITEM_NM', 'ACQS_DE', 'ACQS_AREA_NM',
                    'SDYTRN_OPERTN_YEAR', 'WRTNG_OPERTN_YEAR', 'PRCTTQ_OPERTN_YEAR',
                ])
                writer.writeheader()
                writer.writerow({
                    'QUALF_GRAD_NM': '2급 생활스포츠지도사',
                    'QUALF_ITEM_NM': '수영', 'ACQS_DE': '20250101',
                    'ACQS_AREA_NM': '서울',
                })
            program_fields = [
                'FCLTY_NM', 'FCLTY_TY_NM', 'FCLTY_FLAG_NM', 'CTPRVN_NM',
                'FCLTY_ADDR', 'INDUTY_NM', 'PROGRM_TY_NM', 'PROGRM_NM',
                'PROGRM_BEGIN_DE', 'PROGRM_END_DE', 'PROGRM_RCRIT_NMPR_CO',
            ]
            with program.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=program_fields)
                writer.writeheader()
                row = {
                    'FCLTY_NM': '(취약시설)테스트센터', 'FCLTY_TY_NM': '수영장',
                    'CTPRVN_NM': '서울특별시', 'FCLTY_ADDR': '서울 테스트로 1',
                    'INDUTY_NM': '수영장', 'PROGRM_TY_NM': '수영',
                    'PROGRM_NM': '어린이 초급수영 16시',
                    'PROGRM_BEGIN_DE': '20260701', 'PROGRM_END_DE': '20260731',
                    'PROGRM_RCRIT_NMPR_CO': '20',
                }
                writer.writerow(row)
                writer.writerow(row)
            paths, stats, checks = build_clean_database(
                qualification, program, root / 'output',
            )
            self.assertEqual(checks['integrity_check'], 'ok')
            self.assertEqual(stats['programs_created'], 1)
            self.assertEqual(stats['periods_created'], 1)
            self.assertEqual(stats['period_duplicates'], 1)
            connection = sqlite3.connect(paths.database)
            try:
                self.assertEqual(
                    connection.execute('SELECT name FROM program').fetchone()[0],
                    '어린이 초급수영 16시',
                )
                self.assertEqual(
                    connection.execute('SELECT operating_status FROM program_period').fetchone()[0],
                    'active',
                )
            finally:
                connection.close()
