# 테스트 전략과 공통 계약

> 전체 목표 설계입니다. 후속 MVP의 구현·실행 검증·설계와의 차이는 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)를 참고하세요.

> 2026-10-30 추가 반영: 테스트 유형 4종, 목표 결과 상태 7종, 오류 유형·중복 처리, 결과 화면 구성. 현재 MVP의 5상태 구현과 구분한다. 추가 요구사항은 [REQUIREMENTS_AND_GAPS.md](REQUIREMENTS_AND_GAPS.md)의 8절을 따른다.

작성일: 2026-10-30 (KST). **이 문서는 구현 제안이다.** 현재 구현·실행 검증은 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), 이전 코드 감사는 [AS_IS_ARCHITECTURE.md](AS_IS_ARCHITECTURE.md), 요구사항별 상태는 [REQUIREMENTS_AND_GAPS.md](REQUIREMENTS_AND_GAPS.md)를 따른다. 기존 Python 동기 Playwright·Pillow와 순수 JS UI를 우선 재사용한다.

근거 약칭: `OLD` = `C:/Users/ASUS/Downloads/web-qa-comparator/web-qa-comparator`, `EPC` = `C:/Users/ASUS/Desktop/viva-e-pc`, `MVMH` = `C:/Users/ASUS/Desktop/viva-mv-mh`, `SPEC` = `C:/Users/ASUS/Downloads/web-qa-planning-docs/web-qa-planning/QA_AUTOMATION_PROJECT_SPEC.md`. 회사 샘플은 비교 대상의 표본이며 Comparator 구현 증거가 아니다. 이 문서의 예시 URL·값·한도는 검증 성과가 아니다.

## 1. 검사 범위와 환경 프로필

