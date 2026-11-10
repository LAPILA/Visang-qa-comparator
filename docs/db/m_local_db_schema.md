# 로컬 QA DB 스키마 초안 (PostgreSQL)

> **현재 앱 연결 상태 (v0.5.0):** 이 문서의 `projects`·`project_environments` 두 테이블(+`login_url`·`login_id`·`password_ciphertext` 열)은 `qa/projects_db.py`가 **PostgreSQL 저장소로 실제 사용**한다. `.env`(또는 환경변수)에 `PGHOST`·`PGPORT`·`PGDATABASE`·`PGUSER`·`PGPASSWORD`가 모두 있고 `psycopg`가 설치되어 있으면 PostgreSQL을, 아니면 설정 없이 `local-settings/projects.json`(git 제외) 파일 저장소를 쓴다. 두 저장소는 같은 API(`/api/projects`)·같은 검증·같은 암호화(Fernet, `QA_CREDENTIAL_KEY`)를 쓴다. 나머지 테이블(runs·results·reviews 등)은 아직 앱에 연결되지 않은 초안이다.

이 문서는 각 담당자가 **동일한 로컬 DB 구조**를 만들기 위한 PostgreSQL 16 이상 DDL 초안이다. 현재 앱은 `runs/<run-id>/report.json`과 PNG, 프로젝트 설정은 브라우저 `localStorage`를 사용한다. 아래 SQL은 아직 앱에 연결된 운영 스키마나 기존 JSON의 자동 마이그레이션이 아니다. DB와 증거 파일은 각자 관리하고, 서로 공유할 때는 스키마 버전·내보낸 시점·민감 정보 제거 여부를 함께 기록한다.

기준: `docs/RESULT_CONTRACT.md`의 job/report 2.0, `docs/TEST_STRATEGY.md`의 실행·증거·검수 구분, `docs/ENVIRONMENT_DISCOVERY.md`의 환경별 탐색, 현재 프로젝트 설정 화면의 프로젝트당 복수 환경. 시간은 UTC ISO 8601 문자열, boolean은 0/1, 확장 구조는 JSON 텍스트로 저장한다. `IS JSON` 검사에는 PostgreSQL 16 이상이 필요하다. JSON 컬럼의 내용도 저장 전에 비밀 제거가 필요하다. URL에 계정 정보·인증 query를 넣지 않는다.

