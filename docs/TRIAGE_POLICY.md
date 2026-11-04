# 검수 분류(Triage) 정책 · 판정을 "할 일"로 바꾸는 규칙

기준일: 2026-11-04 · 규칙 버전 v2.3 · 구현 `qa/triage.py`

자동 판정 7상태(PASS/FAIL/DIFF/REVIEW/SKIP/BLOCKED/ERROR)는 **엔진이 무엇을 관찰했는지**를 말한다. 검수 분류는 그 위에 얹히는 **QA 담당자가 무엇을 해야 하는지**다. 자동 판정·검수 이력은 바꾸지 않고, 보고서를 읽을 때마다 결정적으로 다시 계산한다(과거 보고서에도 동일하게 적용).

## 1. 다섯 가지 분류

| 분류 | 의미 | 기본 행동 | 제안 검수 상태 |
|---|---|---|---|
| `ISSUE` 이슈 등록 후보 | 기능 미작동, 필수 영역·요소 누락, 페이지 자체가 4xx/5xx | 재현 확인 후 이슈 등록 | `BUG_CONFIRMED` |
| `HUMAN_CHECK` 대인체크 | DB·이미지 등 데이터 차이, 페이지 매핑 확인, 404·콘솔 오류가 있으나 페이지는 동작 | 사람이 눈으로 확인하고 정상 차이/오탐/버그 중 결정 | `VERIFIED_OK` |
| `RETEST` 재검 필요 | 로그인·권한, 테스트 데이터 전제, 예산 한도, 검사 도구 오류로 **검사하지 못함** | 조건을 갖춰 다시 실행 | `RETEST_REQUIRED` |
| `OK` 정상 | 실행한 검증식이 모두 통과 | 표본 확인 | `VERIFIED_OK` |
| `NOT_RUN` 미실행 | 정책·범위상 실행하지 않음 (판정 아님) | 범위 확대 여부 판단 | — |

제안 검수 상태는 검수 폼의 **기본 선택값**일 뿐이다. 저장은 검수자가 사유와 함께 직접 한다.

## 2. 결정표

행의 `status`와 각 검증식(`checks`)의 `reason_code`·발견 분류(`findings.classify`)로 결정한다. 위에서 아래로 첫 일치 규칙을 적용한다.

| 순서 | 조건 | 분류 | 사유 코드 |
|---|---|---|---|
| 1 | status = PASS | OK | `ALL_ASSERTIONS_PASSED` |
| 2 | status = SKIP | NOT_RUN | `NOT_EXECUTED` |
| 3 | BLOCKED/ERROR 이고 사유에 `LOGIN_REQUIRED`·`ACCESS_DENIED`·`SESSION_EXPIRED`·`LOGIN_FAILED`·`LOGIN_CREDENTIALS_MISSING` 등 인증 계열 | RETEST | `AUTH_REQUIRED` |
| 4 | BLOCKED 사유가 `MATCH_SIDE_UNAVAILABLE`/`REVIEW_MATCH`뿐 (상대 환경에 대응 페이지 없음) | HUMAN_CHECK | `MAPPING_REVIEW` |
| 5 | BLOCKED/ERROR 이고 `INSUFFICIENT_DATA`·`*PRECONDITION*`·`*PREREQUISITE*` | RETEST | `DATA_PRECONDITION` |
| 6 | 그 외 BLOCKED/ERROR (페이지·동작·시간 한도, 캡처·비교·탐색 오류) | RETEST | `BUDGET_OR_TOOL` |
| 7 | FAIL 이고 `DOCUMENT_HTTP_ERROR`·`NAVIGATION_ERROR` (페이지 자체 오류) | ISSUE | `PAGE_UNREACHABLE` |
| 8 | FAIL 검증식의 분류에 `FUNCTIONAL`·`STRUCTURE`·`NAVIGATION`·`API`·`AUTH`·`DATA` 포함 (시나리오 기대값 위반, 필수 영역 누락 등) | ISSUE | `FUNCTIONAL_CONTRACT_VIOLATED` |
| 9 | FAIL 검증식이 모두 `RESOURCE`·`HTTP`·`JAVASCRIPT`·`NETWORK`·`VISUAL`·`TEST_INFRA` 관찰이고 문서 응답(`*.document`)은 PASS — 이미지 404, 콘솔 오류, 서브 리소스 실패 | HUMAN_CHECK | `ERRORS_BUT_PAGE_WORKS` |
| 10 | 그 외 FAIL | ISSUE | `FUNCTIONAL_CONTRACT_VIOLATED` |
| 11 | status = DIFF (시각 차이 임계값 초과) | HUMAN_CHECK | `VISUAL_OR_DATA_DIFF` |
| 12 | REVIEW 사유에 `REVIEW_MATCH`·`NOT_DISCOVERED`·`MATCH_AMBIGUOUS` | HUMAN_CHECK | `MAPPING_REVIEW` |
| 13 | REVIEW 사유가 `ACTION_EXPECTATION_MISSING`뿐 | HUMAN_CHECK | `ACTION_WITHOUT_ASSERTION` |
| 14 | REVIEW 사유에 `HTTP_*`·`CONSOLE_*`·`JS_ERROR*`·`REQUEST_ABORTED` | HUMAN_CHECK | `ERRORS_BUT_PAGE_WORKS` |
| 15 | 그 외 REVIEW | HUMAN_CHECK | `EVIDENCE_INSUFFICIENT` |

