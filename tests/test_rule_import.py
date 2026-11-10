import io
import unittest

from openpyxl import Workbook

from qa.rule_import import parse_workbook


class RuleImportTests(unittest.TestCase):
    def workbook(self):
        workbook = Workbook()
        summary = workbook.active
        summary.title = '요약'
        summary.append(['범위', '설명'])
        sheet = workbook.create_sheet('테스트케이스')
        sheet.append(['검사 목록'])
        sheet.append(['TC ID', '제목', '테스트 단계', '판정기준', '요소 선택자', '검사 종류', '기대값'])
        sheet.append(['TC-01', '목록 표시', '화면 열기', '목록이 보인다', '#list', '표시 여부', True])
        sheet.append(['TC-02', '로그인 필요', '로그인 화면 확인', '로그인 안내가 보인다', None, None, None])
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        return stream.getvalue()

    def test_reads_all_test_case_rows_and_skips_summary(self):
        result = parse_workbook(self.workbook())
        self.assertEqual([case['caseId'] for case in result['cases']], ['TC-01', 'TC-02'])
        self.assertEqual(result['cases'][0]['expectedValue'], 'true')
        self.assertEqual(result['cases'][1]['sourceRow'], 4)
        self.assertEqual(result['sheets'][0]['name'], '테스트케이스')

    def test_rejects_non_workbook(self):
        with self.assertRaisesRegex(ValueError, '.xlsx'):
            parse_workbook(b'not a workbook')


if __name__ == '__main__':
    unittest.main()
