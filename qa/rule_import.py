"""Read QA test case rows from an Excel workbook without executing formulas."""

from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook


ALIASES = {
    'caseId': ('tcid', '테스트케이스id', '테스트케이스번호', '케이스id', 'caseid', 'testcaseid', '규칙id'),
    'title': ('제목', '테스트케이스명', '테스트케이스제목', '케이스명', '테스트명', '규칙이름', 'title', 'testcasename'),
    'checkTarget': ('확인내용', '검증내용', '검사항목', '검수내용', '검증대상', 'checktarget', 'description'),
    'steps': ('테스트단계', '수행절차', '실행단계', 'steps', 'teststeps', 'procedure'),
    'expectedResult': ('판정기준', '기대결과', '예상결과', 'expectedresult', 'passcriteria', 'expected'),
    'preconditionsText': ('사전조건', '선행조건', 'precondition', 'preconditions'),
    'category1': ('대분류', 'category1'),
    'category2': ('중분류', 'category2'),
    'category3': ('소분류', '소분류기능', '기능', 'category3'),
    'testData': ('테스트데이터', '입력데이터', 'testdata'),
    'accountCondition': ('계정조건', '로그인상태', '계정유형', 'accountcondition'),
    'platform': ('플랫폼', 'platform'),
    'browser': ('브라우저', 'browser'),
    'server': ('서버', '환경', 'server'),
    'urlPattern': ('적용url패턴', 'url패턴', '화면route', '화면경로', 'route', 'urlpattern'),
    'selector': ('요소선택자', '선택자', 'css선택자', 'selector', 'cssselector'),
    'kind': ('검사종류', '검증종류', '조건종류', 'kind', 'checkkind'),
    'expectedValue': ('자동기대값', '기대값', 'expectedvalue', 'automationexpected'),
    'attribute': ('속성이름', 'attribute'),
    'unit': ('길이단위', 'unit'),
    'enabled': ('활성', '사용여부', 'enabled'),
}


def _key(value):
    return ''.join(ch for ch in str(value or '').casefold() if ch.isalnum())


LOOKUP = {alias: field for field, aliases in ALIASES.items() for alias in aliases}


def _value(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value).strip()[:4000]


def _columns(row):
    result = {}
    for index, value in enumerate(row):
        field = LOOKUP.get(_key(value))
        if field and field not in result:
            result[field] = index
    return result


def _is_header(columns):
    return len(columns) >= 2 and bool({'caseId', 'title', 'checkTarget', 'expectedResult', 'selector'} & columns.keys())


def parse_workbook(blob):
    if not isinstance(blob, bytes) or not blob or len(blob) > 8_000_000:
        raise ValueError('엑셀 파일은 8MB 이하여야 합니다.')
    try:
        with ZipFile(BytesIO(blob)) as archive:
            if len(archive.infolist()) > 3000 or sum(info.file_size for info in archive.infolist()) > 50_000_000:
                raise ValueError('압축을 푼 엑셀 파일이 너무 큽니다.')
        workbook = load_workbook(BytesIO(blob), read_only=True, data_only=True)
    except (BadZipFile, OSError, KeyError, ValueError) as exc:
        if isinstance(exc, ValueError) and '너무 큽니다' in str(exc):
            raise
        raise ValueError('읽을 수 있는 .xlsx 파일을 선택해 주세요.') from exc
    cases = []
    sheets = []
    try:
        if len(workbook.worksheets) > 30:
            raise ValueError('시트는 최대 30개까지 가져올 수 있습니다.')
        for sheet in workbook.worksheets:
            header = None
            columns = {}
            sheet_count = 0
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if row_number > 5000:
                    raise ValueError('시트당 최대 5,000행까지 읽을 수 있습니다.')
                if header is None:
                    if row_number <= 30 and _is_header(_columns(row)):
                        header, columns = row_number, _columns(row)
                    continue
                if not any(value is not None and str(value).strip() for value in row):
                    continue
                if _is_header(_columns(row)):
                    continue
                case = {field: _value(row[index] if index < len(row) else None) for field, index in columns.items()}
                if not any(case.get(field) for field in ('caseId', 'title', 'checkTarget', 'steps', 'expectedResult', 'selector')):
                    continue
                case['sourceSheet'] = sheet.title
                case['sourceRow'] = row_number
                cases.append(case)
                sheet_count += 1
                if len(cases) > 2000:
                    raise ValueError('한 번에 최대 2,000개 테스트 케이스를 가져올 수 있습니다.')
            if sheet_count:
                sheets.append({'name': sheet.title, 'count': sheet_count, 'headerRow': header})
    finally:
        workbook.close()
    if not cases:
        raise ValueError('테스트 케이스 행을 찾지 못했습니다. TC ID·제목·판정기준 같은 열 이름을 확인하세요.')
    return {'cases': cases, 'sheets': sheets}
