# 실행·결과 계약 v2

기준일: 2026-11-03 KST. 현재 구현의 공동 인터페이스다. 목표 설계와 구현 범위는 [구현 현황](IMPLEMENTATION_STATUS.md), 운영은 [OPERATIONS](OPERATIONS.md)를 함께 본다. 기존 Python/Playwright/Pillow/순수 JS 구조를 유지한다.

## 검수 분류(Triage) 필드 (v2.3)

- `results[].triage = {bucket, reason, label, basis: [reason_code...], suggestedReview}` · `bucket ∈ ISSUE | HUMAN_CHECK | RETEST | OK | NOT_RUN`
- `totals.triage = {ISSUE, HUMAN_CHECK, RETEST, OK, NOT_RUN}`
- 읽을 때마다 `qa/triage.py`로 재계산하므로 저장된 값과 다를 수 있는 유일한 필드다. 자동 `status`·`review`는 바꾸지 않는다. 결정표는 [TRIAGE_POLICY](TRIAGE_POLICY.md).
- `manifest.login = {method: NONE|MANUAL|TEST_ACCOUNT, form: {...선택자} | null, credentialsStored: false}` — 계정 문자열은 어떤 필드에도 들어가지 않는다.

## 1. 실행 설정

HTTP API는 camelCase, 엔진 설정은 snake_case를 사용한다. 변환 경계는 `qa/config.py:parse_options/public_options` 한 곳이다.

