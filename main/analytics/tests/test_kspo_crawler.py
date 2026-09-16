import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from analytics.models import ExamSchedule, ExamScheduleFetchStatus
from analytics.services import license_info
from analytics.services.kspo_client import KspoFetchError, fetch
from analytics.services.kspo_license import parse_license_html
from analytics.services.kspo_schedule import parse_schedule_html


# sqms.kspo.or.kr의 실제 DOM 구조를 그대로 본떠 만든 축소 샘플. 실제 크롤링 대상
# 사이트에서 문구가 바뀌어도 이 구조(class 명, div 중첩)가 유지되는 한 파서는 계속
# 동작해야 한다.
SCHEDULE_HTML = """
<html><body>
<div class="comContTit"><div class="contTitArea"><h5 class="contTit">자격등급 선택</h5></div></div>
<div class="cptCourseSlct"></div>

<div class="comContTit"><div class="contTitArea"><h5 class="contTit">필기시험</h5></div></div>
<div class="cptTable cardM"><div class="tableArea">
<table class="tableType table003">
  <thead><tr><th>구분</th><th>원서접수</th><th>시험일</th><th>합격자발표</th></tr></thead>
  <tbody>
    <tr>
      <th class="bgBlue regular"><div class="tit">구분</div><div class="cont">일반과정</div></th>
      <td><div class="tit">원서접수</div><div class="cont">2026.04.02 10:00 (목) ~ <br/>2026.04.02 18:00 (목)</div></td>
      <td><div class="tit">시험일</div><div class="cont">2026.04.18 (토)</div></td>
      <td><div class="tit">합격자발표</div><div class="cont"> ~ <br/></div></td>
    </tr>
  </tbody>
</table>
</div></div>

<div class="comContTit"><div class="contTitArea"><h5 class="contTit">실기 · 구술 시험 - 동계(설상)</h5></div></div>
<div class="cptTable cardM"><div class="tableArea">
<table class="tableType table003">
  <thead><tr><th>구분</th><th>검정일</th></tr></thead>
  <tbody>
    <tr>
      <th class="bgBlue regular"><div class="tit">구분</div><div class="cont">일반과정</div></th>
      <td><div class="tit">검정일</div><div class="cont">2026.02.02 (월) ~ <br/>2026.03.01 (일)</div></td>
    </tr>
  </tbody>
</table>
</div></div>

<div class="comContTit"><div class="contTitArea"><h5 class="contTit">최종 합격자 발표 및 자격증발급(예정)</h5></div></div>
<div class="cptTable cardM"><div class="tableArea">
<table class="tableType table003">
  <thead><tr><th>최종 합격자 발표</th></tr></thead>
  <tbody>
    <tr><td><div class="tit">최종 합격자 발표</div><div class="cont">2026.12.04 14:00 (금)</div></td></tr>
  </tbody>
</table>
</div></div>
</body></html>
"""