- 테스트 목적은 **단일 환경 QA·환경 비교 QA·회귀 테스트·조건 기반 UI QA**로 구분한다. 단일 환경은 대상 하나, 환경 비교는 동일 제품·디바이스의 A/B 한 쌍, 회귀는 비교 가능한 과거/현재 실행, 조건 기반 검사는 지정한 데이터·화면 조건을 사용한다. 목적과 탐색/시각/시나리오/통합 검사 구성은 별도로 기록한다.
- 환경 비교에서는 운영↔스테이징, 개발1↔개발2 등 임의의 환경을 선택한다. PC↔모바일을 동일 화면으로 비교하지 않는다. 운영을 절대적인 정답으로 간주하지 않고 양쪽을 독립 검증한다.
- 제품별 `site_profile_id`에 시작 URL, 허용 navigation/resource/auth 호스트, route 방식, viewport, 준비 조건, 영역, 안전 행동, 시나리오를 명시한다.
- 실제 사이트 주소 목록과 미확인 STG 주소는 [결정 문서의 환경표](DECISIONS_AND_OPEN_QUESTIONS.md#2-비교-환경-등록표)에 둔다. 이번 감사에서는 실제 사이트 접속·로그인·크롤링을 하지 않았다.
- 1주 MVP는 초등 PC 프로필 한 개와 합성 데모를 대상으로 한다. 모바일 hash route는 로컬 회귀 테스트로 우선 보장하고, 4개 서비스 전체 자동화 완료로 표현하지 않는다.

시작 설정 제안값: 환경당 10페이지, 깊이 2, 페이지 상태당 승인 행동 10개, run당 총 행동 50개, run 시간 예산 10분, 한 대상에 활성 page 1개, 행동 사이 최소 간격 1초. **성능 측정값이나 서비스 허용량이 아니다.** 대상 담당자 정책으로 더 낮출 수 있고 버전 관리한다. 기존 최대 30페이지/깊이 4 제한은 `OLD/app.py:426–430`에 존재하지만 시간·행동 예산은 없다.

## 2. 발견과 실행을 분리하는 상태 그래프

### 2.1 발견

1. 수동 등록 seed와 승인된 메뉴 경로부터 시작한다. A/B를 각각 탐색한다.
2. `a[href]`, button, input(특히 submit/image 포함), role=button/tab/link, tabindex, adapter가 지정한 onclick 요소를 **후보 목록**에 수집한다. submit도 발견 후 위험 등급으로 실행을 통제한다. 비밀번호·개인정보 입력값은 읽어 저장하지 않는다. 프레임은 허용 origin/adapter가 있는 경우만 포함한다. Shadow DOM·가상 목록·canvas 미지원은 누락 사유로 남긴다.
3. 후보에는 accessible role/name, selector 대안, href/form action, 부모 region, disabled/visible 상태, 프레임 경로, 관찰 시점을 저장한다. ID·개인정보가 들어간 원문은 저장 전에 제거한다.
4. 숨겨진 메뉴의 승인된 열기 동작 후 재수집한다. 무작위 hover/click으로 전체 DOM을 탐색하지 않는다.
5. `page_class + route_state + 승인된 UI 상태 + 필터/페이지번호`로 state key를 만든다. 공지 제목·시간·배너 회전값은 중복 상태 판별 키에서 제외한다. 새 상태가 예산을 넘으면 `BLOCKED/LIMIT_REACHED`를 기록한다.

근거: 기존 발견은 `OLD/app.py:103–115,219–228`의 anchor 수집뿐이다. `MVMH/frontend/src/components/main/MainSearch.js:26,64,80,94–96`, `MVMH/frontend/src/containers/cs/NoticeListContainer.js:129`에는 href 없는 동작이 있다.

### 2.2 안전 정책

| 분류 | 기본 처리 | 예시·실행 조건 |
|---|---|---|
| SAFE_NAVIGATION | 등록된 route 계약 안에서 허용 | 메뉴·목록·상세 조회. redirect 목적지도 검사 |
| SAFE_UI_STATE | adapter allowlist로 허용 | 탭·아코디언·메뉴 열기/닫기. 알려진 상태로 복원 |
| READ_SCENARIO | 명시 시나리오에서 허용 | 검색·필터·더보기. 조회 POST도 method+endpoint+payload 목적을 승인 |
| AUTH_MANUAL | 사용자 브라우저 조작 | 로그인·MFA. 자동 로그인 성공을 추정하지 않음 |
| DOWNLOAD_OR_POPUP | 일반 탐색은 SKIP | 승인된 자료/호스트/크기/횟수의 시나리오만 실행 |
| MUTATING | 운영에서 금지 | 저장·삭제·신청·발송·구매·탈퇴·검색기록 삭제·로그아웃 |
| UNKNOWN | SKIP + 검토 대기 | 실행 목적/부작용을 확인하지 못한 JS 링크·form·onclick |

deny 규칙은 allow 규칙보다 우선한다. 이름·CSS·HTTP method 하나로 안전함을 판단하지 않는다. GET도 상태를 변경할 수 있다. `MVMH/frontend/src/components/common/DownloadInfo.js:45–48,66–80`와 `MVMH/frontend/src/lib/api.js:1092–1098`은 다운로드 시 이력 요청과 POST가 있음을 보여준다. `MVMH/frontend/src/index.js:54–78`의 방문 로그처럼 페이지 로드에도 쓰기가 있을 수 있으므로 “모든 요청이 읽기 전용”이라고 보장하지 않는다.

행동 직전 locator를 재확인하고, 이벤트 대기기를 먼저 연결한다. 실행 후 URL·상태·새 창·네트워크를 기록하고 복원한다. 복원 실패 시 다음 행동을 강행하지 않고 `ERROR/STATE_RESET_FAILED`로 해당 분기를 종료한다. 승인되지 않은 navigation/업무 변경 요청은 가능한 범위에서 보내기 전에 차단하고 `SKIP/POLICY_BLOCKED`로 표시한다. 요청 차단만으로 모든 부작용이 방지된다고 주장하지 않는다. 허용되지 않은 redirect·popup 목적지는 열어 보며 확인하지 않는다.

중단/cancel, 총 시간·행동 수·호스트별 간격을 runner의 각 단계에서 검사한다. 한도 이후 큐에 남은 항목도 이유와 함께 남겨야 한다. `발견 → 허용 → 시도 → 완료 → 검증` 수를 따로 집계하며, “모든 클릭 가능 요소 테스트 완료”는 알려진 범위와 분모가 없으면 사용하지 않는다.

## 3. URL과 동일 기능 페이지 매칭

### 3.1 세 종류의 identity

| 식별자 | 의미 | 예시 |
|---|---|---|
| navigation URL | 실제 요청/이동용 원본, redirect 최종 URL 별도 | A와 B의 URL을 모두 보존 |
| page class | 기능 템플릿 | `home`, `notice.list`, `notice.detail`, `search.results` |
| instance/state | 서버 내 데이터·검색·탭 상태 | 환경별 notice ID, keyword, page, selected tab |

정규화는 profile별로 한다. hash-router의 `#/search`는 route이고 `#section`은 해당 사이트 규칙이 확인된 경우에만 문서 anchor로 취급한다. 중복 슬래시·trailing slash·인코딩·대소문자도 서버 의미가 보존되는 규칙만 적용한다. 의미 있는 query, 반복 파라미터의 순서, 검색/페이지/자료 ID를 일괄 제거·정렬하지 않는다. 추적 파라미터 제거는 승인 목록만 허용한다.

기존 `OLD/app.py:56–59`는 fragment를 삭제하고 query를 정렬한다. 모바일의 `MVMH/frontend/src/index.js:3,104–134,175–177`은 HashRouter와 hash 진입 변환을 사용하므로 손실이 실제로 중요하다. `OLD/app.py:67–74,300–318`의 key 동등 비교를 재사용하되 입력 identity와 매칭 단계를 분리해야 한다.

### 3.2 결정 순서

1. 동일 제품·디바이스·인증 역할인지 확인한다. 로그인 화면과 정상 홈을 root라는 이유로 매칭하지 않는다.
2. 양쪽 normalized identity가 같고 승인된 공통 UI anchor/route 계약을 충족하면 `MATCHED_EXACT` 후보를 검증한다.
3. 검수한 alias 매핑을 적용한다. `/subject.do ↔ /subject`는 해당 pair에만 허용한다. suffix를 모든 URL에서 삭제하지 않는다. 충돌은 `MATCH_UNCERTAIN`이다.
4. 제목·메뉴 경로·구조 signature·특징 요소·마스킹한 화면 유사도로 다른 URL의 후보를 제안한다. 제목이나 픽셀 유사도만으로 자동 확정하지 않는다. 동일 템플릿이면서 잘못된 기능인 경우를 negative sample로 포함한다.
5. QA가 후보를 선택하면 양쪽 기능 anchor와 기대 행동을 재확인하고 mapping version/승인자/근거를 저장한다. 확신도는 `HIGH/MEDIUM/LOW`와 근거 특징을 저장하며 보정되지 않은 점수를 확률처럼 표시하지 않는다.
6. 상대 경로 확인은 승인된 alias/등록 경로만 횟수 제한하여 수행한다. 무차별 URL guessing은 금지한다.

일대다/다대일 충돌은 자동 결합하지 않는다. 서버별 다른 notice ID의 첫 항목은 같은 **상세 기능**을 독립 검사하는 것이지 같은 게시물을 비교하는 것이 아니다. 매칭되지 않아도 해당 서버의 계약 검사는 실행할 수 있다.

`NOT_DISCOVERED`(발견 못함), `INACCESSIBLE`(인증/연결 문제), `NOT_FOUND_CONFIRMED`(허용된 URL에서 404 확인), `MATCH_UNCERTAIN`(후보 모호), `OUT_OF_SCOPE`를 분리한다. 200으로 표시되는 오류 페이지는 별도 soft-404 계약이 있을 때만 판정한다. `ONLY_BASELINE`/`ONLY_CANDIDATE`는 존재 자체의 증명이 아니다.

## 4. HTTP·JS 수집과 정책

listener는 페이지 이동/행동 전에 context 및 page에 부착한다. 원시 이벤트에는 `run_id, environment, page_id, state_id, scenario_id, step_id, request_id, timestamp, sanitized_url, method, resource_type, frame, origin_class, status, failure, redirect_chain`을 포함한다. response body와 인증 헤더는 기본 저장하지 않는다. 요청/응답과 JS·console의 원문을 그대로 로그로 내보내지 않는다.

| 관찰 | 기본 판정 | 예외·확인 조건 |
|---|---|---|
| 필수 document 404/500 | 명시된 route/status 계약 위반이면 FAIL | 인증 선행 실패면 보호 페이지 check는 BLOCKED; 원인 check 별도 |
| 필수 first-party 조회 API 500 | expected 2xx 계약이 있으면 FAIL | 명세 없으면 REVIEW, 화면 영향 근거 추가 |
| API 400 | 상태만으로 경미/치명 결정 금지 | 잘못된 입력 테스트의 기대 400이면 해당 assertion PASS; 정상 입력의 계약 위반이면 FAIL |
| 로그인 상태 확인 401 | 승인된 익명 상태 계약이면 예상 이벤트 | 로그인 상태에서 발생하면 REVIEW/계약 FAIL; 광역 401 무시는 금지 |
| 외부 위젯 403/5xx | EXTERNAL_DEPENDENCY + REVIEW | 필수 인증/핵심 기능이 실패하면 해당 기능 assertion은 FAIL 가능 |
| requestfailed | NETWORK_FAILURE | 통신 실패와 HTTP 응답 오류를 구분; 사용자의 취소/runner 차단과 구분 |
| pageerror | JS_EXCEPTION | 필수 기능의 uncaught 오류 금지 계약이면 FAIL, 미정이면 REVIEW |
| console.error | CONSOLE_ERROR + REVIEW | 명세/근거 없이 즉시 버그 확정하지 않음 |
| 수집기 자체 예외·누락 | ERROR/OBSERVATION_INCOMPLETE | 기존처럼 예외를 조용히 삼켜 PASS로 만들지 않음 |

HTTP 404/503도 응답을 받으면 `requestfailed`와 다른 경로로 관찰된다. [Playwright Request 공식 문서](https://playwright.dev/python/docs/api/class-request). listener 중복 이벤트는 request_id와 page/state를 기준으로 합치고 발생 횟수·최초/최종 시점을 보존한다. 이슈 개수를 제한한다면 누락 수를 기록한다. 기존 `OLD/app.py:92–96`의 35개 제한을 전체 이벤트 정상 수집으로 표현하면 안 된다.

예외 규칙에는 ID, 환경, endpoint pattern, method, resource type, 상태 코드, 기대 인증 상태, 사유, 작성자, 만료일, 적용 횟수를 둔다. 예외는 관찰 삭제가 아닌 판정 근거이며, 만료 시 REVIEW로 돌아간다.

### 4.1 오류 유형 분류

판정 상태는 검사 결론이고 오류 유형은 관찰한 문제의 종류다. 같은 유형도 기대값·사전 조건에 따라 다른 상태가 된다. 데이터 차이가 항상 오류는 아니므로 전체 목록은 “발견 사항”으로 표시한다. PASS나 정책상 SKIP에는 오류 유형이 없을 수 있다.

| 대분류 코드 | 분류 | 세부 코드 예시 | 관찰·검증 예시 |
|---|---|---|---|
| HTTP | HTTP 응답 | HTTP_4XX, HTTP_5XX, UNEXPECTED_STATUS | 페이지·리소스의 예상하지 않은 상태 |
| NETWORK | 연결·전송 | DNS_FAILED, TLS_FAILED, REQUEST_TIMEOUT, CONNECTION_FAILED | 연결·전송 실패 |
| JAVASCRIPT | 클라이언트 실행 | UNCAUGHT_EXCEPTION, UNHANDLED_REJECTION, CONSOLE_ERROR | JS 예외·Promise·콘솔 오류 |
| API | API 계약·응답 | API_STATUS_MISMATCH, API_SCHEMA_MISMATCH, API_BUSINESS_FAILURE | 상태·필수 필드·업무 결과 위반 |
| RESOURCE | 이미지·정적 파일 | IMAGE_LOAD_FAILED, SCRIPT_LOAD_FAILED, STYLESHEET_LOAD_FAILED, FONT_LOAD_FAILED | 필요한 파일 로딩 실패 |
| NAVIGATION | 링크·이동 | BROKEN_LINK, WRONG_DESTINATION, REDIRECT_LOOP, HISTORY_MISMATCH | 목적지·라우팅·뒤로가기 이상 |
| STRUCTURE | DOM·구성 요소 | REQUIRED_ELEMENT_MISSING, VISIBILITY_MISMATCH, ELEMENT_COUNT_MISMATCH | 필수 요소 누락·숨김·개수 불일치 |
| FUNCTIONAL | 기능 동작 | SEARCH_RESULT_MISMATCH, VALIDATION_MISMATCH, INTERACTION_MISMATCH | 검색·입력·탭·페이지네이션 계약 위반 |
| VISUAL | 시각·레이아웃 | REGION_DIFF, TEXT_OVERFLOW, ELEMENT_OVERLAP, LAYOUT_SHIFT | 이미지 차이·잘림·겹침·배치 변화 |
| DATA | 데이터·표시 조건 | CONTENT_DIFF, EMPTY_DATA, INSUFFICIENT_DATA, DISPLAY_CONDITION_MISMATCH | 데이터 차이·부족·노출 조건 불일치 |
| AUTH | 인증·권한 | LOGIN_REQUIRED, SESSION_EXPIRED, ROLE_UNAVAILABLE, ACCESS_DENIED | 로그인 필요·만료·권한 부족 |
| TEST_INFRA | 검사 도구·설정 | BROWSER_LAUNCH_FAILED, CAPTURE_FAILED, COMPARE_FAILED, EVIDENCE_SAVE_FAILED, MAPPING_UNRESOLVED | 브라우저·수집·비교·저장·매핑 문제 |

위 코드는 목표 분류안이다. 모든 항목의 자동 탐지가 구현되었다는 의미는 아니다. 세부 코드와 판정 사유 `reason_code`는 구분하며, API 스키마·업무 결과·잘림·겹침 등은 별도 계약과 수집기가 필요하다. HTTP 상태·요청 method·resource type·출처는 유형과 별도로 보존한다.

### 4.2 대표 유형과 중복 처리

- 이미지 요청 404는 `RESOURCE / IMAGE_LOAD_FAILED`를 대표 유형으로 두고 HTTP 404 사실과 관련 태그를 보존한다. HTTP·RESOURCE·VISUAL 세 건으로 단순 합산하지 않는다.
- API 계약 검사에서 500이 발생하면 `API / API_STATUS_MISMATCH`를 대표 유형으로 두고 기대 상태와 실제 HTTP 상태를 함께 기록한다. 계약이 없다면 HTTP 관찰은 보존하되 API 계약 위반으로 확정하지 않는다.
- 대표 유형은 검증한 대상 계약으로 선택한다. 버튼 존재 검사는 STRUCTURE, 버튼을 통한 기능 검사는 FUNCTIONAL이다. 관련 발견 사항을 연결하되 같은 원인인지는 근거 없이 확정하지 않는다.
- 동일 요청·환경·페이지·단계·규칙의 반복 관찰을 묶고 발생 횟수·최초/최종 시점을 보존한다. 서로 다른 환경이나 별도 검증식의 결과는 삭제하지 않는다.
- 원시 관찰 수, 결과 행 수, 중복을 묶은 고유 발견 사항 수, 연결된 이슈 수를 구분한다. fingerprint의 구체 형식은 구현 전 계약으로 확정한다.

## 5. 시각·DOM·CSS 및 데이터 검증

### 5.1 준비 조건과 영역

viewport/DPR/브라우저 빌드/OS·폰트/locale/timezone/color scheme/인증 역할/입력을 고정한다. 폰트 준비, 해당 component의 loading 종료와 안정된 bounding box를 확인한다. 무조건적인 sleep이나 network-idle 하나를 완료 증거로 삼지 않는다. Playwright 공식 API도 테스트 준비 상태에 `networkidle` 의존을 권하지 않는다. [Page API](https://playwright.dev/python/docs/api/class-page#page-wait-for-load-state).

전체 화면은 맥락 증거이고 판정 단위는 `page → region → scenario → step → check`이다. 초안 region은 `home.navigation`, `home.notice`, `home.banner`, `search.form`, `search.results`, `notice.list`, `material.actions`로 두고 실제 selector는 adapter에서 확정한다. 샘플 `EPC/src/main/java/com/vivasam/elementary/mvc/controller/MainController.java:94–120`은 홈에 여러 서비스 데이터가 주입됨을 보여준다.

- 픽셀: 동일 capture 조건과 크기에서 비교. component crop/overlay/변경 bounding box를 함께 제공한다. region 위치 이동은 crop 비교로 놓칠 수 있어 layout check가 별도로 필요하다.
- DOM: role/name/필수 요소·계층·행 구조를 비교한다. 전체 innerHTML 문자열 diff는 동적 ID 때문에 기본 사용하지 않는다.
- CSS/layout: 승인 속성(font/size/spacing/color/display)과 element rect, overflow/clipping, 클릭 타깃 노출을 검사한다. 의도된 overlay·줄임표·가로 스크롤은 계약으로 구분한다. rect 교차만으로 전부 겹침 버그로 확정하지 않는다.
- 스크린샷·이미지 처리 실패/크기 불일치는 해당 비교 check의 `ERROR`이며 0%·PASS로 치환하지 않는다. 유효한 adapter와 준비된 화면에서 명세상 필수 region/버튼이 없으면 **존재 assertion은 FAIL**이다. selector/adapter 자체의 오류는 ERROR, 인증·데이터 전제 미충족은 BLOCKED, 정책 제외는 SKIP으로 구분한다. 필수 영역이 없어 수행할 수 없는 후속 이미지 비교는 선행 실패를 연결하고 BLOCKED로 기록한다.

원시 차이율 = 변경 픽셀 / 전체 비교 픽셀 × 100, 정책 적용 차이율 = 변경된 유효 픽셀 / 마스킹을 제외한 유효 픽셀 × 100. 비교 영역이 0이면 목표 설계에서는 `BLOCKED/NO_COMPARABLE_PIXELS`로 기록한다. 현재 MVP의 ERROR 처리와 구분하며 적용 전 계약을 확정한다. 알고리즘·픽셀 감도·region threshold·mask version을 저장한다. 기존 Pillow 처리(`OLD/app.py:234–257`)는 재사용하되 기존 회색조 변환/감도 25가 작은 색상 차이를 놓칠 수 있는지 합성 fixture로 검증하고 임계값을 조정한다.

**비교 가능한 증거에서 확인한 시각 차이 자체는 DIFF다.** 매칭·준비 조건·증거가 불명확하면 REVIEW다. 승인된 필수 요소 부재·버튼 잘림·명세 기반 위치 허용범위 위반만 해당 assertion FAIL이다. 화면이 비슷하면 동일 페이지의 후보가 될 수 있지만 기능이 다르면 매칭할 수 없다.

### 5.2 데이터 모드

| 모드 | A/B 값 비교 | 독립 검증 | 한계 |
|---|---|---|---|
| LIVE_INDEPENDENT (기본) | 공지 제목·개수·날짜·ID·자료·배너·검색 결과의 직접 일치 제외 | 각 환경의 목록/빈 상태/필수 필드/상세 연결/검색·필터·레이아웃 | DB 실제 일치성·검색 정답 데이터는 입증하지 못함 |
| SHARED_FIXTURE | 승인된 stable key로 동일 데이터 대응 시만 허용 | fixture 사전조건/계약/정확한 기대값 | 운영에 fixture를 쓰지 않음; 도구 오류는 ERROR, 데이터 전제 미충족은 BLOCKED |
| MOCK_UI | 같은 승인 API 응답에 UI 값·배치 비교 | 빈 결과/긴 제목/다국어/오류 상태 | 실제 API·DB 정상성 입증 불가; LIVE 결과와 분리 |

API mocking 자체는 Playwright의 기존 기능으로 구현할 수 있다. [Network 공식 문서](https://playwright.dev/python/docs/network). 공통 fixture는 별도 테스트 환경·승인된 생성/정리 절차에서만 사용하며 이번 단계에서는 DB에 접근하지 않는다.

LIVE 예: “홈 전체 다름” 대신 `home.notice.title / DATA_DIFF / 정책=LIVE_INDEPENDENT / 값 비교 제외`를 표시한다. 값 제외는 기록 삭제가 아니다. 해당 영역의 컨테이너·제목 노출·겹침·자세히보기는 별도 check로 유지한다. 허용된 값 차이는 정보 관찰로 남기고, 비교 가능한 콘텐츠 차이는 DIFF, 비교 근거가 부족하면 REVIEW다. 데이터만 다르고 명시된 구조 assertion이 통과했다면 그 assertion은 PASS일 수 있지만 두 DB가 같다는 뜻은 아니다.

검색 결과에 키워드 문자열이 반드시 포함되어야 한다는 계약도 임의로 만들지 않는다(동의어·형태소 검색 가능). LIVE는 입력 전달·요청 조건·로딩 종료·결과 또는 없음 상태와 이동 계약을 검사하고, 정확한 결과 집합은 fixture 명세에서만 판정한다.

### 5.3 결과 필터와 판정 분리

- 실행 규칙: `pixel_sensitivity`, `region_threshold`, `mask_policy_version`.
- 조회 필터: 상태, 환경, page class, region, scenario, category, reviewer, `diff_min/max`, 비교 불가 포함 여부.
- 조회 필터는 저장된 PASS/FAIL을 다시 계산하지 않는다. 정책 재판정은 원본 run을 덮어쓰지 않고 별도 evaluation version으로 연결한다.
- 0%는 수치 0, 비교 불가는 null + reason이다. CSV에서도 구분한다. 화면 차이가 작아도 HTTP/기능 FAIL은 별도 “치명 이슈” 목록에 남겨 시각 필터 때문에 숨겨지지 않게 한다.

### 5.4 결과 화면 구성

- **요약**: 7상태별 개수, 방문·검증·차단·제외 범위, 고유 발견 사항 수, 연결된 이슈 수를 표시한다. 동일 현상이 여러 페이지/영역 행에 나타날 수 있으므로 행 수를 독립 버그 수로 표시하지 않는다.
- **필터**: 테스트 유형, 환경, 상태, 오류 대분류·세부 유형, 심각도, 검수 상태, 회귀 구분을 제공한다. 기존 차이율·비교 불가·영역·검색 필터도 유지한다.
- **목록**: 페이지/영역, 판정, 대표 유형, 관찰 내용 요약, 검수 상태, 이슈 연결 상태를 표시한다. 데이터 차이·검사 차단을 모두 확정 오류로 부르지 않는다.
- **상세**: 기대값·실제값, 사전 조건, 스크린샷·차이 이미지, 요청·콘솔 정보, 원인 후보와 근거, 검수·변경 이력을 연결한다. 환경 비교 증거에는 A/B 출처를, 단일 환경에는 해당 환경을, 회귀 비교에는 과거/현재 실행을 명시한다.

이슈 연결·회귀 구분·원인 후보가 아직 없으면 미등록/미평가로 표시한다. 데이터 부재를 정상·해결로 추정하지 않는다. 자동 판정과 검수는 별도이며, 화면 필터로 저장된 판정을 바꾸지 않는다. 이는 목표 화면 요구사항으로 현재 UI의 구현 완료를 의미하지 않는다.

## 6. 기능 시나리오 확장 계약

MVP는 Python의 등록된 함수/클래스로 시나리오를 구현한다. JSON은 입력·설정과 결과 직렬화에 사용하고, YAML/임의 코드 실행 DSL은 도입하지 않는다. 기존 `visit()`은 매 방문 후 page를 닫으므로(`OLD/app.py:119–196`), history를 검증하는 시나리오는 **시나리오 내부에서 동일 page/context를 유지**해야 한다. 서로 다른 시나리오·환경·QA 담당자 사이는 분리한다.

| 경계 | 공통 인터페이스 제안 | 책임 |
|---|---|---|
| SiteAdapter | `identify(page)`, `ready(page, region)`, `locate(target)`, `classify_action(candidate)` | 제품별 selector·라우트·준비·안전 규칙 |
| Discovery | `discover(context, profile, budget) -> DiscoveryResult` | 페이지/상태/행동 후보와 skip 이유 |
| Matcher | `match(a, b, mapping_rules) -> MatchResult` | 양쪽 page ID, 방식, 신뢰 근거, 승인 상태 |
| Collector | `attach(context, sink)` / `close()` | 원시 event; 제품 판정과 분리 |
| Scenario | `preconditions(ctx)`, `execute(ctx) -> list[CheckResult]`, `cleanup(ctx)` | 입력·행동·기대값·검증·복원 |
| Comparator | `compare(a_snapshot, b_snapshot, policy) -> list[CheckResult]` | region별 pixel/DOM/layout |
| PolicyEvaluator | `evaluate(observations, assertions, policy) -> CheckResult` | 상태/심각도/사유; UI와 분리 |
| ResultStore | `append_result`, `append_review(expected_revision)`, `get_run` | 불변 결과·검수 이력·충돌 검사 |

`ScenarioContext` 필수값: run/environment/operator/profile, page/context, adapter, data_policy, collector, evidence_writer, budget, cancel_token. 시나리오는 직접 다른 환경의 DB를 조회하거나 임의 URL로 이동하지 않는다. `scenario_id/version`, 요구사항 ID, page class, 승인 행동 목록, 데이터 모드, 입력 fixture, 전제조건, ready 조건, timeout, cleanup, 검증식 ID를 등록한다. prerequisite 미충족은 BLOCKED, 기대값 미정은 REVIEW, 실행기 예외는 ERROR로 반환한다.

검색은 Enter/버튼과 결과 상태를, 길이 제한은 N−1/N/N+1·붙여넣기·공백·한글·이모지를, history는 브라우저 back/forward와 UI back을 분리한다. `maxlength` 발견만으로 정식 요구사항 N을 확정하지 않는다. UTF-16 code unit/문자/grapheme/byte 중 어떤 단위인지 TC에 적고, IME 조합을 일반 fill 테스트로 검증했다고 주장하지 않는다. 합성 입력 N=10 같은 데모와 실제 제품 N은 별개다.

팝업은 DOM modal, JS dialog, 새 tab을 구분한다. 다운로드는 이벤트·실패 여부·허용 MIME/파일명/크기·완료를 검증하고 파일을 실행하지 않는다. 파일 바이트 일치는 공통 fixture에서만 허용한다. 수신 파일은 공개 artifact에 포함하지 않고 승인된 임시 위치에서 관리한다. 예상 이벤트를 먼저 기다린 뒤 행동하는 Playwright API를 사용할 수 있다. [Page API](https://playwright.dev/python/docs/api/class-page).

## 7. 결과 스키마 v1 초안 — 두 담당자의 공통 기준

아래는 **합성 예시**이다. implementation 전에 A/B가 계약 테스트로 고정한다.

```json
{
  "schema_version": "1.0",
  "run_id": "demo-run-001",
  "result_id": "check-001",
  "attempt": 1,
  "operator_id": "qa-a",
  "site_profile_id": "demo-pc",
  "environment": "candidate",
  "page_id": "page-b-01",
  "page_class": "home",
  "state_id": "home-default",
  "match_id": "match-01",
  "region_id": "home.notice",
  "scenario_id": "notice.open.v1",
  "step_id": "open-first-item",
  "check_id": "detail-shows-selected-item",
  "requirement_ids": ["R22", "R23", "R25"],
  "test_case_ids": ["TC-16"],
  "action_path": ["home", "notice", "open-first-item"],
  "input_ref": "redacted-input-001",
  "expected": {"contract": "detail-for-selected-local-item"},
  "actual": {"contract_satisfied": true},
  "status": "PASS",
  "reason_code": "ASSERTION_SATISFIED",
  "severity": "NONE",
  "observation_ids": ["event-001"],
  "evidence_ids": ["image-001"],
  "policy_version": "live-independent.v1",
  "review_status": "UNREVIEWED"
}
```

- `RunManifest`: schema/tool/source hash/commit(없으면 null+사유), operator, `run_mode`(DISCOVERY/VISUAL/SCENARIOS/COMBINED), 환경별 URL·redirect, 시각/타임존, 브라우저 버전·OS·viewport·DPR·locale·폰트, 인증 **역할/별칭만**, 입력/fixture/seed, 한도, adapter/mapping/policy/scenario version, 시작·종료·취소 사유, 테스트 대상 build ID(미확보면 UNKNOWN).
- `MatchResult`: A/B page_id, 원 URL·최종 URL, page_class, 각 instance key, method, confidence label+근거, reviewer, mapping version. A/B 어느 한쪽이 없어도 독립 check는 보존.
- `ActionCandidate`: candidate ID, element signature, region/state, risk, policy rule, discovered/allowed/attempted/verified/blocked, reason.
- `Observation`: 변경하지 않는 관찰 이벤트. URL query·console·stack은 비밀 제거 후 기록. 차단/누락·truncation 수 포함.
- `Evidence`: 상대 artifact 경로, MIME, SHA256, capture 시각, redact 상태, run/page/step 연결. HTML export는 escape하고 외부 스크립트·민감 URL 포함 여부를 검사한다.
- `ReviewEvent`: result ID, previous/new review status, reviewer, revision, timestamp, reason, issue ref, retest run ref. 원래 자동 상태를 덮어쓰지 않는다.
- 저장은 run manifest/result JSON+PNG부터 시작하고 review는 append 이력으로 보관한다. 공유 서버에 두 사람이 동시에 쓰는 기능은 revision 검사·원자적 저장 또는 SQLite transaction 검증 후 확장한다. unknown major schema는 import ERROR, minor 추가 필드는 무시 가능한 규칙으로 정한다.

## 8. 자동 상태·심각도·QA 최종 검수

목표 결과 상태는 다음 7종이다. 현재 MVP의 5상태 구현과 과거 저장 결과는 별도이며, 기존 REVIEW/SKIP을 근거 없이 DIFF/BLOCKED로 일괄 변경하지 않는다.

| 상태 | 판정 조건 | 예 |
|---|---|---|
| PASS | 전제조건과 명시된 assertion이 실행되어 참 | 검색 요청 값이 입력과 같음; 정해진 결과 상태 표시 |
| FAIL | 제품 기대 동작/계약이 실행 가능한 조건에서 거짓임을 증거로 확인 | 필수 버튼 없음, 정상 조회 API 계약 위반, 뒤로가기 상태 불일치 |
| DIFF | 환경 간 차이를 확인했으나 오류 여부 미확정 | 비교 가능한 A/B의 시각·콘텐츠 차이 |
| SKIP | 설정·검사 범위·안전 정책에 따라 제외 | 위험 행동 차단, 선택하지 않은 검사 |
| BLOCKED | 실행에 필요한 데이터·권한 등 사전 조건 미충족 | 로그인 필요, 최소 표본 데이터 부족 |
| ERROR | 테스트 실행기/수집/비교/증거 실패로 판정 불가 | browser crash, locator adapter 오류, 이미지 파싱 실패 |
| REVIEW | 증거 부족·기대값 미정으로 수동 검토 필요 | 매칭 후보, 미정 검색 복원 정책, 원인 판단 근거 부족 |

DIFF는 차이가 확인된 상태이고 REVIEW는 판단 근거가 부족한 상태다. DIFF에도 별도 검수 대기를 연결할 수 있다. API 500 같은 서비스 관찰은 실행기 ERROR와 구분하고 기대 계약 위반이면 FAIL로 판정한다. 기대값 없이 HTTP 코드나 요소 미표시만으로 FAIL을 확정하지 않는다.

필수 데이터 부족은 BLOCKED지만, “데이터 0건이면 빈 목록 안내 표시” 계약을 실제 검사했다면 PASS/FAIL이다. Timeout은 일괄 FAIL이 아니다. 필수 화면 준비 SLA 위반을 확인하면 FAIL, runner/selector 문제면 ERROR, 인증 선행조건 미충족이면 BLOCKED, 원인 불명이면 REVIEW다. 심각도는 기존 `CRITICAL/HIGH/MEDIUM/LOW/NONE`을 유지하고 상태와 분리한다.

시간·페이지·행동 한도에 막힌 미실행 check는 `BLOCKED/LIMIT_REACHED`로 기록하는 안을 제안한다. 구체 한도별 코드는 구현 전 확정한다. 사용자가 취소한 실행은 별도 `CANCELLED`로 기록하고 완료한 check와 미실행 사유를 보존한다.

집계는 check별 7상태 수와 coverage를 함께 표시한다. 대표 배지 우선순위는 **FAIL → ERROR → 필수 BLOCKED → REVIEW → DIFF → 필수 SKIP → PASS**로 제안한다. 필수 검증이 모두 통과하고 미확인 차이·판정 불가·필수 누락이 없을 때만 대표 PASS다. 전부 설정 제외라면 SKIP이며 미실행을 PASS로 만들지 않는다. 다른 상태가 함께 있으면 대표 배지 옆에 개수와 불완전 실행 여부를 보존한다.

run 완료 여부(`COMPLETED/PARTIAL/CANCELLED/ERROR`)는 품질 판정과 별도다. 필수 BLOCKED/ERROR가 남으면 정상 검증 완료로 표시하지 않는다. 대표 배지 세부 집계는 구현 전 계약 테스트로 확정한다.

검수 흐름:

1. 담당자가 run/profile/정책/인증 상태와 누락 범위를 확인하고 자신의 review queue에서 결과를 인수한다.
2. 매칭·데이터 예외·region·행동·원시 이벤트·전후 증거를 확인한다. 실서비스 민감 증거는 로컬 접근 통제 아래 검수한다.
3. 필요하면 동일 input/fixture/version으로 선택 check만 재실행한다. 첫 실패를 숨기기 위해 성공할 때까지 재시도하지 않는다. attempt별 결과를 모두 보존한다.
4. 이상 관찰은 `BUG_CONFIRMED`, `EXPECTED_DIFFERENCE`, `FALSE_POSITIVE`, `RETEST_REQUIRED` 중 하나와 사유를 기록한다. 초기값은 `UNREVIEWED`. 정상 PASS 표본을 검수해 문제가 없음을 확인한 경우는 별도 `VERIFIED_OK`로 기록하여 FALSE_POSITIVE로 집계하지 않는다. 기획의 `NEEDS_RETEST`는 `RETEST_REQUIRED`로 정규화한다.
5. 오류 확정은 제품 요구사항과 재현 증거를 붙인다. 정책 예외 변경·매칭 승인·심각 결함은 다른 담당자가 검토한다. 확정 건이 적어도 정상 표본을 함께 검수해 미탐을 평가한다.
6. 재검 결과는 원래 결과에 연결하고 검수 이력을 보존한다. 두 명의 동시 편집은 expected_revision 불일치 시 충돌을 반환하며 조용히 덮어쓰지 않는다.

## 9. 구체 테스트 카탈로그

아래는 **실행할 테스트 명세**이며 현재 통과 결과가 아니다. 첫 MVP에서는 TC-01~08, 13~15, 21~24, 26~29, 31~33 중 core gate와 2~3개 기능 시나리오를 선택한다. 모든 항목을 1주 완료했다고 표시하지 않는다.

| ID | 조건·행동 | 기대 결과/판정 | 계층·근거 |
|---|---|---|---|
| TC-01 | `#/search`와 `#/notice` 발견 | 서로 다른 route, anchor와 구분 | unit; OLD/app.py:56–59 |
| TC-02 | `.do` 별칭 승인/미승인/충돌 | 승인 pair만 매칭, 충돌 REVIEW | unit; OLD/app.py:67–74 |
| TC-03 | 추적 query·detail ID·반복 query 순서 | 추적값만 제외; 의미값 보존 | unit; OLD/app.py:56–74 |
| TC-04 | 제목/화면 같은 서로 다른 기능·로그인 gate | 구조 유사만으로 자동 매칭 금지 | matcher fixture |
| TC-05 | JS 메뉴/href 없는 더보기·submit 발견 | 후보에 나타나며 승인 행동만 실행 | browser fixture; `MVMH/frontend/src/components/main/MainSearch.js:26,80` |
| TC-06 | 삭제/저장/unknown GET/외부 redirect | 실행 차단+SKIP 이유; 서버 변경 카운터 0 | trap fixture |
| TC-07 | page/depth/action/time/cancel 한도 | 큐 잔여·중단 이유 기록, 추가 행동 없음 | runner integration |
| TC-08 | hash 별칭과 모바일 viewport 프로필 | PC와 섞이지 않으며 hash 유지 | profile fixture |
| TC-09 | 필수 document 404/500 | route 계약 FAIL; 실제 발생 URL 증거 | HTTP fixture |
| TC-10 | 익명 auth probe 401, 외부 위젯403 | 좁은 정책의 예상 관찰/REVIEW, 전체 FAIL 아님 | collector fixture |
| TC-11 | 정상 입력 API400 vs 음성 테스트 예상400 | 전자는 계약 FAIL, 후자는 assertion PASS | policy unit/browser |
| TC-12 | pageerror·console·requestfailed 및 반복 이벤트 | 유형·출처·단계·횟수 구분; 누락 시 불완전 표시 | collector integration |
| TC-13 | 양쪽 공지 제목·개수만 다름 | LIVE 데이터 비교 제외/정보; 구조 check 유지 | dual demo |
| TC-14 | 마스킹 영역 안 버튼 잘림·행 겹침 | pixel mask와 별개 layout 계약 FAIL | visual/layout fixture |
| TC-15 | region 스크린샷 없음/손상/크기 불일치 | 증거 수집·처리 실패는 ERROR, 선행조건 미충족은 BLOCKED; PASS 금지 | comparator unit |
| TC-16 | 각 환경 공지의 첫 표본→상세 | 각자 선택한 항목과 상세 연결 검증; A/B ID 동일성 주장 금지 | browser scenario |
| TC-17 | 검색 빈값/키워드/Enter/버튼 | 승인 명세의 요청·상태; 정확한 집합은 fixture에서만 | scenario; `MVMH/frontend/src/containers/main/MainSearchContainer.js:54–177` |
| TC-18 | N−1/N/N+1·한글·이모지·paste·공백 | 승인 길이 단위와 거절/절단/안내 계약; 미정이면 REVIEW | synthetic input fixture |
| TC-19 | 목록→상세→browser back/forward | 검색·필터·스크롤 보존 여부는 확정 TC와 대조 | scenario |
| TC-20 | UI back·직접 진입 back·새로고침 | 각 계약대로 route/state 복원; 요구 미정 REVIEW | `MVMH/frontend/src/pages/cs/NoticePage.js:7–28` |
| TC-21 | 팝업/modal/dialog/new-tab | 허용 이벤트·origin·닫기·부모 상태 확인 | synthetic scenario |
| TC-22 | 승인 파일 다운로드/실패/대용량/외부host | 완료·MIME·size 검증 또는 정책 SKIP; 파일 실행 없음 | synthetic scenario |
| TC-23 | 차이율 0/null/경계·상태복합 필터 | 조회만 변경, 판정 불변; null 별도; CSV 0 보존 | report/UI |
| TC-24 | 실행기 예외/모든SKIP/필수BLOCKED/DIFF/FAIL+ERROR | 7상태 및 집계규칙 유지, 차이와 근거 부족 구분, 무실행 PASS 없음 | policy unit |
| TC-25 | fixture 누락·API mock·실데이터 | 모드 표기, 누락 시 정밀비교 중단; mock을 DB 검증으로 표시 금지 | contract test |
| TC-26 | 수동 로그인·ID 기억 해제·세션 만료 | PW 미저장; 사용자/환경별 분리; 만료 BLOCKED/재로그인 | auth local fixture |
| TC-27 | 토큰/PII 포함 URL·console·스크린샷 | export 전 제거/차단, 로그인 캡처 제외 | security fixture |
| TC-28 | restart 후 run/CSV/증거 조회 | manifest·정책·결과·연결 보존, 손상 artifact 명시 | persistence test |
| TC-29 | 두 담당자 리뷰·같은 revision 변경 | 담당자 구분, 충돌 반환, 이력 손실 없음 | contract/integration |
| TC-30 | 폰트 지연·로딩·애니메이션·동일 빌드 반복 | 준비조건/같은 입력에서 반복 결과 기록; 미완료 ERROR | stability fixture |
| TC-31 | skip reason·분모·matched/unmatched 집계 | 포함 범위가 명확하고 중복 page/step 이중 계산 없음 | metrics unit |
| TC-32 | API export/HTML/CSV 특수문자 | script/formula 삽입 방어, 0/null 보존 | report security fixture |
| TC-33 | 정상/seeded defect/정상 DB 차이 세트 | ground truth와 자동·QA 결과를 별도 저장 | benchmark |
| TC-34 | 정상처럼 보이는 공통 200 오류 페이지 | 알려진 오류-page 계약이면 FAIL, 외형만으로 PASS 금지 | matching/health fixture |
| TC-35 | framework crash/collector 예외/중간 종료 | 부분 결과와 ERROR/중단 원인 보존, 다음 run 격리 | resilience fixture |

### 요구사항과 테스트 연결

요구사항 ID는 [REQUIREMENTS_AND_GAPS.md](REQUIREMENTS_AND_GAPS.md)의 Rxx, 테스트 ID는 TC-xx로 분리한다. 아래 연결은 계획이며 통과 여부는 이후 실행 레코드로 연결한다.

| 요구사항 | 검증 계획 |
|---|---|
| R01, R02, R03 | 기존 URL/독립 context 회귀 + TC-08,26,28,33; fresh install gate |
| R04, R05, R07, R08, R41 | TC-05~07,21~22,35 |
| R06, R09~13, R42 | TC-01~04,08,34 |
| R14~17 | TC-09~12,24,35 |
| R18~19, R21~24 | TC-13~16,25,30 |
| R20, R34 | TC-23,32 |
| R25~29 | TC-16~22 |
| R30, R36 | TC-26~27,32 |
| R31 | TC-15,24,35 |
| R32, R33, R35, R37 | TC-27~29,35 |
| R38~40, R44 | TC-30~33 및 아래 실측 산식; CI/fresh install gate |
| R43 | 담당자의 권한·명세 확인. 자동 테스트만으로 충족 판정하지 않음 |
| R45 | 모드별 실행 범위·SKIP/제외 사유 계약, TC-24,31 |
| R46 | 후속 접근성 검사 도구·검사 범위 선정 후 별도 TC. 현재 미계획/미실행 |

## 10. 신뢰성 검증과 포트폴리오 지표

합성 A/B 데모에 정상 화면, 다른 경로의 동일 기능, 다른 데이터의 동일 구조, HTTP 500, 필수 버튼 누락, 잘림, 검색 상태 유실, 위험 클릭 함정을 준비한다. 정답 라벨은 실행 전에 작성하고 별도 담당자가 검토한다. 개발용 fixture와 최종 평가 fixture를 분리해 임계값을 평가 데이터에 맞춰 조정하지 않는다.

| 지표 | 분모와 산식 | 주의 |
|---|---|---|
| page 발견 coverage | 등록된 기대 page 중 발견/기대 page | live 전체 page 분모가 없으면 coverage 수치 금지, 관측 수만 보고 |
| 매칭률 | 승인 가능한 대응 pair 중 매칭 pair | live에서는 발견 범위 내 비율이라고 표시; 오매칭도 별도 검수 |
| 행동 실행률 | 완료한 승인 행동/발견된 승인 행동 | 차단/미분류/미발견과 분리 |
| assertion 실행률 | 실제 기대식 평가까지 끝난 assertion/계획된 assertion | PASS/FAIL의 평가 완료 check가 기본 분자. 관찰만 있는 DIFF/REVIEW, 미평가 SKIP/BLOCKED/ERROR는 분자 제외하고 별도 수를 표시 |
| 탐지 precision | TP/(TP+FP) | 자동 경고를 고정 정의, BUG_CONFIRMED/정답 라벨과 대조 |
| false discovery 비율 | FP/(TP+FP) | 흔히 부르는 오탐 비율의 이 분모를 명시 |
| FPR | FP/(FP+TN) | 정상 ground truth 모집단이 있을 때만 계산 |
| seeded defect recall | TP/(TP+FN) | 중복 이벤트가 아닌 고유 결함 기준 |
| 재현률 | 동일 조건 재시도에서 같은 결함 재현/재시도한 확인 결함 | 환경·데이터 변화는 별도 분류 |
| flake 비율 | 동일 버전·fixture 반복에서 상태가 바뀐 check/반복 검사 check | 횟수·표본 수와 첫 실패를 보존 |
| 수동 대비 시간 | 같은 범위의 준비+실행+검수+재검 실측 | 자동 실행 시간만 비교하지 않음 |

분모 0은 0%가 아닌 N/A다. 미검수 DIFF/REVIEW는 FP/TN로 강제 분류하지 않는다. 지표와 CI 성공 횟수는 실험 후에만 채운다. 이번에 실행한 기존 단위 테스트 5개는 위 브라우저·성능·오탐 실험을 대신하지 않는다.
