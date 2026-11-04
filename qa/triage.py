"""Review triage: turn the 7 automatic statuses into four operator buckets.

The automatic status (PASS/FAIL/DIFF/REVIEW/SKIP/BLOCKED/ERROR) says what the
engine *observed*. Triage says what a QA operator should *do* with the row:

======================  =====================================================
Bucket                  Meaning / default operator action
======================  =====================================================
``ISSUE``               기능 미작동·필수 요소 누락·페이지 자체 오류 → 이슈 등록 후보
``HUMAN_CHECK``         대인체크: DB/이미지 데이터 차이, 매핑 확인, 404·콘솔 오류가
                        있어도 페이지는 동작하는 경우 → 사람이 눈으로 확인
``RETEST``              로그인·데이터·예산·도구 오류로 검사하지 못함 → 조건 갖춰 재검
``OK``                  실행한 검증식이 모두 통과
``NOT_RUN``             정책·범위상 실행하지 않음 (판정 아님)
======================  =====================================================

Triage is derived deterministically from the row's own checks and findings
taxonomy, is recomputed on every read (so legacy reports also get it) and
never changes ``row['status']`` or review data. It is a *suggestion*: the
reviewer's recorded decision always wins.
"""
from __future__ import annotations

from .findings import classify

BUCKETS = ('ISSUE', 'HUMAN_CHECK', 'RETEST', 'OK', 'NOT_RUN')

# Categories whose FAIL means the product contract itself is broken.
_CONTRACT_CATEGORIES = frozenset({'FUNCTIONAL', 'STRUCTURE', 'NAVIGATION', 'API', 'AUTH', 'DATA'})
# Categories whose FAIL is an *observation* that may or may not break the page.
_OBSERVATION_CATEGORIES = frozenset({'RESOURCE', 'HTTP', 'JAVASCRIPT', 'NETWORK', 'VISUAL', 'TEST_INFRA'})
_AUTH_REASONS = frozenset({'LOGIN_REQUIRED', 'ACCESS_DENIED', 'SESSION_EXPIRED', 'ROLE_UNAVAILABLE',
                           'MANUAL_AUTH_REQUIRED', 'LOGIN_FAILED', 'LOGIN_CREDENTIALS_MISSING',
                           'LOGIN_HOST_NOT_APPROVED', 'AUTH_TIME_LIMIT_REACHED'})
_DATA_REASONS = frozenset({'INSUFFICIENT_DATA', 'PRECONDITION_FAILED', 'REGION_PREREQUISITE_FAILED'})
_PAGE_LEVEL_REASONS = frozenset({'DOCUMENT_HTTP_ERROR', 'NAVIGATION_ERROR'})

SUGGESTED_REVIEW = {
    'ISSUE': 'BUG_CONFIRMED', 'HUMAN_CHECK': 'VERIFIED_OK', 'RETEST': 'RETEST_REQUIRED',
    'OK': 'VERIFIED_OK', 'NOT_RUN': None,
}

REASON_LABELS = {
    'PAGE_UNREACHABLE': '페이지 자체가 오류 응답',
    'FUNCTIONAL_CONTRACT_VIOLATED': '기능·구조 기대값 위반',
    'ERRORS_BUT_PAGE_WORKS': '오류 관찰됨 · 페이지는 동작',
    'VISUAL_OR_DATA_DIFF': '화면·데이터(DB/이미지) 차이',
    'MAPPING_REVIEW': '페이지 매핑 확인 필요',
    'ACTION_WITHOUT_ASSERTION': '동작 실행 · 기대값 미등록',
    'EVIDENCE_INSUFFICIENT': '판단 근거 부족',
    'AUTH_REQUIRED': '로그인·권한 필요',
    'DATA_PRECONDITION': '테스트 데이터 전제 미충족',
    'BUDGET_OR_TOOL': '한도 초과·검사 도구 오류',
    'ALL_ASSERTIONS_PASSED': '실행한 검증식 모두 통과',
    'NOT_EXECUTED': '정책·범위상 미실행',
}


def _check_category(item):
    try:
        return classify(item, item.get('observation') or {})[0]
    except Exception:  # classification is best-effort; triage must never raise
        return 'TEST_INFRA'