### 왜 이렇게 나누나

- **DB(이미지·데이터) 차이는 버그가 아닐 확률이 높다.** 운영↔STG는 데이터가 다른 것이 정상이므로 시각 DIFF와 데이터 분류는 기본적으로 사람이 본다(11). 영역 마스크(`regions[].mask_selectors`)로 동적 데이터를 가리면 DIFF 자체가 줄어든다.
- **404·콘솔 오류가 떠도 페이지가 정상 동작하는 경우가 많다.** 문서 응답이 200이고 기능 검증식이 실패하지 않았으면 이슈로 바로 보내지 않고 대인체크로 둔다(9, 14). 반대로 페이지 자체가 500이면 바로 이슈 후보다(7).
- **기능 미작동은 이슈다.** 등록 시나리오(검색·입력·history)의 기대값 위반, 필수 영역 누락은 사람이 보지 않아도 이슈 후보다(8).
- **검사를 못 한 것은 버그도 정상도 아니다.** 로그인·데이터·예산 때문에 못 봤으면 재검이다(3, 5, 6). 검사 누락을 해결로 처리하지 않는다는 회귀 정책과 같은 원칙이다.

## 3. 보고서·CSV·UI 표현

- 행: `row.triage = {bucket, reason, label, basis[], suggestedReview}`; `basis`는 분류에 사용한 사유 코드(최대 12개).
- 합계: `totals.triage = {ISSUE, HUMAN_CHECK, RETEST, OK, NOT_RUN}`.
- CSV: `검수 분류`, `분류 사유` 열(자동 상태 다음).
- UI: 결과 대시보드 상단 5개 타일(클릭 = 필터), 결과 필터의 "검수 분류", 각 행의 배지, 상세의 분류 카드, 검수 폼 기본값.

## 4. 한계

- 분류는 검증식·관찰의 **사유 코드**에만 의존한다. 사유 코드가 없는 이전 형식(1.x) 보고서는 대부분 `EVIDENCE_INSUFFICIENT` 또는 `BUDGET_OR_TOOL`로 묶인다.
- "페이지는 동작"은 문서 응답 PASS + 기능 검증식 미실패라는 **근거 기준**이지, 사용자가 실제로 기능을 썼다는 뜻이 아니다. 그래서 OK가 아니라 대인체크다.
- 새 분류 규칙은 자동 판정을 바꾸지 않으므로 회귀 비교 가능성(`ruleVersion`)에는 영향이 없다. 단, 동등 라우트 매칭(v2.3)은 매칭 결과를 바꾸므로 v2.2 이전 실행과는 회귀 비교 불가로 표시된다.
