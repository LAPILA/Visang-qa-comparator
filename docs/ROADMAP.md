# 구현 로드맵과 2인 협업 계획

> 이 문서는 최초 설계 단계의 계획을 보존합니다. **2026-11-03 v0.2의 실행 결과와 남은 범위는 [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md), 확정 2인 인터페이스는 [RESULT_CONTRACT](RESULT_CONTRACT.md), 실무 인수 순서는 [OPERATIONS](OPERATIONS.md)를 따릅니다.** 아래 “이번 작업은 문서만”·5상태·예정 파일들은 최초 감사 단계에 관한 설명입니다. 신규 결과는 7상태/스키마 2.0입니다.

작성일: 2026-10-30 (KST). **향후 개발 계획이며 이번 작업의 구현 결과가 아니다.** 이번에는 docs의 다섯 문서만 작성한다. 소스 이관·리팩터링·샘플 복사·커밋·푸시는 수행하지 않는다. 사용자가 커밋을 담당한다.

현 상태: 작업 저장소에는 기존 소스와 커밋이 없고, 분석한 Python Comparator는 Downloads의 별도 이전 버전이다. 경로·코드 근거·테스트 결과는 [AS_IS_ARCHITECTURE.md](AS_IS_ARCHITECTURE.md), 기능별 차이는 [REQUIREMENTS_AND_GAPS.md](REQUIREMENTS_AND_GAPS.md)에 있다. 아래 신규 파일 경로는 **예정 경로**이며 존재한다고 주장하지 않는다.

## 1. 구현 순서와 재사용 원칙

1. 승인된 이전 Comparator 소스만 선별 이관하고 동작 기준을 남긴다. `runs/`, 실제 대상 사이트 코드, 인증·로그·다운로드 자료를 복사하지 않는다.
2. 결과 계약과 잘못된 PASS부터 고친다. 관측 실패/미실행/제품 실패가 구분되어야 이후 개선 효과를 측정할 수 있다.
3. hash/별칭 매칭·안전 탐색·미탐색 이유를 먼저 고정한다. JS 버튼을 추가하기 전에 실행 정책을 둔다.
4. 좁은 시나리오와 region 단위 결과를 붙이고 QA가 증거를 검수할 수 있게 한다.
5. 합성 데모와 CI로 재현성을 입증한 뒤 4개 제품군·공유 검수·넓은 기능 범위로 확장한다.

기존 `OLD/app.py:199–231` BFS, `:124–153` 이벤트 listener, `:185–191` 캡처, `:234–257` Pillow overlay, `:345–349,396–412` CSV와 `OLD/tests/test_core.py:11–60`의 단위 테스트를 재사용한다. URL identity·판정·저장·시나리오 수명주기는 새 계약에 맞춰 점진 수정한다. React/Node 서버/분산 큐/AI runtime으로의 전면 변경을 전제하지 않는다.

## 2. 담당자와 파일 소유권

**담당 A = 사용자: 메인 핵심 기능과 실행 통합. 담당 B = 협업자: 사이트 어댑터·기능 TC·보고/검수와 검증 품질.** 개발 병렬성과 실제 QA 검수 역할은 별도로 기록한다.

| 영역 | 예정 파일·디렉터리 | 주 담당 | 다른 담당자의 계약/검토 |
|---|---|---|---|
| 기존 진입점·실행 통합 | `app.py`, `qa/runner.py`, `qa/job_service.py` | A | B가 API·cancel·상태 계약 검증 |
| 공통 모델·정책 | `qa/models.py`, `qa/policy.py`, `tests/contract/` | A 소유, B 승인 | schema version, 5상태, reason code 합의 |
| 안전 발견·페이지 매칭 | `qa/discovery.py`, `qa/actions.py`, `qa/matching.py` | A | B가 route/행동 fixture와 충돌 사례 제공 |
| 관찰·화면 비교 | `qa/collectors.py`, `qa/comparison.py`, `qa/evidence.py` | A | B가 데이터/region 명세와 정답 라벨 작성 |
| 인증 수명주기 | `qa/auth.py` | A | B가 수동 로그인·ID 기억·만료·격리 테스트 |
| 제품별 어댑터·정책 설정 | `qa/adapters/`, `config/profiles/`, `config/mappings/` | B | A가 allowlist/identity/timeout 계약 검토 |
| 기능 시나리오 | `qa/scenarios/`, `tests/scenarios/` | B | A가 runner hook·collector·cleanup 제공 |
| 보고 저장·export | `qa/reporting.py`, `qa/store.py` | B | A가 manifest/evidence contract·원자적 저장 검토 |
| Web UI·필터·QA 리뷰 | `public/app.js`, `public/index.html`, `public/styles.css` | B | A는 이 파일을 병렬 편집하지 않음 |
| 합성 데모·회귀·CI | `tests/fixtures/`, `tests/integration/`, `.github/workflows/qa.yml` | B | A가 코드 커버리지 누락·안전 trap 검토 |
| 문서·포트폴리오 근거 | `docs/`, 공개용 `examples/` | B 편집, A 최종 검토 | 내부 소스·실데이터 공개 여부 별도 확인 |