LICENSE_HTML = """
<html><body>
<div class="cptSystemInfo"><div class="infoArea"><div class="partTab on"><div class="tabTxt">자격정의 및 관련근거</div></div>
<div class="partWrap"><div class="comInfoList"><ul class="nmbGroup">
  <li class="number"><div class="txt">자격정의</div><ul class="bltGroup"><li class="bullet"><div class="txt">테스트 자격 정의문.</div></li></ul></li>
  <li class="number"><div class="txt">관련근거</div><ul class="bltGroup">
    <li class="bullet"><div class="txt">국민체육진흥법 제11조</div></li>
    <li class="bullet"><div class="txt">국민체육진흥법 시행령 제8조</div></li>
  </ul></li>
</ul></div></div></div></div>

<div class="cptSystemInfo"><div class="infoArea"><div class="partTab on"><div class="tabTxt">자격요건 및 제출서류</div></div>
<div class="partWrap">
<div class="cptTable cardM"><div class="tableArea"><table class="tableType table003">
  <thead><tr><th colspan="2">응시자격</th><th>취득절차</th><th>제출서류(인정요건)</th></tr></thead>
  <tbody>
    <tr>
      <td><div class="tit">응시자격</div><div class="cont">일반과정</div></td>
      <td class="left"><div class="cont">테스트 응시자격 요건</div></td>
      <td class="left"><div class="tit">취득절차</div><div class="cont">-필기<br/>-연수</div></td>
      <td class="left"><div class="tit">제출서류(인정요건)</div><div class="cont">서류A<br/>서류B</div></td>
    </tr>
  </tbody>
</table></div></div>
</div></div></div>

<div class="cptSystemInfo"><div class="infoArea"><div class="partTab on"><div class="tabTxt">필기시험과목 <i>(2과목)</i></div></div>
<div class="partWrap"><div class="comInfoList"><ul class="nmbGroup">
  <li class="number"><div class="txt">필수</div><ul class="bltGroup inline">
    <li class="bullet"><div class="txt">과목A</div></li>
    <li class="bullet"><div class="txt">과목B</div></li>
  </ul></li>
</ul></div></div></div></div>

<div class="cptSystemInfo"><div class="infoArea"><div class="partTab on"><div class="tabTxt">자격검정기관 및 연수기관 지정현황</div></div>
<div class="partWrap"><div class="cptTable headL"><div class="tableArea"><table class="tableType table005">
  <tbody>
    <tr><th class="left">필기시험 검정기관</th><td class="left">테스트검정기관</td></tr>
    <tr><th class="left">연수기관</th><td class="left">테스트연수기관</td></tr>
  </tbody>
</table></div></div></div></div></div>

<div class="cptSystemInfo"><div class="infoArea"><div class="partTab on"><div class="tabTxt">유의사항</div></div>
<div class="partWrap"><div class="comInfoList"><ul class="nmbGroup">
  <li class="number"><div class="txt">자격검정 합격 및 연수 이수기준</div><ul class="bltGroup">
    <li class="bullet"><div class="txt">필기시험 : 60% 이상 득점</div></li>
  </ul></li>
</ul></div></div></div></div>

<div class="cptSystemInfo"><div class="infoArea"><div class="partTab on"><div class="tabTxt">체육지도자 결격 사유<br/>(국민체육진흥법 제11조의 5, 제12조)</div></div>
<div class="partWrap">
<div class="cptAddsDesc"><div class="descArea">
  <p class="txt">제11조의5(체육지도자의 결격사유)</p>
  <ul class="descList"><li class="item">1. 피성년후견인</li></ul>
</div></div>
</div></div></div>
</body></html>
"""


class ParseScheduleHtmlTests(TestCase):
    def test_parses_phases_seasons_and_course_types(self):
        rows = parse_schedule_html(SCHEDULE_HTML, 'LSC2')
        phases = {(r['phase'], r['season']) for r in rows}
        self.assertEqual(phases, {
            ('필기시험', ''), ('실기구술시험', '동계(설상)'), ('최종발표', ''),
        })
        self.assertTrue(all(r['grade_code'] == 'LSC2' for r in rows))

    def test_parses_date_range_into_start_and_end(self):
        rows = parse_schedule_html(SCHEDULE_HTML, 'LSC2')
        apply_row = next(r for r in rows if r['milestone'] == '원서접수')
        self.assertEqual(apply_row['start_at'].isoformat()[:16], '2026-04-02T10:00')
        self.assertEqual(apply_row['end_at'].isoformat()[:16], '2026-04-02T18:00')

    def test_single_date_only_sets_end_at(self):
        rows = parse_schedule_html(SCHEDULE_HTML, 'LSC2')
        exam_day = next(r for r in rows if r['milestone'] == '시험일')
        self.assertIsNone(exam_day['start_at'])
        self.assertEqual(exam_day['end_at'].isoformat()[:16], '2026-04-18T00:00')

    def test_empty_period_yields_none_but_keeps_row(self):
        rows = parse_schedule_html(SCHEDULE_HTML, 'LSC2')
        announce = next(r for r in rows if r['milestone'] == '합격자발표')
        self.assertIsNone(announce['start_at'])
        self.assertIsNone(announce['end_at'])

    def test_course_type_missing_defaults_to_empty(self):
        rows = parse_schedule_html(SCHEDULE_HTML, 'LSC2')
        final_row = next(r for r in rows if r['phase'] == '최종발표')
        self.assertEqual(final_row['course_type'], '')

    def test_unknown_structure_returns_empty_list_not_error(self):
        self.assertEqual(parse_schedule_html('<html><body>전혀 다른 페이지</body></html>', 'LSC2'), [])