def _reason(item):
    return str(item.get('reason_code') or (item.get('observation') or {}).get('category') or '').upper()


def _document_reachable(checks):
    docs = [c for c in checks if str(c.get('check_id', '')).endswith('.document')]
    return bool(docs) and all(c.get('status') == 'PASS' for c in docs)


def triage_row(row):
    """Return {'bucket', 'reason', 'label', 'basis', 'suggestedReview'} for one result row."""
    status = row.get('status')
    checks = [c for c in row.get('checks', []) if isinstance(c, dict)]
    basis = []

    def result(bucket, reason):
        return {'bucket': bucket, 'reason': reason, 'label': REASON_LABELS.get(reason, reason),
                'basis': basis[:12], 'suggestedReview': SUGGESTED_REVIEW[bucket]}

    if status == 'PASS':
        return result('OK', 'ALL_ASSERTIONS_PASSED')
    if status == 'SKIP':
        return result('NOT_RUN', 'NOT_EXECUTED')
    if status in ('BLOCKED', 'ERROR'):
        reasons = {_reason(c) for c in checks if c.get('status') in ('BLOCKED', 'ERROR')}
        basis.extend(sorted(reasons))
        if reasons & _AUTH_REASONS:
            return result('RETEST', 'AUTH_REQUIRED')
        if reasons <= {'MATCH_SIDE_UNAVAILABLE', 'REVIEW_MATCH'} and reasons:
            # The region could not be compared because the other environment has
            # no approved counterpart: a mapping decision, not a tooling failure.
            return result('HUMAN_CHECK', 'MAPPING_REVIEW')
        if reasons & _DATA_REASONS or any('PREREQUISITE' in r or 'PRECONDITION' in r for r in reasons):
            return result('RETEST', 'DATA_PRECONDITION')
        return result('RETEST', 'BUDGET_OR_TOOL')
    if status == 'FAIL':
        failing = [c for c in checks if c.get('status') == 'FAIL']
        reasons = {_reason(c) for c in failing}
        basis.extend(sorted(reasons))
        if reasons & _PAGE_LEVEL_REASONS:
            return result('ISSUE', 'PAGE_UNREACHABLE')
        categories = {_check_category(c) for c in failing}
        if categories & _CONTRACT_CATEGORIES:
            return result('ISSUE', 'FUNCTIONAL_CONTRACT_VIOLATED')
        if categories <= _OBSERVATION_CATEGORIES and _document_reachable(checks):
            # 404 on an image, a console error, a sub-resource failure: the page
            # itself answered and no functional contract failed → a person decides.
            return result('HUMAN_CHECK', 'ERRORS_BUT_PAGE_WORKS')
        return result('ISSUE', 'FUNCTIONAL_CONTRACT_VIOLATED')
    if status == 'DIFF':
        basis.extend(sorted({_reason(c) for c in checks if c.get('status') == 'DIFF'}))
        return result('HUMAN_CHECK', 'VISUAL_OR_DATA_DIFF')
    # REVIEW
    reasons = {_reason(c) for c in checks if c.get('status') == 'REVIEW'}
    basis.extend(sorted(reasons))
    if reasons & {'REVIEW_MATCH', 'NOT_DISCOVERED', 'MATCH_AMBIGUOUS'}:
        return result('HUMAN_CHECK', 'MAPPING_REVIEW')
    if reasons & {'ACTION_EXPECTATION_MISSING'} and len(reasons) == 1:
        return result('HUMAN_CHECK', 'ACTION_WITHOUT_ASSERTION')
    if any(r.startswith('HTTP') or 'CONSOLE' in r or 'JS_ERROR' in r or 'REQUEST_ABORTED' in r for r in reasons):
        return result('HUMAN_CHECK', 'ERRORS_BUT_PAGE_WORKS')
    return result('HUMAN_CHECK', 'EVIDENCE_INSUFFICIENT')


def apply_triage(report):
    """Attach ``row['triage']`` and ``totals['triage']`` in place; returns the report."""
    rows = report.get('results') or []
    counts = {bucket: 0 for bucket in BUCKETS}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row['triage'] = triage_row(row)
        counts[row['triage']['bucket']] += 1
    report.setdefault('totals', {})['triage'] = counts
    return report