`OLD`는 이전 Comparator 경로이며 [AS_IS](AS_IS_ARCHITECTURE.md)의 경로 등록표를 따른다. 모듈 수가 개발 자체를 지연하면 처음에는 `app.py` adapter wrapper에서 출발해 테스트가 있는 경계부터 추출한다. 모든 예정 파일을 하루에 생성하는 것이 완료 기준은 아니다.

## 3. 병렬 개발을 위한 공통 인터페이스

[TEST_STRATEGY의 공통 계약](TEST_STRATEGY.md#7-결과-스키마-v1-초안--두-담당자의-공통-기준)을 단일 기준으로 삼는다. 특히 `RunManifest`, `PageIdentity`, `MatchResult`, `ActionCandidate`, `Observation`, `CheckResult`, `ReviewEvent`의 이름·필수 필드·상태 enum을 양쪽에서 다르게 만들지 않는다.

- A는 B에게 실제 사이트 대신 합성 `ScenarioContext`와 결과 JSON을 제공한다. B는 runner 미완성 상태에서도 시나리오/필터/검수 화면을 개발할 수 있다.
- B는 A에게 page class/region/ready/locator/승인 행동/기대값 TC를 제공한다. A가 제품 요구를 코드에서 임의로 추정하지 않는다.
- 시나리오는 `preconditions → execute(check 결과) → cleanup`이며 runner가 context·budget·cancel·collector·evidence를 소유한다.
- API 초안: `POST /api/scans`, `GET /api/scans/{id}`, `POST /api/scans/{id}/cancel`, `GET /api/scans/{id}/results`, `POST /api/results/{id}/reviews`, export endpoint. 현재 구현된 API는 AS_IS에서 별도로 구분한다. 필터는 결과 조회에만 적용한다.
- review 변경에는 `expected_revision`을 필수로 넣고 충돌 시 409를 반환한다. `operator_id` 텍스트는 로컬 담당자 라벨이지 인증 수단이 아니다.
- 모든 새 필드는 schema version과 fixture를 갱신한다. 기존 JSON의 0/null, unknown reason, missing evidence를 보존하는 계약 테스트를 둔다.

작업 브랜치 예: A `codex/core-matching`, B `codex/scenario-reporting`. 이번 감사에서는 만들지 않았다. PR당 한 책임 경계를 권장하며, shared model/API를 먼저 합의하고 각자 최신 기준을 반영한다. 상대 소유 파일 수정이 필요하면 PR을 나눠 통합 순서를 정한다.

## 4. 가장 먼저 할 개발 PR 3개

### PR-01 — 기준 소스 확보와 정직한 결과 계약

- 파일: 선별된 `app.py`, `public/`, 실행 스크립트, `requirements.txt`, `.gitignore`, 기존 `tests/test_core.py`; 신규 `qa/models.py`, `qa/policy.py`, `tests/contract/test_result_schema.py`, `tests/unit/test_status_policy.py`.
- A: 이전 소스의 hash·출처 기록, 엔트리포인트 유지, 비교 실패 PASS 제거, PASS/FAIL/REVIEW/SKIP/ERROR·reason 정의. 로컬 run/인증·ID 설정·임시 증거를 Git 제외 경로로 지정.
- B: 기존 테스트를 복구하고 null/오류/미실행/모든SKIP/FAIL+ERROR fixture와 CSV 0 보존 인수 항목 작성.
- 인수: 기존 5개 회귀 통과; 이미지 처리 실패·누락을 PASS로 만들지 않음; source/manifest/version 기록; 소스·민감 자료 유입 없음. 아직 live 신뢰성 확보를 선언하지 않는다.

### PR-02 — URL identity·명시 매칭과 통제된 발견

- 파일: `qa/matching.py`, `qa/discovery.py`, `qa/actions.py`, `config/mappings/demo.json`, `qa/adapters/demo.py`, `tests/unit/test_matching.py`, `tests/integration/test_safe_discovery.py`.
- A: hash 보존, profile별 query, 검수한 `.do` alias, root 인증 gate 방지, matching reason, budget/cancel/skip 기록.
- B: href 없는 안전 메뉴·더보기, 파괴적 GET/POST 함정, 다른 URL의 같은 화면과 같은 화면의 다른 기능을 담은 합성 데모·negative fixture 제공.
- 인수: `#/search`와 `#/notice` 분리; 승인 alias만 매칭; 충돌/미발견과 404 구분; unsafe/unknown 행동은 실행되지 않고 이유가 보임; 정해진 예산을 넘지 않음. 실사이트 “모든 링크 완료” 주장 금지.

### PR-03 — region·오류 정책·보존되는 결과와 조회 필터

- 파일: `qa/collectors.py`, `qa/comparison.py`, `qa/reporting.py`, `qa/store.py`, `public/app.js`, `tests/integration/test_report_lifecycle.py`, `tests/fixtures/dual_demo/`.
- A: HTTP origin/resource/step 수집, 오류와 수집기 ERROR 분리, `home.notice` region·동적 데이터 policy 연결.
- B: manifest/result JSON 저장, restart 조회·CSV, 차이율 수치/null 필터, 원시 상태를 유지하는 결과 UI, operator·검수 상태 기록 초안.
- 인수: 문서500/예상401/외부403/공지 데이터 차이를 각각 설명; “홈 > 공지” 근거 표시; 저장 후 재조회에 동일 ID·정책·증거가 연결됨; 조회 필터를 바꿔도 판정 불변.

세 PR의 작업량이 커지면 각각 source import/contract, matcher/safe discovery, collector/store/UI의 작은 PR로 쪼갠다. 우선순위 세 가지를 동시에 완성해야 하는 단일 거대 PR로 묶지 않는다.

## 5. 1주 MVP — 7일 작업 창, 2인 기준 초안

**일정은 추정 계획이며 실제 소요일·완료 보장이 아니다.** 설치·계정·제품 요구 확정이 지연되면 기능 수를 줄이고 안전/판정/재현 gate를 유지한다.

| 일차 | A: 핵심 기능 | B: TC·어댑터·보고 | 함께 확인할 산출물·인수 조건 |
|---|---|---|---|
| D1 | 소스 선별 이관, 실행 기준, schema/policy | 합성 데모·정답 라벨, region/TC 초안 | 5개 기존 회귀, 소스 버전, 계약 fixture. 인증·미확정 도메인 차단 목록 |
| D2 | URL/hash/query·alias matcher | UI 후보/오매칭/데이터차이 fixture, 결과 컴포넌트 | TC-01~04. hash 충돌 없음, alias 충돌 REVIEW |
| D3 | budget·cancel·action gate·이벤트 | 승인 메뉴/검색 adapter, TC 안전 trap | TC-05~07,09~12. 위험 변경 함정 미실행; 오류 출처 표시 |
| D4 | runner의 scenario context·수동 인증 경계 | 검색, 길이 경계, history 중 2~3개 정의/구현 | 명세 확정 시나리오만 PASS/FAIL; 비밀번호 미저장 |
| D5 | notice region·Pillow 비교·5상태 집계 | 결과 필터·CSV·JSON persistence·operator | TC-13~15,23~24,28. 비교 불가 PASS 없음, region 이슈 확인 |
| D6 | 통합 오류·복원·누락 수정 | 정상/결함/정상 데이터 차이 검수 | 선택 시나리오를 양 합성 환경에서 실행; 실패·skip 근거 모두 확인 |
| D7 | 릴리스 후보 실행·코드 검토 | 재현 README, 증거 bundle, CI 최소 pipeline | 깨끗한 환경 설치·로컬 데모 재실행, 미완료 범위와 측정표 기록 |

MVP 기능 시나리오 기본 선택은 **검색, 길이 경계, 목록→상세→뒤로가기/새로고침**이다. 실제 길이/복원 명세가 없으면 그 항목은 합성 데모에서만 검증하고 live는 REVIEW로 둔다. 팝업·다운로드는 안전 계약과 테스트 자료가 준비되면 교체/추가하고, 모든 기능을 1주 안에 넣지 않는다.

MVP 결과 사용 형태: 각자 로컬 인스턴스·개인 인증 context로 실행하고 operator가 붙은 비밀 제거 결과를 공유한다. 서로의 cookie/profile/password를 공유하지 않는다. 이 단계에서 인증 없는 서버를 LAN에 공개하지 않는다. 동일 프로세스의 한 활성 run 제한을 유지해도 되지만 대기/충돌을 명확히 표시한다.

### MVP 완료 gate

- 다른 URL 동일 기능을 검수한 매핑으로 묶고, hash route를 잃지 않는다.
- 발견/허용/실행/검증/차단/한도 누락을 별도 표시한다.
- region·시나리오·단계·check와 증거가 연결되고 자동 5상태가 작동한다.
- 공지 데이터 차이가 구조 결함을 숨기거나 전체 홈 버그로 오인되지 않는다.
- 2~3개 명세 기반 시나리오가 양 합성 환경에서 돌아가며 예상 성공·실패·미실행을 각각 검증한다.
- report와 실행 설정이 재시작 후 남고 reviewer/operator가 구분된다. 최소 수동 검수 기록이 있다.
- 깨끗한 설치와 합성 데모의 CI 실행을 재현한다. 성능/오탐 수치는 아직 측정하지 못하면 `미측정`으로 남긴다.

실사이트 계정·정책 승인 미확보는 데모 MVP를 막지 않는다. 대신 live 적용 완료라고 표기하지 않는다. 기존 source import/구조 추출이 지연되면 첫 주는 PC 한 프로필과 핵심 2개 시나리오로 축소한다.

## 6. 이후 단계와 종료 조건

| 단계 | 범위 | 인수 조건·측정 |
|---|---|---|
| 안정화 | rule version, narrow allowlist, 수집 누락·취소·세션 만료·retry | 모든 partial/error가 보존되고 반복 실행의 변동 원인이 분류됨 |
| 기능 QA 확장 | 정렬·페이지네이션·검색 없음·UI back·forward·팝업·다운로드 | 각 scenario에 기대값/전제/정리/위험등급; 독립 fixture와 negative test |
| 시각·데이터 정밀화 | component DOM/CSS/overflow, fixture/mock, threshold 보정 | 데이터만 변경한 정상 세트와 UI 결함 세트를 분리 평가; 가림 영역 구조 검사 |
| 4개 제품 적용 | PC 초등/중고등, 모바일 초등/중고등 adapter | 제품별 route/viewport/auth/host 명세; 초등모바일·중고등PC 소스/동작 별도 확인 |
| 2인 공유 검수 | SQLite 또는 검증된 저장 adapter, revision, 담당 큐, issue/retest 링크 | 재시작·동시 리뷰 충돌·이력 보존·접근 통제 테스트 |
| 포트폴리오 완성 | 공개 합성 데모, RTM, CI, 결함 주입·지표·ADR·재현 영상 | 회사 자료 없는 fresh clone에서 실행; 원시 실험결과로 요약 수치 재계산 가능 |

SQLite 도입은 표준 라이브러리와 로컬 규모를 고려한 후속 후보이지 이번 단계의 확정 리팩터링이 아니다. 공유 운영을 하기 전 인증·보존·백업/삭제·충돌 처리를 함께 검증한다. 다중 worker/원격 브라우저/대규모 crawl은 필요성이 측정된 이후 별도 ADR로 다룬다.

## 7. 검증·릴리스 방식

테스트 계층: 순수 함수/정책 unit → schema/adapter contract → 합성 브라우저 통합 → dual-site end-to-end → 선택적 승인 live smoke. CI의 기본 대상은 합성 데모이고 운영/STG 로그인은 기본 자동 실행하지 않는다. Python/Playwright/Pillow의 검증 버전과 Chromium revision을 기록하고, 의존성 갱신은 별도 PR로 비교한다.

PR 체크는 바뀐 위험을 검증하는 테스트로 한정한다. 구현을 그대로 복제한 테스트나 무의미한 100% 커버리지 목표를 만들지 않는다. URL 충돌, ERROR→PASS, unsafe 요청, null/0, review 충돌, artifact 연결 손실처럼 사용자가 신뢰를 잃는 경로를 우선한다.

검증 결과에는 실행 명령·환경·입력 버전·정답 라벨·성공/실패/누락·불안정성·artifact checksum을 남긴다. 포트폴리오에는 [TEST_STRATEGY의 지표 산식](TEST_STRATEGY.md#10-신뢰성-검증과-포트폴리오-지표)을 사용하고 분모 없는 탐지율, 임의의 시간 절감률을 싣지 않는다. 기존 테스트 5개 통과는 실제 운영 QA 신뢰성 검증 완료와 다르다.

## 8. 다음 구현 요청용 프롬프트

```text
docs/AS_IS_ARCHITECTURE.md, REQUIREMENTS_AND_GAPS.md, TEST_STRATEGY.md,
ROADMAP.md, DECISIONS_AND_OPEN_QUESTIONS.md를 먼저 읽어라.
이번에는 ROADMAP의 PR-01 범위만 구현한다.
Downloads의 이전 Comparator에서 필요한 소스를 선별 이관하되
실제 사이트 샘플/기존 runs/계정/쿠키/로그는 복사하지 않는다.
Python/Playwright/Pillow와 기존 UI를 유지하고 결과 스키마/5상태를 고정한다.
이미지 비교 실패·미실행을 PASS로 만들지 않으며 기존 5개 단위 테스트와
새 판정 계약 테스트를 안전한 로컬 환경에서 실행한다.
운영/STG 접속이나 로그인은 하지 말고, 변경·검증·남은 위험을 보고하라.
커밋과 푸시는 사용자가 하므로 실행하지 마라.
```

이 프롬프트는 후속 작업을 위한 예시이고 현재 구현을 시작하라는 지시가 아니다.