class ParseLicenseHtmlTests(TestCase):
    def test_extracts_all_expected_fields(self):
        summary, paths, disqualification = parse_license_html(LICENSE_HTML, 'PSC1')
        self.assertEqual(summary['definition'], '테스트 자격 정의문.')
        self.assertIn('국민체육진흥법 제11조', summary['legal_basis'])
        self.assertIn('국민체육진흥법 시행령 제8조', summary['legal_basis'])
        self.assertEqual(summary['written_subjects'], '과목A, 과목B')
        self.assertEqual(summary['exam_agency'], '테스트검정기관')
        self.assertEqual(summary['training_agency'], '테스트연수기관')
        self.assertIn('60% 이상', summary['pass_criteria'])
        self.assertEqual(summary['sport_events_summary'], '')  # 이 자격은 자격종목 섹션이 없음

        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]['course_type'], '일반과정')
        self.assertEqual(paths[0]['eligibility'], '테스트 응시자격 요건')
        self.assertIn('연수', paths[0]['acquisition_process'])
        self.assertIn('서류A', paths[0]['submitted_documents'])
        self.assertIn('서류B', paths[0]['submitted_documents'])

        self.assertIn('피성년후견인', disqualification)

    def test_unknown_structure_returns_empty_without_error(self):
        summary, paths, disqualification = parse_license_html('<html></html>', 'PSC1')
        self.assertEqual(summary['definition'], '')
        self.assertEqual(paths, [])
        self.assertEqual(disqualification, '')


class KspoClientTests(TestCase):
    @patch('analytics.services.kspo_client.requests.get')
    def test_fetch_returns_text_on_success(self, mock_get):
        mock_get.return_value = Mock(status_code=200, text='<html>ok</html>', apparent_encoding='utf-8')
        result = fetch('https://sqms.kspo.or.kr/info/schedPlan.kspo', delay=0)
        self.assertEqual(result, '<html>ok</html>')

    @patch('analytics.services.kspo_client.requests.get')
    def test_fetch_raises_kspo_error_on_network_failure(self, mock_get):
        mock_get.side_effect = requests.ConnectionError('boom')
        with self.assertRaises(KspoFetchError):
            fetch('https://sqms.kspo.or.kr/info/schedPlan.kspo', delay=0)

    @patch('analytics.services.kspo_client.requests.get')
    def test_fetch_raises_kspo_error_on_http_error_status(self, mock_get):
        response = Mock(status_code=500)
        response.raise_for_status.side_effect = requests.HTTPError('500')
        mock_get.return_value = response
        with self.assertRaises(KspoFetchError):
            fetch('https://sqms.kspo.or.kr/info/schedPlan.kspo', delay=0)