| API 필드 | 내부 필드 | 계약 |
|---|---|---|
| testType | test_type | comparison / single / regression / conditional |
| mode | mode | combined / visual / discovery. 목적과 별도 |
| baselineUrl | baseline_url | 항상 검사할 A. http(s), 자격증명 포함 금지 |
| candidateUrl | candidate_url | comparison에서만 검사할 B. 다른 목적은 null이며 호스트 승인에도 포함하지 않음 |
| previousRunId | previous_run_id | regression의 저장된 종료 실행 UUID. 임의 파일 경로 불가 |
| operatorId | operator_id | 실행 책임자 이름. 인증 주체를 검증하는 기능은 아님 |
| conditions | conditions | 읽기 전용 조건 계약 배열. conditional에서 최소 1개 필수 |
| aliases / regions / safeActions | route_aliases / regions / safe_actions | 명시적 페이지 대응·영역·승인 click 설정 |
| allowedHosts / allowedPaths | allowed_hosts / allowed_paths | 정확한 host[:port]·제한된 상대 경로. 전역 /* 승인 금지 |
| scenarioIds | scenario_ids | 등록된 Python 시나리오 ID. 임의 코드 실행 없음 |
| pairStartPages | pair_start_pages | 비교 목적 기본 true. 입력한 두 시작 레코드만 같은 기능으로 지정. alias 우선, 나머지 route·query·hash identity 유지 |
| resourceHosts | resource_hosts | 별도 정적 CDN host[:port]. GET/HEAD script/stylesheet/image/font/media만 허용. 이동·API·쓰기 권한 없음 |
| baselineName / candidateName | baseline_name / candidate_name | 제품과 독립된 환경 별칭, 각 1~50자. 단일 환경 B는 null |
| baselineEnvironmentId / candidateEnvironmentId | baseline_environment_id / candidate_environment_id | 제품별 production/staging/vibe-dev/legacy-dev 또는 custom. ID-only는 등록 URL 선택, ID+다른 URL은 거부. 단일 환경 B는 null |
| crawlScope | crawl_scope | approved_paths(기존 기본) / same_origin_readonly(정확한 각 환경 origin의 조회 링크 확장). 알려진 위험 URL·행동 제외와 예산 유지 |

사용 가능한 프로필·기본값·testTypes는 `GET /api/bootstrap`에서 조회한다. POST는 같은 로컬 출처와 `X-QA-Token`이 필요하다. ID 기억은 브라우저 저장 기능이며 비밀번호·세션은 API에 받지 않는다.

v0.3.1부터 각 제품의 `environments[]`에 사용자 제공 4환경 URL을 제공한다. 기본 A는 운영, B는 STG이며 바이브/레거시 개발을 각각 선택할 수 있다. ID를 생략한 기존 요청은 실제 URL의 정확한 일치로 추론하고 일치하지 않으면 custom이다. 환경 이름은 사용자 별칭을 유지한다. 등록표와 제공 경로는 [ENVIRONMENT_URLS](ENVIRONMENT_URLS.md)가 기준이며, 목록을 읽는 것만으로 16개 호스트의 접근 권한을 부여하지 않는다.

v0.2.1의 시작 쌍 매칭은 `SELECTED_START_PAGES / START_URLS_DECLARED_EQUIVALENT`로 기록한다. 확신도는 설정한 대응 관계에 관한 것이며 실제 제품 동작을 보장하지 않는다. HTTP 요청에 fragment가 없으므로 시작 URL의 bootstrap document만 별도로 승인하고, 행동 후보의 hash route 검사는 계속 유지한다. 준비 조건·수집 오류·시각 차이는 매칭과 별도로 검사한다. discovery는 차이율 미계산이다.

규칙 버전은 `v2.1`이며 시작 쌍 옵션·정적 호스트 범위를 hash와 manifest에 기록한다. 기존 v2 실행과 정책이 달라지면 회귀 비교 가능성에서 차이를 표시한다. `JS_ERROR_AFTER_POLICY_BLOCK`/`CONSOLE_ERROR_AFTER_POLICY_BLOCK`는 TEST_INFRA/POLICY_INTERFERENCE, 원시 browser 메시지·출처·관련 차단 요청을 보존한다. `policyInterference`와 `policyRelation`은 원인 확정이나 제품 버그 확정이 아니다.

v0.3.1의 규칙 버전은 **v2.3**이다. v2.3은 `EQUIVALENT_ROUTE` 매칭 방법(`/`·`/#/`·`/main`·`.do`·끝 슬래시 접기, 확정 조건: 제목 일치 또는 `#/`만 다름)과 행별 `triage` 객체, `manifest.login`·`manifest.routeEquivalence`를 추가한다. v2.2의 규칙은 그대로 유지된다: `navigationTrail/pageSignature`와 전체 후보 관계를 통해 `SEMANTIC_CANDIDATE`를 제안하되 승인하지 않는다. alias/시작 쌍/정확 경로를 먼저 예약하며 후보 근거·모순·사용 가능 여부를 보존한다. `report.inventory`의 환경별 목록·방문/보류·매칭 후보와 `GET /api/scans/{id}/inventory.csv` 계약은 [ENVIRONMENT_DISCOVERY](ENVIRONMENT_DISCOVERY.md)에 기록한다. 일반 페이지 키는 query 순서·중복·percent encoding·hash를 그대로 보존하고 비밀 URL의 자동 alias는 비활성화한다.

## 2. 실행과 결과의 구분

저장 봉투(job)의 `schemaVersion`은 신규 `2.0`이다. 기존 1.x는 읽을 때 원래 판정과 검수를 유지한다. 지원하지 않는 major 버전은 오류다.

```text
job
 ├─ id, schemaVersion, state, progress, operatorId, profileId
 ├─ startedAt, finishedAt, error, authSide, options
 └─ report
     ├─ manifest: 버전·실행 조건·범위·브라우저·source hash
     ├─ coverage: 방문·미실행·요청 차단·미지원 범위
     ├─ totals: 행/검증식 상태와 서로 다른 집계 분모
     ├─ results[]: 페이지/영역별 검증식과 A/B 증거
     ├─ findings[]: 중복을 묶은 발견 사항과 원시 관찰 연결
     └─ regression?: 과거 실행 비교 가능성·발견 사항·행별 분류
```

job의 `done`은 worker가 결과를 반환했다는 뜻이다. 제품 품질 PASS나 검사 범위 전체 완료를 뜻하지 않는다. `manifest.status`는 COMPLETED/PARTIAL/CANCELLED이며 필수 BLOCKED/ERROR나 미실행이 있으면 PARTIAL이 된다. worker/저장 실패는 job ERROR로 기록한다. 사용자 취소와 시간 한도는 구분한다.

## 3. 검증식·대표 상태

검증식의 공통 필드:

```json
{
  "check_id": "a.condition.notice.empty",
  "environment": "a",
  "scenario_id": "conditions",
  "step_id": "notice.empty",
  "status": "PASS",
  "reason_code": "CONDITION_SATISFIED",
  "expected": true,
  "actual": true,
  "required": true,
  "evidence": []
}
```

- PASS: 명시된 검증식 실행·충족. 실제 수행하지 않은 기능을 정상으로 확대하지 않는다.
- FAIL: 준비된 조건에서 제품 계약 위반을 확인.
- DIFF: 승인된 매칭·준비 조건에서 화면 차이를 확인. 버그 확정과 별도.
- REVIEW: 매칭·준비·기대값·원인 등 판단 근거 부족.
- SKIP: 설정·범위·안전 정책에 따른 제외.
- BLOCKED: 인증·데이터·선행 검사·실행 한도로 수행 불가.
- ERROR: 수집기·선택자·브라우저·증거 처리 오류.

대표 배지 우선순위는 **FAIL → ERROR → 필수 BLOCKED → REVIEW → DIFF → 필수 SKIP → PASS**다. 실제 PASS가 없고 전부 제외되면 SKIP이다. `totals.checks`는 페이지/영역에 중복 표시한 검증식을 한 번씩 집계한다. 대표 배지와 전체 검증식 상태 분포를 함께 본다.

시각 차이율은 null과 0을 구분한다. 비교할 픽셀이 전부 마스킹되면 `BLOCKED/NO_COMPARABLE_PIXELS`다. 캡처 실패·이미지 손상·크기 불일치는 ERROR이며 0%로 치환하지 않는다. 매칭 또는 준비가 미확정이면 화면 차이를 DIFF로 확정하지 않는다.

## 4. 발견 사항·중복·집계

대분류는 HTTP/NETWORK/JAVASCRIPT/API/RESOURCE/NAVIGATION/STRUCTURE/FUNCTIONAL/VISUAL/DATA/AUTH/TEST_INFRA다. `qa/findings.py:classify`는 수집된 관찰·실행된 계약을 분류하며, 분류명만으로 탐지기를 생성하지 않는다. API 계약을 실행하지 않은 HTTP 500을 API 스키마 위반으로 확정하지 않는다.

발견 사항은 `id`, `fingerprint`, `assertionKey`, `environment`, `pageKey`, `checkId`, `scenarioId`, `stepId`, `category`, `subtype`, `severity`, `status`, `expected`, `actual`, `occurrenceCount`, `firstSeenAt`, `lastSeenAt`, `evidence`, `rowIds`, `tags`, `observations`를 가진다. 시간은 실제 관찰 시각을 사용하며 없는 과거 정보는 만들어내지 않는다.

fingerprint는 SHA256으로 다음 의미 정보를 정규 JSON 직렬화하여 만든다.

1. 환경 + 페이지 identity + 검증식 + 시나리오 + 단계 + 요청 대상.
2. 대표 category/subtype.
3. 관찰이 있으면 method/resource type/status/source 및 JS·network 메시지.

request ID는 원시 증거 연결·발생 횟수 중복 방지에 사용하며 실행 사이의 지문 identity로 쓰지 않는다. 행 인덱스를 영속적인 검증식 ID로 사용하지 않는다. 환경·페이지·검증 계약이 다르면 근거 없이 같은 원인으로 병합하지 않는다. 지문이 같은 발견 사항이 여러 결과 행에서 보일 수 있다.

| 집계 | 의미 |
|---|---|
| rawObservations | 페이지/영역의 동일 이벤트 복제를 제외한 관찰 횟수 |
| resultRows | 화면에 표시하는 결과 행 수. 기존 totals.pages도 이 의미 |
| uniqueFindings | 지문으로 묶은 발견 사항 수. 확정 버그 수가 아님 |
| linkedIssues | 현재 검수에 연결된 서로 다른 이슈 URL 수 |
| baselineVisited / candidateVisited | 실제 방문 페이지 수 |
| discovered/attempted/executed/blockedActions | 발견·시도·완료·안전 정책상 차단을 분리 |

## 5. 회귀 비교

`qa/regression.py:evaluate_regression(previous_report, current_report)`는 이미 불러온 두 보고서만 받는다. 파일·네트워크를 읽지 않는다. 신규 검사는 현재 A에서 실행하며 과거 A/B 쌍을 단일 환경과 같은 범위로 비교하지 않는다.

스키마 major, 대상 shape, ruleVersion/rulesHash, 프로필, 검사 모드, viewport, 시나리오·조건·매핑, 데이터 정책, 허용 범위와 캡처 조건이 비교 가능한지 먼저 확인한다. source hash·실행 ID·담당자·시각은 달라도 되며 정책·조건의 실제 차이는 숨기지 않는다.

| 분류 | 의미 |
|---|---|
| NEW | 비교 가능한 기존 증거에 없고 현재 새로 관찰됨. 제품 결함 신규 발생 확정과 별도 |
| RECURRING | 동일 지문의 발견 사항을 다시 관찰. 해결 후 재발까지 자동 확정하지 않음 |
| RESOLVED_CANDIDATE | 이전 발견 사항과 같은 검증식을 현재 명시적으로 실행하여 PASS. QA 재검 필요 |
| NOT_RETESTED | 현재 같은 검증식의 PASS 증거 없음. 사라졌다는 이유로 해결 처리 금지 |
| NON_COMPARABLE | 과거/현재 규칙·조건·범위가 다르거나 비교 근거 부족 |

과거 결과와 검수는 덮어쓰지 않는다. 회귀 분류는 자동 상태와 별도로 `report.regression`, 행의 `regression`에 기록한다. 과거 발견 사항만 있고 현재 대응 행이 없어도 전체 회귀 목록에 남는다. 기존 1.x 보고서는 판독 가능하지만 필수 비교 메타데이터가 없어 NON_COMPARABLE이다.

## 6. 조건 기반 UI 계약

`conditions`는 최대 30개, 각 `preconditions`는 최대 10개다. `kind`는 visible/count/text_length/overflow/attribute만 허용한다. 선택자·ID·지원하지 않는 필드를 검증하며 호출자가 JavaScript·action·mock 코드를 전달할 수 없다.

- visible/overflow: expected boolean. overflow는 scroll/client 크기의 계약 검사이며 모든 겹침·잘림 탐지와 다르다.
- count/text_length: expected `{equals,min,max}` 중 하나 이상. 길이 단위는 codepoints 또는 utf16.
- attribute: 승인된 표시용 속성에 한하여 expected 문자열/null/`{exists:boolean}`.
- case: custom/long_title/empty/pagination. custom 외에는 데이터 전제조건이 필수다.
- url_pattern: 현재 URL 또는 path에 대한 검사 범위. 범위 밖 SKIP, 전제 불충족 BLOCKED, 기대값 누락 REVIEW, 유효한 계약 불충족 FAIL, 선택자 오류 ERROR.

조건을 만들기 위해 운영 데이터를 쓰지 않는다. 별도 test fixture/mock 자동 주입은 현재 미지원이다.

## 7. 검수·이슈 연결

`POST /api/scans/{id}/reviews`:

```json
{
  "resultId": "현재 행의 id",
  "reviewer": "qa-b",
  "status": "BUG_CONFIRMED",
  "reason": "요구사항과 스크린샷으로 재현 확인",
  "expectedRevision": 0,
  "issueRef": "https://issues.example.invalid/QA-12"
}
```

검수 상태는 BUG_CONFIRMED/EXPECTED_DIFFERENCE/FALSE_POSITIVE/RETEST_REQUIRED/VERIFIED_OK다. 초기값은 UNREVIEWED다. 같은 revision의 경합은 한 요청만 저장하고 나머지는 HTTP 409다. issueRef 생략은 기존 연결 유지, 빈 문자열은 연결 해제다. 변경은 actor/reason/revision/timestamp/issueRef 이력에 남고 자동 status는 유지한다. 외부 이슈 조회·등록·해결은 하지 않는다.

## 8. 담당자별 변경 경계

| 담당 | 모듈 | 변경 시 필요한 공동 검토 |
|---|---|---|
| A: 핵심 엔진 | engine/policy/matching/comparison, app 실행 통합 | 상태 의미·예산·관찰·manifest·설정 계약 |
| B: 시나리오·검수 | scenarios/conditions, 제품별 selector·기대값, public, findings/regression 보고 | 실제 요구사항·증거·회귀 identity |
| 공동 | config/store/report_validation, 이 문서와 계약 테스트 | 스키마·마이그레이션·검수 충돌·민감 정보 |

새 수집기는 observation을, 새 제품 검사는 check를 생성한다. 새 UI는 저장된 상태를 다시 계산하지 않는다. 새 시나리오는 엔진 예산·허용 경로·환경 격리를 우회하지 않는다.