## 생성 SQL

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 60),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_environments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 50),
    start_url TEXT NOT NULL CHECK (length(start_url) BETWEEN 8 AND 2000),
    sort_order INTEGER NOT NULL CHECK (sort_order >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_project_environments_project ON project_environments(project_id);

CREATE TABLE IF NOT EXISTS project_rules (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
    rule_key TEXT NOT NULL CHECK (length(rule_key) BETWEEN 1 AND 100),
    condition_json TEXT NOT NULL CHECK ((condition_json IS JSON)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, rule_key)
);
CREATE INDEX IF NOT EXISTS idx_project_rules_project ON project_rules(project_id, enabled);

-- 실행 시점의 옵션과 대상 환경을 복사해 둔다. 프로젝트를 수정해도 과거 실행은 바뀌지 않는다.
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    schema_version TEXT NOT NULL DEFAULT '2.0',
    operator_id TEXT NOT NULL CHECK (length(trim(operator_id)) BETWEEN 1 AND 50),
    profile_id TEXT NOT NULL,
    test_type TEXT NOT NULL CHECK (test_type IN ('comparison','single','regression','conditional')),
    mode TEXT NOT NULL CHECK (mode IN ('combined','visual','discovery')),
    state TEXT NOT NULL CHECK (state IN ('running','awaiting_auth','done','cancelled','error')),
    report_status TEXT CHECK (report_status IN ('COMPLETED','PARTIAL','CANCELLED')),
    previous_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    progress_text TEXT,
    error_code TEXT,
    auth_side TEXT CHECK (auth_side IN ('a','b') OR auth_side IS NULL),
    options_json TEXT NOT NULL CHECK ((options_json IS JSON)),
    manifest_json TEXT CHECK (manifest_json IS NULL OR (manifest_json IS JSON)),
    coverage_json TEXT CHECK (coverage_json IS NULL OR (coverage_json IS JSON)),
    totals_json TEXT CHECK (totals_json IS NULL OR (totals_json IS JSON))
);
CREATE INDEX IF NOT EXISTS idx_runs_project_started ON runs(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_state_started ON runs(state, started_at DESC);

CREATE TABLE IF NOT EXISTS run_environments (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    project_environment_id TEXT REFERENCES project_environments(id) ON DELETE SET NULL,
    side TEXT NOT NULL CHECK (side IN ('a','b')),
    name TEXT NOT NULL,
    start_url TEXT NOT NULL,
    final_url TEXT,
    environment_registry_id TEXT,
    UNIQUE (run_id, side)
);

-- 실행 시점에 실제 적용한 규칙 사본. 프로젝트 규칙이 수정·삭제되어도 실행 근거를 보존한다.
CREATE TABLE IF NOT EXISTS run_rules (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_rule_id TEXT REFERENCES project_rules(id) ON DELETE SET NULL,
    rule_key TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    condition_json TEXT NOT NULL CHECK ((condition_json IS JSON)),
    source_updated_at TEXT,
    applied_at TEXT NOT NULL,
    UNIQUE (run_id, rule_key)
);
CREATE INDEX IF NOT EXISTS idx_run_rules_run ON run_rules(run_id);

-- 발견된 페이지와 실제 방문 여부는 별도 상태로 보존한다.
CREATE TABLE IF NOT EXISTS crawl_nodes (
    id TEXT PRIMARY KEY,
    run_environment_id TEXT NOT NULL REFERENCES run_environments(id) ON DELETE CASCADE,
    page_key TEXT NOT NULL,
    requested_url TEXT NOT NULL,
    final_url TEXT,
    title TEXT,
    navigation_trail_json TEXT CHECK (navigation_trail_json IS NULL OR (navigation_trail_json IS JSON)),
    page_signature_json TEXT CHECK (page_signature_json IS NULL OR (page_signature_json IS JSON)),
    discovered_from_id TEXT REFERENCES crawl_nodes(id) ON DELETE SET NULL,
    visit_state TEXT NOT NULL CHECK (visit_state IN ('DISCOVERED','VISITED','DEFERRED','BLOCKED','ERROR')),
    not_executed_reason TEXT,
    http_status INTEGER,
    discovered_at TEXT,
    visited_at TEXT,
    UNIQUE (run_environment_id, page_key)
);
CREATE INDEX IF NOT EXISTS idx_crawl_nodes_run_environment ON crawl_nodes(run_environment_id, visit_state);

CREATE TABLE IF NOT EXISTS page_matches (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    a_node_id TEXT REFERENCES crawl_nodes(id) ON DELETE SET NULL,
    b_node_id TEXT REFERENCES crawl_nodes(id) ON DELETE SET NULL,
    method TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVED','CANDIDATE','REJECTED','UNMATCHED')),
    reason_json TEXT NOT NULL CHECK ((reason_json IS JSON)),
    mapping_version TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    CHECK (a_node_id IS NOT NULL OR b_node_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_page_matches_run ON page_matches(run_id, decision);

CREATE TABLE IF NOT EXISTS action_candidates (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    crawl_node_id TEXT REFERENCES crawl_nodes(id) ON DELETE SET NULL,
    element_signature TEXT,
    action_kind TEXT,
    risk TEXT,
    policy_rule TEXT,
    state TEXT NOT NULL CHECK (state IN ('DISCOVERED','ALLOWED','ATTEMPTED','EXECUTED','BLOCKED','SKIPPED')),
    reason_code TEXT,
    discovered_at TEXT,
    executed_at TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    run_environment_id TEXT REFERENCES run_environments(id) ON DELETE SET NULL,
    crawl_node_id TEXT REFERENCES crawl_nodes(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    category TEXT,
    subtype TEXT,
    source_url TEXT,
    http_status INTEGER,
    message TEXT,
    occurred_at TEXT,
    details_json TEXT CHECK (details_json IS NULL OR (details_json IS JSON))
);
CREATE INDEX IF NOT EXISTS idx_observations_run_kind ON observations(run_id, kind);

-- 결과 행의 자동 판정은 QA 검수 상태와 분리한다.
CREATE TABLE IF NOT EXISTS result_rows (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    page_key TEXT NOT NULL,
    page_match_id TEXT REFERENCES page_matches(id) ON DELETE SET NULL,
    region_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('PASS','FAIL','DIFF','SKIP','BLOCKED','ERROR','REVIEW')),
    reason_code TEXT,
    severity TEXT CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW','NONE') OR severity IS NULL),
    category TEXT,
    subtype TEXT,
    visual_difference_percent DOUBLE PRECISION CHECK (visual_difference_percent BETWEEN 0 AND 100 OR visual_difference_percent IS NULL),
    visual_unavailable_reason TEXT,
    baseline_url TEXT,
    candidate_url TEXT,
    regression_classification TEXT CHECK (regression_classification IN ('NEW','RECURRING','RESOLVED_CANDIDATE','NOT_RETESTED','NON_COMPARABLE','NOT_EVALUATED') OR regression_classification IS NULL),
    detail_json TEXT CHECK (detail_json IS NULL OR (detail_json IS JSON))
);
CREATE INDEX IF NOT EXISTS idx_result_rows_run_status ON result_rows(run_id, status);

CREATE TABLE IF NOT EXISTS checks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    result_row_id TEXT REFERENCES result_rows(id) ON DELETE SET NULL,
    check_id TEXT NOT NULL,
    environment_side TEXT CHECK (environment_side IN ('a','b','comparison') OR environment_side IS NULL),
    scenario_id TEXT,
    step_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('PASS','FAIL','DIFF','SKIP','BLOCKED','ERROR','REVIEW')),
    reason_code TEXT,
    required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    expected_json TEXT CHECK (expected_json IS NULL OR (expected_json IS JSON)),
    actual_json TEXT CHECK (actual_json IS NULL OR (actual_json IS JSON)),
    preconditions_json TEXT CHECK (preconditions_json IS NULL OR (preconditions_json IS JSON)),
    observed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_run_status ON checks(run_id, status);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    assertion_key TEXT,
    environment_side TEXT,
    page_key TEXT,
    check_id TEXT,
    scenario_id TEXT,
    step_id TEXT,
    category TEXT NOT NULL,
    subtype TEXT,
    severity TEXT,
    status TEXT NOT NULL CHECK (status IN ('PASS','FAIL','DIFF','SKIP','BLOCKED','ERROR','REVIEW')),
    expected_json TEXT CHECK (expected_json IS NULL OR (expected_json IS JSON)),
    actual_json TEXT CHECK (actual_json IS NULL OR (actual_json IS JSON)),
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
    first_seen_at TEXT,
    last_seen_at TEXT,
    tags_json TEXT CHECK (tags_json IS NULL OR (tags_json IS JSON)),
    UNIQUE (run_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_findings_run_category ON findings(run_id, category, subtype);

CREATE TABLE IF NOT EXISTS finding_rows (
    finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    result_row_id TEXT NOT NULL REFERENCES result_rows(id) ON DELETE CASCADE,
    PRIMARY KEY (finding_id, result_row_id)
);

CREATE TABLE IF NOT EXISTS finding_observations (
    finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    PRIMARY KEY (finding_id, observation_id)
);

-- PNG/JSON 등 실제 파일은 DB 밖에 두고 상대 경로와 해시를 저장한다.
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    result_row_id TEXT REFERENCES result_rows(id) ON DELETE SET NULL,
    check_record_id TEXT REFERENCES checks(id) ON DELETE SET NULL,
    finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
    observation_id TEXT REFERENCES observations(id) ON DELETE SET NULL,
    environment_side TEXT CHECK (environment_side IN ('a','b','comparison') OR environment_side IS NULL),
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    sha256 TEXT,
    captured_at TEXT,
    redacted INTEGER NOT NULL DEFAULT 0 CHECK (redacted IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence(run_id);

CREATE TABLE IF NOT EXISTS review_state (
    result_row_id TEXT PRIMARY KEY REFERENCES result_rows(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (status IN ('UNREVIEWED','BUG_CONFIRMED','EXPECTED_DIFFERENCE','FALSE_POSITIVE','RETEST_REQUIRED','VERIFIED_OK')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    issue_ref TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS review_events (
    id TEXT PRIMARY KEY,
    result_row_id TEXT NOT NULL REFERENCES result_rows(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    reviewer_id TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL CHECK (new_status IN ('BUG_CONFIRMED','EXPECTED_DIFFERENCE','FALSE_POSITIVE','RETEST_REQUIRED','VERIFIED_OK')),
    reason TEXT NOT NULL,
    issue_ref TEXT,
    retest_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE (result_row_id, revision)
);

CREATE TABLE IF NOT EXISTS regression_evaluations (
    id TEXT PRIMARY KEY,
    current_run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    previous_run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    comparable INTEGER NOT NULL CHECK (comparable IN (0,1)),
    reasons_json TEXT NOT NULL CHECK ((reasons_json IS JSON)),
    evaluated_at TEXT NOT NULL,
    UNIQUE (current_run_id, previous_run_id)
);

CREATE TABLE IF NOT EXISTS regression_items (
    id TEXT PRIMARY KEY,
    evaluation_id TEXT NOT NULL REFERENCES regression_evaluations(id) ON DELETE CASCADE,
    current_finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
    previous_finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
    current_result_row_id TEXT REFERENCES result_rows(id) ON DELETE SET NULL,
    classification TEXT NOT NULL CHECK (classification IN ('NEW','RECURRING','RESOLVED_CANDIDATE','NOT_RETESTED','NON_COMPARABLE')),
    reason_json TEXT CHECK (reason_json IS NULL OR (reason_json IS JSON)),
    CHECK (current_finding_id IS NOT NULL OR previous_finding_id IS NOT NULL OR current_result_row_id IS NOT NULL)
);

INSERT INTO schema_migrations (version, applied_at)
VALUES ('m_local_db_schema_v1', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')) ON CONFLICT (version) DO NOTHING;
INSERT INTO schema_migrations (version, applied_at)
VALUES ('m_local_db_schema_v2_rules', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')) ON CONFLICT (version) DO NOTHING;
INSERT INTO schema_migrations (version, applied_at)
VALUES ('m_local_db_schema_v3_run_rules', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')) ON CONFLICT (version) DO NOTHING;

COMMIT;
```

## 테이블·컬럼 정의

아래 정의는 위 SQL의 컬럼 주석 역할을 한다. `*_json`은 PostgreSQL `TEXT`에 JSON으로 저장하며, 기록 전에 민감 정보를 제거한다. `id`는 해당 행의 UUID, `*_id`는 이름으로 가리키는 테이블의 ID다. `created_at`·`updated_at`·`started_at`·`finished_at`·`occurred_at`·`applied_at` 등 `*_at`은 UTC ISO 8601 시각이다. `NULL`은 해당 값이 없거나 아직 확정되지 않았다는 뜻이며, 0·빈 문자열·PASS로 바꾸지 않는다.

### 설정과 실행

- **`schema_migrations`**: `version` — 적용한 스키마 변경의 고유 이름; `applied_at` — 적용 시각.
- **`projects`**: `id` — 프로젝트 UUID; `name` — 프로젝트 표시명; `created_at` — 최초 등록 시각; `updated_at` — 마지막 수정 시각.
- **`project_environments`**: `id` — 환경 UUID; `project_id` — 소속 프로젝트; `name` — 환경 표시명; `start_url` — 해당 환경의 시작 주소; `sort_order` — 프로젝트 화면의 환경 순서; `created_at` — 등록 시각; `updated_at` — 수정 시각. 환경은 프로젝트당 여러 개이며 실행마다 필요한 A/B만 고른다.
- **`project_rules`**: `id` — 규칙 UUID; `project_id` — 소속 프로젝트; `name` — 사람이 읽는 규칙 이름; `rule_key` — 프로젝트 안에서 유일한 조건 ID(`condition.id`); `condition_json` — 자동 실행 조건(`condition`), 사람이 수정할 테스트 케이스 내용(`caseData`), 자동 실행 가능 여부(`automationReady`), 엑셀 출처(`source`)를 담은 JSON 객체. 자동 실행 조건은 `qa/conditions.py` 계약을 따른다; `enabled` — 활성 여부(1/0); `created_at` — 등록 시각; `updated_at` — 수정 시각. 활성화만으로 과거 결과를 다시 판정하지 않는다.
- **`runs`**: `id` — 실행 UUID; `project_id` — 선택 프로젝트(프로젝트 없이 직접 실행 시 NULL); `schema_version` — 저장 결과 형식 버전(현재 2.0); `operator_id` — 실행 때 입력한 담당자 ID, 인증 계정이 아님; `profile_id` — 엔진의 제품/검사 프로필 ID, 프로젝트 ID와 다름; `test_type` — 환경 비교·단일·회귀·조건 UI 목적; `mode` — 통합·시각·탐색 검사 구성; `state` — worker의 실행/로그인 대기/종료/중단/오류 상태; `report_status` — 검사 범위의 완료/부분/취소 상태; `previous_run_id` — 회귀 비교 기준 실행; `started_at` — 시작 시각; `finished_at` — 종료 시각; `progress_text` — 진행 메시지; `error_code` — worker·저장 오류 코드; `auth_side` — 수동 로그인 대기 중인 A/B; `options_json` — 실제 실행 설정 사본(한도, 허용 경로·호스트, 별칭, 영역, 시나리오, 조건, 마스크 등); `manifest_json` — 도구·규칙·범위·캡처 버전과 hash; `coverage_json` — 방문·차단·미실행 범위; `totals_json` — 상태별 행/검증식 및 고유 발견 사항 등의 서로 다른 집계. `state=done`은 품질 PASS가 아니다.
- **`run_environments`**: `id` — 실행 대상 환경 UUID; `run_id` — 소속 실행; `project_environment_id` — 선택한 등록 환경(직접 입력 시 NULL); `side` — 실행 내 역할 A/B; `name` — 실행 당시 환경 이름 사본; `start_url` — 실행 당시 시작 URL 사본; `final_url` — 이동 후 최종 URL; `environment_registry_id` — 엔진 제공 환경 ID(production/staging/vibe-dev/legacy-dev/custom). 프로젝트의 환경 UUID를 엔진 등록 ID와 혼동하지 않는다.
- **`run_rules`**: `id` — 적용 규칙 사본 UUID; `run_id` — 소속 실행; `source_rule_id` — 원래 프로젝트 규칙(삭제 후 NULL 가능); `rule_key` — 실행 시점 조건 ID; `rule_name` — 실행 시점 표시명; `condition_json` — 실제 실행에 전달된 조건 사본; `source_updated_at` — 원 규칙의 당시 수정 시각; `applied_at` — 실행 설정에 확정한 시각. `checks.check_id` 또는 조건 ID를 통해 실행 결과와 대조한다.

### 탐색·판정·증거

- **`crawl_nodes`**: `id` — 발견 페이지 노드 UUID; `run_environment_id` — 어느 실행 환경에서 발견했는지; `page_key` — query/hash를 보존한 페이지 identity; `requested_url` — 방문 요청 URL; `final_url` — 이동 후 URL; `title` — 페이지 제목; `navigation_trail_json` — 메뉴/링크 발견 경로; `page_signature_json` — 메뉴·heading·폼 등 제한된 구조 특징; `discovered_from_id` — 이 페이지를 발견한 부모 노드; `visit_state` — 발견/방문/보류/차단/오류 상태; `not_executed_reason` — 방문하지 못한 이유; `http_status` — 실제 받은 HTTP 상태; `discovered_at` — 발견 시각; `visited_at` — 방문 시각. 발견만 된 노드를 검증 완료로 보지 않는다.
- **`page_matches`**: `id` — A/B 대응 관계 UUID; `run_id` — 소속 실행; `a_node_id`·`b_node_id` — 각 환경의 페이지 노드; `method` — 명시 alias·시작 쌍·정확 route·기능 후보 등 매칭 방식; `decision` — 승인/후보/거절/미매칭; `reason_json` — 일치·모순 근거; `mapping_version` — 적용 매핑 버전; `reviewed_by` — 대응 관계 검토자; `reviewed_at` — 검토 시각. 후보를 승인된 동일 기능으로 간주하지 않는다.
- **`action_candidates`**: `id` — 발견 행동 UUID; `run_id` — 소속 실행; `crawl_node_id` — 발견 페이지; `element_signature` — 버튼/링크 식별 근거; `action_kind` — click 등 행동 종류; `risk` — 위험 분류; `policy_rule` — 허용·차단에 적용한 정책; `state` — 발견부터 실행/차단까지의 단계; `reason_code` — 차단·미실행 이유; `discovered_at` — 발견 시각; `executed_at` — 실제 실행 시각. 발견·허용·실행·기능 검증은 서로 다른 단계다.
- **`observations`**: `id` — 원시 관찰 UUID; `run_id` — 소속 실행; `run_environment_id` — 관찰한 환경; `crawl_node_id` — 관찰한 페이지; `kind` — HTTP/JS/network 등 이벤트 종류; `category` — 대표 대분류; `subtype` — 세부 유형; `source_url` — 비밀 제거한 출처 URL; `http_status` — 해당 응답 상태; `message` — 비밀 제거한 메시지; `occurred_at` — 관찰 시각; `details_json` — 요청/콘솔 등 추가 구조 정보. 원시 관찰 자체를 확정 버그로 세지 않는다.
- **`result_rows`**: `id` — 페이지·영역 결과 행 UUID; `run_id` — 소속 실행; `page_key` — 결과 페이지 identity; `page_match_id` — 관련 A/B 매칭; `region_id` — 영역 ID(전체 페이지면 NULL); `status` — 자동 대표 7상태; `reason_code` — 대표 판정 사유; `severity` — 상태와 별도인 심각도; `category`·`subtype` — 대표 오류 유형; `visual_difference_percent` — 실제 비교 가능 픽셀의 차이율, 비교 불가면 NULL; `visual_unavailable_reason` — 차이율을 계산하지 못한 이유; `baseline_url`·`candidate_url` — 이 행의 A/B 증거 출처 URL; `regression_classification` — 회귀 분류(품질 판정과 별도); `detail_json` — 행의 추가 근거·메타데이터. 결과 행 수는 고유 발견 사항 수와 다르다.
- **`checks`**: `id` — 실행된 검증식 레코드 UUID; `run_id` — 소속 실행; `result_row_id` — 표시될 결과 행; `check_id` — 재현 가능한 검증식 식별자; `environment_side` — A/B/비교; `scenario_id` — 등록 시나리오 ID 또는 conditions; `step_id` — 시나리오 단계/조건 ID; `status` — 검증식의 7상태; `reason_code` — 판정·미실행 이유; `required` — 필수 검증식 여부(1/0); `expected_json` — 기대값; `actual_json` — 실제 관찰값; `preconditions_json` — 검사 선행 조건과 평가 근거; `observed_at` — 검증 시각. 같은 검증식이 여러 행에 보이면 totals에서는 한 번만 센다.
- **`findings`**: `id` — 중복을 묶은 발견 사항 UUID; `run_id` — 소속 실행; `fingerprint` — 실행 내 중복 제거용 의미 지문; `assertion_key` — 관련 검증 계약 identity; `environment_side` — 출처 환경; `page_key` — 페이지 identity; `check_id` — 관련 검증식; `scenario_id`·`step_id` — 시나리오/단계; `category`·`subtype` — 발견 유형; `severity` — 심각도; `status` — 자동 상태; `expected_json`·`actual_json` — 기대/실제 근거; `occurrence_count` — 동일 지문의 관찰 횟수; `first_seen_at`·`last_seen_at` — 최초/최종 실제 관찰 시각; `tags_json` — 부가 분류. 발견 사항 수를 확정 버그 수로 부르지 않는다.
- **`finding_rows`**: `finding_id` — 발견 사항; `result_row_id` — 같은 발견 사항이 나타난 결과 행. 복수 행 연결용 테이블.
- **`finding_observations`**: `finding_id` — 발견 사항; `observation_id` — 근거가 된 원시 이벤트. 복수 이벤트 연결용 테이블.
- **`evidence`**: `id` — 증거 UUID; `run_id` — 소속 실행; `result_row_id` — 관련 결과 행; `check_record_id` — 관련 검증식 레코드; `finding_id` — 관련 발견 사항; `observation_id` — 관련 원시 관찰; `environment_side` — A/B/비교 증거 출처; `kind` — baseline/candidate/diff PNG, JSON 등 증거 종류; `relative_path` — 실행 디렉터리 기준 상대 경로; `mime_type` — 파일 형식; `sha256` — 파일 무결성 hash; `captured_at` — 수집 시각; `redacted` — 민감 정보 제거 여부(1/0). DB 공유만으로 파일이 함께 전달되지는 않는다.

### 검수·회귀

- **`review_state`**: `result_row_id` — 검수 대상 결과 행; `status` — 현재 QA 검수 상태(UNREVIEWED 등), 자동 판정과 별도; `revision` — 낙관적 잠금 버전; `issue_ref` — 연결한 외부 이슈 URL; `updated_at` — 마지막 검수 시각.
- **`review_events`**: `id` — 검수 이벤트 UUID; `result_row_id` — 검수 대상 행; `revision` — 이 변경 후 버전; `reviewer_id` — 검수 담당자; `previous_status`·`new_status` — 변경 전/후 검수 상태; `reason` — 사람이 기록한 판단 사유; `issue_ref` — 변경 후 이슈 연결; `retest_run_id` — 재검 실행 참조; `created_at` — 변경 시각. 이벤트는 추가만 하고 과거 기록을 수정하지 않는다.
- **`regression_evaluations`**: `id` — 회귀 평가 UUID; `current_run_id` — 현재 실행; `previous_run_id` — 비교 기준 실행; `comparable` — 규칙·범위·캡처 조건 비교 가능 여부(1/0); `reasons_json` — 비교 가능/불가 근거; `evaluated_at` — 평가 시각.
- **`regression_items`**: `id` — 발견 사항별 회귀 분류 UUID; `evaluation_id` — 소속 회귀 평가; `current_finding_id`·`previous_finding_id` — 현재/과거 발견 사항; `current_result_row_id` — 현재 대응 검증 결과 행; `classification` — NEW/RECURRING/RESOLVED_CANDIDATE/NOT_RETESTED/NON_COMPARABLE; `reason_json` — 분류 근거. 미재검·비교 불가를 해결로 표시하지 않는다.

### 검사 실행 화면과의 대응

| 화면/API 입력 | 저장 위치 |
|---|---|
| 프로젝트 선택, 환경 목록 | `projects`, `project_environments`; 실행 당시 선택은 `runs.project_id`, `run_environments` |
| 실행 담당자 ID, 검사 프로필, 목적, 모드, 과거 실행 | `runs.operator_id`, `profile_id`, `test_type`, `mode`, `previous_run_id` |
| A/B 이름·URL과 등록 환경 ID | `run_environments.name`, `start_url`, `project_environment_id`, `environment_registry_id` |
| 페이지/깊이/행동/시간 한도, 탐색 범위, 허용 경로·호스트, 시각 임계값, 로그인 옵션, 마스크, 별칭, 영역, 시나리오 | `runs.options_json`의 실행 시점 사본; 버전·hash는 `manifest_json` |
| 조건 기반 검사의 `conditions`, 활성 프로젝트 규칙 | `runs.options_json`의 실제 조건 배열 + `run_rules.condition_json`의 규칙별 사본; 결과는 `checks`/`result_rows` |
| 탐색·오류·이미지/차이·검수·회귀 | `crawl_nodes`/`observations`/`evidence`/`result_rows`/`review_events`/`regression_items` |

**현재 구현과의 차이:** 프로젝트와 환경, 검사 규칙은 PostgreSQL에서 읽고 저장한다. 실행 API는 아직 `projectId`/`projectEnvironmentId` 또는 `source_rule_id`를 보고서에 저장하지 않는다. 따라서 `runs.project_id`, `run_environments.project_environment_id`, `run_rules.source_rule_id`는 **실행 이력 DB 연결 시 추가할 계약**이며 현재 JSON 보고서에서 자동 복원할 수 있다고 가정하면 안 된다. 지금의 실행 옵션·조건·결과는 `qa/config.py`와 보고서 JSON에 저장된다.

## 적용 및 공유 규칙

1. 각자 같은 SQL을 PostgreSQL 16 이상 DB에 실행하고 외래 키는 PostgreSQL에서 자동으로 적용된다. 적용 뒤 `SELECT version FROM schema_migrations;`로 버전을 확인한다.
2. 프로젝트는 `projects`와 `project_environments`에, 프로젝트별 조건 규칙은 `project_rules`에 저장한다. 실행에 적용한 규칙은 `run_rules`에 사본으로 남긴다. 환경은 1개 이상이어야 한다는 앱 규칙은 저장 트랜잭션에서 검증한다. 환경 URL은 저장 전 `http(s)`·자격증명 부재를 검사한다. 길이 CHECK만으로 URL 유효성이 보장되지는 않는다. 규칙의 `condition_json`은 앱에서 `qa/conditions.py` 계약으로 검증한 뒤 저장한다.
3. 실행 때 선택한 A/B만 `run_environments`에 복사한다. 등록된 환경 전체에 자동 접속하지 않는다. `runs.operator_id`는 실행 시점 담당자 ID이고 프로젝트 설정에는 없다.
4. `runs.state=done`은 worker 종료만 뜻한다. `report_status`, 7상태 `result_rows.status`/`checks.status`, `review_state.status`는 각각 별개다. 미실행·비교 불가를 PASS 또는 0%로 채우지 않는다.
5. 검수 변경은 트랜잭션 안에서 `review_state.revision`이 예상 값과 일치할 때만 갱신하고 `review_events`에 같은 새 revision을 추가한다. 충돌하면 롤백한다. 이전 자동 판정과 검수 이벤트를 덮어쓰지 않는다.
6. 증거 파일은 DB에 포함되지 않는다. 공유할 때 `relative_path`가 가리키는 파일과 SHA256을 함께 확인한다. 비밀번호, 쿠키, 인증 토큰, 세션 상태, 민감 URL은 DB·증거·내보내기에 넣지 않는다.
7. 두 사람이 각각 로컬 DB를 사용하면 ID 충돌 방지를 위해 프로젝트·환경·실행·결과·검수 이벤트 ID를 UUID로 만든다. 단순히 DB 파일을 서로 덮어쓰지 말고, 공유·병합 절차와 충돌 정책을 정한 후 교환한다. 이 SQL만으로 다중 사용자 동기화가 구현되지는 않는다.