class RefreshExamScheduleCommandTests(TestCase):
    def test_success_replaces_cache_and_clears_error(self):
        ExamScheduleFetchStatus.objects.create(grade_code='LSC2', last_error='이전 오류')
        ExamSchedule.objects.create(
            grade_code='LSC2', grade_name='2급 생활스포츠지도사', phase='필기시험',
            milestone='원서접수', raw_text='옛날 값',
        )
        fresh_rows = [{
            'grade_code': 'LSC2', 'grade_name': '2급 생활스포츠지도사', 'phase': '필기시험',
            'season': '', 'course_type': '일반과정', 'milestone': '원서접수',
            'start_at': None, 'end_at': None, 'raw_text': '새 값',
        }]
        with patch('analytics.management.commands.refresh_exam_schedule.fetch_schedule', return_value=fresh_rows):
            call_command('refresh_exam_schedule', '--grade', 'LSC2', stdout=StringIO())

        rows = list(ExamSchedule.objects.filter(grade_code='LSC2'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].raw_text, '새 값')
        status = ExamScheduleFetchStatus.objects.get(grade_code='LSC2')
        self.assertEqual(status.last_error, '')
        self.assertIsNotNone(status.last_success_at)

    def test_failure_preserves_existing_cache_and_records_error(self):
        ExamSchedule.objects.create(
            grade_code='LSC2', grade_name='2급 생활스포츠지도사', phase='필기시험',
            milestone='원서접수', raw_text='기존 캐시 값',
        )
        with patch(
            'analytics.management.commands.refresh_exam_schedule.fetch_schedule',
            side_effect=KspoFetchError('사이트 응답 없음'),
        ):
            call_command('refresh_exam_schedule', '--grade', 'LSC2', stdout=StringIO(), stderr=StringIO())

        rows = list(ExamSchedule.objects.filter(grade_code='LSC2'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].raw_text, '기존 캐시 값', '실패 시 기존 캐시가 지워지면 안 된다')
        status = ExamScheduleFetchStatus.objects.get(grade_code='LSC2')
        self.assertIn('사이트 응답 없음', status.last_error)

    def test_empty_parse_result_is_treated_as_failure(self):
        ExamSchedule.objects.create(
            grade_code='LSC2', grade_name='2급 생활스포츠지도사', phase='필기시험',
            milestone='원서접수', raw_text='기존 캐시 값',
        )
        with patch('analytics.management.commands.refresh_exam_schedule.fetch_schedule', return_value=[]):
            call_command('refresh_exam_schedule', '--grade', 'LSC2', stdout=StringIO(), stderr=StringIO())

        rows = list(ExamSchedule.objects.filter(grade_code='LSC2'))
        self.assertEqual(len(rows), 1, '사이트 구조가 바뀌어 파싱 결과가 비어도 기존 캐시를 지우면 안 된다')
        status = ExamScheduleFetchStatus.objects.get(grade_code='LSC2')
        self.assertTrue(status.last_error)


class LicenseInfoLoaderTests(TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.data_dir = Path(self.tmp_dir.name) / 'data'
        self.data_dir.mkdir()
        # 모듈 레벨 lru_cache가 테스트 간 상태를 들고 있지 않도록 매번 비운다.
        license_info.get_license_grades.cache_clear()
        license_info._all_eligibility_paths.cache_clear()
        license_info.get_disqualification_text.cache_clear()
        self.addCleanup(license_info.get_license_grades.cache_clear)
        self.addCleanup(license_info._all_eligibility_paths.cache_clear)
        self.addCleanup(license_info.get_disqualification_text.cache_clear)

    def test_missing_csv_returns_empty_without_error(self):
        with override_settings(BASE_DIR=Path(self.tmp_dir.name)):
            self.assertEqual(license_info.get_license_grades(), {})
            self.assertEqual(license_info.get_eligibility_paths('PSC1'), [])
            self.assertEqual(license_info.get_disqualification_text(), '')

    def test_reads_csv_and_filters_by_grade(self):
        (self.data_dir / 'kspo_license_grades.csv').write_text(
            'grade_code,grade_name\nPSC1,1급 전문스포츠지도사\n', encoding='utf-8-sig',
        )
        (self.data_dir / 'kspo_license_eligibility_paths.csv').write_text(
            'grade_code,course_type\nPSC1,일반과정\nPSC2,일반과정\n', encoding='utf-8-sig',
        )
        (self.data_dir / 'kspo_disqualification.txt').write_text('결격사유 텍스트', encoding='utf-8')

        with override_settings(BASE_DIR=Path(self.tmp_dir.name)):
            grades = license_info.get_license_grades()
            self.assertEqual(grades['PSC1']['grade_name'], '1급 전문스포츠지도사')

            psc1_paths = license_info.get_eligibility_paths('PSC1')
            self.assertEqual(len(psc1_paths), 1)
            self.assertEqual(license_info.get_eligibility_paths('PSC2'), [{'grade_code': 'PSC2', 'course_type': '일반과정'}])

            self.assertEqual(license_info.get_disqualification_text(), '결격사유 텍스트')
