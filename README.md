# Web QA Comparator

두 웹 환경의 페이지를 탐색하고, 명시적 URL 매핑·영역별 화면 비교·HTTP/JavaScript 관찰·등록된 기능 시나리오를 실행하는 **로컬 QA 도구의 첫 MVP**입니다. Python, Playwright, Pillow와 기존 HTML/JavaScript UI를 사용합니다.

운영 서비스 전체를 검증한 제품은 아닙니다. 기능 시나리오는 현재 공개 가능한 합성 데모에서 동작하며, 실사이트에는 별도의 경로·요소·기대값 설정이 필요합니다. 이전 소스 감사와 현재 구현을 구분한 목록은 [구현 현황](docs/IMPLEMENTATION_STATUS.md)을 보세요.

## 시작하기

Python 3.10 이상이 필요합니다. 개발 검증 환경과 고정 라이브러리는 `requirements.txt`와 구현 현황에 기록합니다.

Windows에서는 `setup_windows.bat`를 한 번 실행해 가상환경·의존성·Chromium을 설치한 다음, `run_windows.bat`를 실행하세요. 기본 주소는 **[http://127.0.0.1:3000](http://127.0.0.1:3000)**입니다. 서버는 loopback에만 바인딩합니다.

직접 실행하려면:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe app.py
```

macOS/Linux에서는 `.venv/bin/python`을 사용합니다. 포트 변경은 `PORT` 환경변수, 로컬 결과 폴더 변경은 `QA_RUNS_DIR` 환경변수로 가능합니다. WindowsApps Python 별칭만 있는 경우 실제 Python을 설치하세요. 제공 스크립트는 `.venv` 또는 설치된 Python 실행 파일을 찾습니다.

## 먼저 합성 데모 실행

1. 환경에서 **합성 데모**를 선택하고 담당자를 입력합니다.
2. 기본 설정으로 검사를 시작합니다. 앱 안의 A/B 데모에만 접속하며 외부 요청이 필요하지 않습니다.
3. 페이지/영역별 결과를 열어 매칭 근거, 검증식, 스크린샷, 발견·차단된 행동을 확인합니다.
4. 상태·차이율·비교 불가·영역·검색 필터로 범위를 좁히고 검수 사유를 저장합니다.
5. 실행 이력에서 다시 열거나 CSV/JSON을 내려받습니다. 앱 재시작 후에도 결과와 검수 이력이 남습니다.

데모에는 의도적으로 **B의 필수 Help 버튼 누락**, **서버별 공지 내용 차이**, **`.do` 경로 차이**, **절대 실행하면 안 되는 저장/삭제 함정**이 들어 있습니다. 따라서 모든 행이 PASS인 것이 데모의 정답이 아닙니다. `/demo/meta`는 합성 정답 라벨과 함정 실행 횟수를 제공합니다.

등록 시나리오 `demo.search`, `demo.input_length`, `demo.history`는 검색(버튼/Enter/결과 없음), UTF-16 기준 10자 입력 경계, 목록→상세→뒤로가기·새로고침을 검증합니다. 이 기대값을 실제 회사 사이트의 요구사항으로 적용하지 않습니다.

## 실사이트 설정

초등 PC·중고등 PC·초등 모바일의 사용자 제공 주소가 프로필에 들어 있습니다. 중고등 모바일 STG는 정확한 주소가 미확정이므로 비활성 상태입니다. 주소가 준비되면 직접 입력 프로필을 사용할 수 있습니다. 실제 사이트 자동 검사는 이번 개발 검증에 포함되지 않았습니다.

- 최초 URL과 명시적으로 매핑한 경로, 고급 설정의 허용 경로만 자동 방문합니다. 다른 링크는 발견 목록과 차단 사유에 남습니다.
- `#/...` route와 의미 있는 query 순서를 보존합니다. `.do`를 일괄 제거하지 않습니다. 구조 유사 후보는 REVIEW이며 승인 매핑으로 확정합니다.
- 허용 호스트는 정확한 `host[:port]`를 입력합니다. 외부 CDN/인증 호스트가 차단되면 결과의 `POLICY_BLOCKED`와 누락 범위를 확인한 후 필요한 호스트만 추가합니다.
- 자동 POST/업무 변경/다운로드/알 수 없는 버튼은 기본 차단합니다. DOM 클릭 성공만으로 기능 정상 PASS를 만들지 않습니다.
- 현재 `safeActions`는 승인된 click 실행만 제공합니다. 행동의 정식 기대값 검사는 Python 시나리오로 확장해야 합니다.

고급 매핑 예시(실제 사이트 설정이 아닌 형식 예시):

```json
[
  {"baseline": "/old/notice.do", "candidate": "/new/notice", "page_class": "notice.list"}
]
```

영역 설정 예시:

```json
[
  {"id": "home.navigation", "selector": "#site-nav", "required": true, "mask_selectors": []},
  {"id": "home.notice", "selector": "#notice-list", "required": true, "mask_selectors": [".notice-title"]}
]
```

selector는 대상 화면에서 확인해야 합니다. 마스크가 데이터값 차이를 가려도 영역의 존재/가시성 검사는 수행합니다. 현재는 일반적인 텍스트 겹침·잘림을 전부 판정하는 엔진이 없으므로 마스크만으로 UI 정상이라고 결론내리지 않습니다.

## 로그인과 두 사람의 작업

**수동 로그인**을 선택하면 실제 Chromium 창이 열립니다. 각 환경에서 사용자가 직접 로그인하고 앱에서 계속을 누릅니다. 비밀번호·세션 파일을 API나 디스크에 저장하지 않으며, 세션은 해당 실행의 환경별 context에만 유지됩니다. 로그인 성공·권한 역할은 사용자가 확인해야 합니다. 일반 사이트에 대한 자동 인증 성공 판별은 아직 없습니다.

아이디 기억은 선택 기능입니다. 체크한 경우에만 현재 브라우저의 localStorage에 담당자/프로필/A·B별 ID를 저장합니다. 비밀번호 저장·자동 붙여넣기는 없습니다. 브라우저 저장값은 암호화된 OS 비밀 저장소가 아니므로 공용 PC에서는 사용하지 말고 지우기 기능으로 제거하세요.

두 사람은 담당자 이름으로 실행·검수를 구분합니다. 검수 저장은 revision으로 충돌을 검출하며 자동 판정은 덮어쓰지 않습니다. **한 서버에서 동시 실행은 1개**입니다. 각자 로컬 실행할 경우 결과 폴더와 브라우저 세션을 공유하지 마세요. 담당자 문자열은 사용자 인증 기능이 아닙니다.

## 판정과 저장

| 상태 | 의미 |
|---|---|
| PASS | 실제 실행한 검증식의 기대값 충족 |
| FAIL | 명시한 기대값 위반 또는 현재 오류 정책의 실패 관찰 |
| REVIEW | 시각 차이·매칭 후보·기대값 미정 등 QA 검토 필요 |
| SKIP | 정책·전제·한도로 실행하지 못함 |
| ERROR | 브라우저·수집·비교·실행기 오류로 판정 불가 |

차이율 필터는 조회 범위만 바꿉니다. 0%와 비교 불가(null)를 구분하고, FAIL/ERROR는 별도 요약에도 남깁니다. 400/401/403은 일괄 무시하지 않으며 현재 정책은 출처·resource type을 구분합니다. endpoint별 예상 인증 응답 계약은 후속 작업입니다.

`runs/<run-id>/report.json`에 실행 설정·결과·검수 이력, `a/`, `b/`, `diff/`에 PNG가 저장됩니다. 실행 중 앱이 종료되면 다음 시작 시 해당 run을 `PROCESS_INTERRUPTED` 오류로 표시합니다. 결과 폴더는 `.gitignore`에 포함됩니다. URL 인증 파라미터·일부 로그 문자열을 제거하지만 모든 개인정보를 자동 탐지하는 기능은 아니므로 실제 서비스 증거를 공개하기 전 검수해야 합니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -B scripts/run_tests.py
```

테스트는 로컬 HTTP 서버와 합성 데이터만 사용합니다. Chromium이 설치되어야 브라우저 테스트를 실행할 수 있습니다. 임시 데이터는 프로젝트의 `output/tmp/`를 사용합니다. 테스트 횟수·결과·현재 제한은 [구현 현황](docs/IMPLEMENTATION_STATUS.md)에 기록합니다.

## 코드 안내

```text
app.py                 로컬 API, 실행/취소/수동 로그인, CSV
qa/config.py           프로필·입력 검증
qa/engine.py           제한된 탐색, 관찰, 캡처, 시나리오 통합
qa/matching.py         URL identity와 명시적 별칭
qa/comparison.py       Pillow 이미지 비교
qa/policy.py           5상태·위험 동작·HTTP 기본 정책
qa/scenarios.py        합성 데모 기능 검증식
qa/demo.py             자체 합성 A/B 사이트·정답·위험 동작 함정
qa/store.py            원자적 JSON 저장·재시작 복구·검수 revision
public/                한국어 실행/결과/검수 UI
tests/                 단위·HTTP·브라우저 검증
docs/                  이전 구현 감사, 설계, 현재 구현 현황
```

핵심 엔진과 통합은 담당 A, 사이트별 어댑터·기능 시나리오·보고/검수는 담당 B가 맡는 [협업 계획](docs/ROADMAP.md)을 유지합니다. 이번 MVP에서는 기업 샘플 소스·실데이터·기존 실행 이미지를 복사하지 않았습니다.
