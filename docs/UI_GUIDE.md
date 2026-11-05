# VISANG QA AI · UI 가이드

`public/index.html`·`public/styles.css`의 화면 규칙을 정리한 문서입니다. `app.js`와 브라우저 테스트(`tests/test_ui_*.py`)가 참조하는 **ID·클래스 이름은 그대로 유지**했고, 레이아웃과 스타일만 바꿨습니다. 상태 의미는 [README](../README.md#판정과-저장), 결과 화면 요구사항은 [REQUIREMENTS_AND_GAPS AR04](REQUIREMENTS_AND_GAPS.md)를 따릅니다.

## 페이지 구성 (v0.4 · origin/1105_mia 통합)

세 페이지가 같은 셸(왼쪽 사이드바 + 상단 바)과 같은 `styles.css`·토큰을 씁니다.

| 페이지 | 파일 | 역할 |
|---|---|---|
| 대시보드 | `m_dashboard.html` + `m_workspace.js` | 최근 완료 실행의 검수 분류 5타일, 실행 요약 4개, 최근 실행 표(클릭 → `/?run=<id>`로 결과 열기), 7상태 요약 |
| 프로젝트 설정 | `m_project_settings.html` + `m_project_settings.js` | 프로젝트별 환경(이름·URL) 목록을 브라우저 localStorage(`m_qa_projects_v1`)에 저장, "검사 설정에 적용"으로 실행 화면에 A/B 전달 |
| 검사 실행·결과 | `index.html` + `app.js` | 기존 4단계 설정·실행 이력·결과 대시보드. 1단계에 프로젝트 선택 추가 |

공통: `theme-boot.js`(그리기 전 테마 적용, 깜빡임 방지), `shell.js`(테마 버튼·사이드바 활성 표시). 대시보드·프로젝트 설정의 원안은 동료 브랜치 `origin/1105_mia`이며, 저장 키와 동작은 그대로 두고 디자인 토큰·검수 분류·테마만 맞췄습니다.

## 테마 (라이트 / 다크 / 시스템)

사이드바 아래 스위치로 고르며 `localStorage.qa_theme`에 저장됩니다. `<html data-theme="light|dark">`가 있으면 그 값, 없으면(시스템) `prefers-color-scheme`을 따릅니다. 다크 값은 `styles.css` 15절 한 곳에만 있고 모든 페이지가 공유합니다.

## 화면 흐름 (위에서 아래로)

| 순서 | 영역 | 역할 |
|---|---|---|
| 0 | 상단 바 | VISANG QA AI 브랜드, 검사 설정·실행 이력·검사 결과 바로가기, 버전 |
| 1 | 히어로 + 기능 카드 + 상태 범례 | 제품 소개 한 줄, 4가지 테스트 목적 카드, 7상태(PASS/FAIL/DIFF/REVIEW/SKIP/BLOCKED/ERROR) 의미 |
| 2 | 검사 설정 (4 Step) | ① 무엇을 → ② 어느 환경을 → ③ 어디까지 → ④ 선택 사항(로그인·고급) |
| 3 | 실행 이력 (우측, sticky) | 담당자별 과거 실행 선택 |
| 4 | 실행 중 패널 | 진행 메시지, 수동 로그인 계속, 중단 |
| 5 | 결과 대시보드 | **검수 분류 타일 5개**(이슈/대인체크/재검/정상/미실행, 클릭=필터) → 7상태 타일 8개 → 커버리지 칩 |
| 6 | 결과 표 | 상태 필터 → 검색/검수 분류/영역/차이율 → 세부 필터(접기 가능) → 행(상태 배지 + 분류 배지) → 상세(분류 카드·매칭·증거) → 검수 폼(분류 제안이 기본값) |

## 설정 폼 Step 규칙

- Step은 `<fieldset class="step">` + `<legend><span class="step-no">N</span>…</legend>`. 번호는 파란 원, 선택 사항(Step 4)은 회색 원(`step-optional`).
- A/B 환경은 `.env-pair` 안의 두 카드(`.env-card.env-a`, `.env-card.env-b`). 상단 색 띠로 구분: A = 파랑 `--env-a`, B = 청록 `--env-b`.
- 단일 환경·회귀·조건 검사처럼 B가 필요 없으면 `app.js`가 `.url-fields`에 `single-target`을 붙이고, CSS가 `:has()`로 B 카드를 숨기고 1열로 바꿉니다. JS 수정 없음.
- 긴 설명은 `.helper`(11px, 회색)로 입력 바로 아래 한 줄. 고급 입력은 `<details class="configuration-details">`로 접어 둠.

## 검수 분류(Triage) 요소

- `#triageStats` 안에 `app.js`가 `.triage-tile.{ISSUE|HUMAN_CHECK|RETEST|OK|NOT_RUN}` 버튼을 만든다. 클릭하면 `#triageFilter` select 값을 바꾸고 `renderRows()`를 호출한다.
- 행의 분류 배지는 `.triage-badge.{bucket}` (페이지 셀 안, `.status` 배지는 그대로 `.row-main`의 직접 자식 — 테스트 계약).
- 상세의 `.triage-note.{bucket}`은 사유·근거 코드·제안 검수를 보여준다. 색 변수: `--issue`, `--human`, `--retest` (+ 다크 값).
- 커버 페이지 통과는 Step 2의 `#entryDetails` (`#entrySelector`, `#entryText`, `#entryUrlPattern`, `#entrySides`). 선택자가 비어 있으면 payload에 `entry`를 넣지 않는다.
- 로그인 설정은 `#loginDetails` 안 `.login-option` 두 블록(테스트 계정 / 수동). `#loginEnabled`를 켜면 `#loginFields` 입력이 활성화되고 `#manualLogin`은 자동 해제된다(상호 배타).

## 대시보드 타일

- `#stats` 안에 `app.js`가 `.stat.ALL`, `.stat.PASS` … 를 만듭니다. CSS는 왼쪽 4px 색 띠(`::before`)와 숫자 색만 상태별로 지정합니다.
- 커버리지(`#coverageSummary`)는 둥근 칩 형태. 새 항목을 추가해도 스타일 수정 불필요.
- 열 수: 데스크톱 8 → 1150px 이하 4 → 550px 이하 2.

## 색 토큰 (`:root`)

| 용도 | 변수 | 값 |
|---|---|---|
| 배경 / 패널 | `--bg` / `--surface` | `#f3f5f9` / `#fff` |
| 본문 / 보조 / 흐림 | `--text` / `--text-2` / `--muted` | `#1f2a3d` / `#4b5a73` / `#7a889e` |
| 강조(버튼·링크·Step) | `--accent` | `#2f5fd8` |
| PASS | `--pass` / `--pass-bg` | 초록 |
| FAIL | `--fail` / `--fail-bg` | 빨강 |
| DIFF | `--diff` / `--diff-bg` | 파랑 |
| REVIEW | `--review` / `--review-bg` | 황색 |
| SKIP | `--skip` / `--skip-bg` | 회색 |
| BLOCKED | `--blocked` / `--blocked-bg` | 주황 |
| ERROR | `--error` / `--error-bg` | 보라 |

상태 배지(`.status.X`), 타일(`.stat.X`), 실행 상태(`.job-state`), 오류 항목(`.error-item.X`)이 전부 같은 변수를 쓰므로 **색을 바꿀 때는 `:root`만 수정**하면 됩니다.

## 반응형 기준점

- `1150px`: 이력 패널 260px, 타일 4열, 세부 필터 3열
- `880px`: 1열 레이아웃, 상단 바 링크 숨김, A/B 카드 세로 배치, 표 헤더 숨김(행 안에 라벨 포함)
- `550px`: 타일 2열, 버튼 전체 폭, 검수 폼 1열
- 모바일 가로 스크롤 없음(`scrollWidth <= innerWidth`) — 브라우저 테스트로 확인

## 이름에 대해

화면 이름은 **VISANG QA AI**, 코드명·모듈명은 `Web QA Comparator`를 유지합니다. 현재 엔진은 규칙 기반(Playwright·Pillow)이며 LLM을 호출하지 않으므로, 문구에서 "AI가 판정한다"고 쓰지 않습니다. 판정은 항상 근거(스크린샷·HTTP·JS 관찰)와 함께 표시합니다.

## 바꾸지 말아야 할 것

- 모든 `id`와 `app.js`가 생성하는 클래스 이름(`result-row`, `row-main`, `status`, `stat`, `history-item`, `finding-card`, `review-form` 등)
- `#testTypeFilter` 등 세부 필터는 접기 가능한 `<details class="advanced-filters" open>` 안에 있음. **`open`을 빼면 테스트가 select를 찾지 못해 실패**합니다.
- `.single-target` 토글, `.hidden` 유틸리티
- `#triageFilter`는 `SELECT_FILTERS` 첫 항목이라 `resetResultFilters()`가 함께 초기화한다. 타일 active 상태도 거기서 지운다.

## 검증 기록

- 2026-11-04 (브랜치 taehwan-, 규칙 v2.3): 테스트 계정 로그인·검수 분류 타일·동등 라우트 안내까지 합성 데모로 확인, 계정 문자열 미노출 확인
- 2026-11-04 (브랜치 taehwan-): 합성 데모 실행 → 32행 렌더, 상세/검수/스크린샷 정상. `tests.test_ui_contracts` + `tests.test_ui_browser` 8개 통과, 모바일(390px) 가로 넘침 없음.
