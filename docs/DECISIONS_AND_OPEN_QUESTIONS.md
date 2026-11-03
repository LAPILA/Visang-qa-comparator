# 결정 기록과 미결정 질문

> 최초 설계 결정 기록입니다. **2026-11-03 v0.2의 구현·제한·검증 결과는 [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md), 확정 7상태·인터페이스·판정 계약은 [RESULT_CONTRACT](RESULT_CONTRACT.md)에 있습니다.** 아래 ADR의 5상태·예정 모듈 등은 최초 설계 시점 기록이며 현재 계약을 대체하지 않습니다.

> **2026-11-03 URL 확인 갱신:** 사용자가 4제품 × 운영/STG/바이브 개발/레거시 개발의 16개 주소를 제공했다. 현재 등록은 [ENVIRONMENT_URLS](ENVIRONMENT_URLS.md)와 `qa/environments.py`를 따른다. 중고등 모바일 STG는 `stg-mv.vivasam.com`으로 확인되어 과거의 미확정·오타 기록을 대체한다. 주소 등록과 실제 접속 검증은 구분한다.

작성일: 2026-10-30 (KST). 결정의 범위는 **설계 초안**이다. 코드 구현·서비스 정책 승인·배포 검증을 대신하지 않는다. 현재 상태는 [AS_IS_ARCHITECTURE.md](AS_IS_ARCHITECTURE.md), 판정/인터페이스의 기준은 [TEST_STRATEGY.md](TEST_STRATEGY.md), 담당/PR 계획은 [ROADMAP.md](ROADMAP.md)에 있다.

## 1. 자료 출처와 이번 작업의 경계

| 구분 | 경로·확인 사실 | 취급 |
|---|---|---|
| 산출물 저장소 | `C:/Users/ASUS/Documents/GitHub/Visang-qa-comparator` | 감사 시작 시 .git만 존재, main 커밋 없음. 이번 docs 작성 위치 |
| 사용자 지정 기획 원본 | `C:/Users/ASUS/Downloads/web-qa-planning-docs/web-qa-planning/QA_AUTOMATION_PROJECT_SPEC.md` | 목표/초안. 현재 구현 증거가 아님 |
| 사용자 지정 감사 원본 | 같은 폴더의 `CODEX_REPOSITORY_AUDIT_PROMPT.md` | 코드 변경 금지, 라인 근거·안전한 로컬 검증 요구 |
| 이전 Comparator (`OLD`) | `C:/Users/ASUS/Downloads/web-qa-comparator/web-qa-comparator` | 실제 분석한 구현; 아직 새 저장소로 이관하지 않음 |
| PC 샘플 (`EPC`) | `C:/Users/ASUS/Desktop/viva-e-pc` | 초등 PC 표본. Comparator 구현/운영 배포와 구분 |
| 모바일 샘플 (`MVMH`) | `C:/Users/ASUS/Desktop/viva-mv-mh` | 중고등 모바일 표본. 다른 두 제품의 구현까지 대표하지 않음 |

처음 발견한 Downloads 루트의 기획 두 파일과 사용자 지정 폴더의 파일은 SHA256이 동일했다. 기획 원문은 수정하거나 이 저장소로 복사하지 않았다. GitHub connector 404와 git 원격 조회 네트워크 실패가 있었으므로 원격 소스 상태는 확인 불가다. 원격 저장소가 비어 있거나 존재하지 않는다고 단정하지 않는다.

기획 원본 SHA256:

- SPEC: `96CF94F7E8BBA086B78D8E1800379A5A3B212313213B6082A8DDB1CBA9B923AF`
- AUDIT: `D980B1D6FDE726E6A92950E568FBAF03FB9F8E8A3E60012B1F316031CE820C85`

문서에 적힌 경로와 파일/라인은 로컬 감사 시점의 증거다. 다른 개발 PC에서 재현할 때 승인된 소스 위치를 다시 지정해야 한다. 원문 소스·실데이터·스크린샷을 공개 포트폴리오로 옮길 권한까지 이 감사 요청에 포함된 것으로 간주하지 않는다. 이번에는 커밋·푸시를 하지 않는다.

## 2. 비교 환경 등록표

주소는 **사용자가 제공한 값**이며 이번 감사에서 DNS·TLS·로그인·서비스 응답을 검증하지 않았다. 기본 A=운영/B=STG로 제안하지만 실행 시 명시적으로 바꿀 수 있고 역할을 저장한다.

| site_profile_id | 제품 | A 운영 시작점 | B STG 시작점 | 상태·주의 |
|---|---|---|---|---|
| elementary-pc | 초등 PC | `https://e.vivasam.com/main` | `https://stg-e.vivasam.com/main` | 제공 주소, 접속 미검증 |
| secondary-pc | 중고등 PC | `https://v.vivasam.com/` | `https://stg-v.vivasam.com/main` | `/`↔`/main`은 profile alias 후보, 내용/로그인 gate 확인 필요 |
| elementary-mobile | 초등 모바일 | `https://me.vivasam.com/#/` | `https://stg-me.vivasam.com/` | root/hash alias 후보. 해당 서비스의 router 구현 별도 확인 |
| secondary-mobile | 중고등 모바일 | `https://mv.vivasam.com/#/` | `https://stg-mvvivasam.com/` | **STG 철자 미확정. 자동 교정·자동 접속 금지**, 소유자가 정확한 URL 확인 |

특히 마지막 STG 값은 다른 서비스의 도메인 패턴과 다르지만 `stg-mv.vivasam.com`으로 임의 수정하지 않는다. 확인 전 해당 profile을 disabled로 둔다. 시작 URL 하나를 안다고 `*.vivasam.com` 전체 navigation 권한을 얻은 것은 아니다. navigation, 인증 SSO, 리소스/CDN 호스트 목록을 별도로 관리한다. 동일 URL이더라도 로그인 역할·학교급·검색 상태에 따라 다른 page state일 수 있다.

레거시↔신규 서버의 구체적인 pair는 아직 제공되지 않았다. 같은 engine과 별도 profile/mapping을 사용하되 운영↔STG의 별칭을 자동 재사용하지 않는다.

## 3. ADR 요약

| ADR | 상태 | 결정·이유 | 결과·재검토 조건 |
|---|---|---|---|
| ADR-01 | 설계 채택 | Python sync Playwright/Pillow/기존 JS UI 우선 유지. `OLD/app.py:19–24,281–298`에 핵심 흐름이 있음 | 전면 재작성 없이 test seam부터 추출. 병목 실측 후만 다른 runtime 검토 |
| ADR-02 | 설계 채택 | 현재 저장소와 OLD, 비교 대상 샘플을 분리 | source import는 다음 PR. 현재 docs의 구현 상태는 OLD에 한정 |
| ADR-03 | 설계 채택 | page class·instance·state 분리, hash 보존, 승인 alias | `OLD/app.py:56–74` 손실·분리 문제 해결. 외형만으로 자동 동일성 확정 금지 |
| ADR-04 | 설계 채택 | 클릭 후보 발견과 실행 권한 분리 | 기존 blacklist(`OLD/app.py:31–35,77–84`)만으로 안전 보장 불가. unknown 기본 SKIP |
| ADR-05 | 설계 채택 | LIVE 독립 계약이 기본, fixture/mock 별도 | DB 내용 차이는 결함 확정 근거가 아님. 마스킹과 구조 검사를 병행 |
| ADR-06 | 설계 채택 | 관찰·자동 5상태·심각도·QA 검수 상태를 분리 | 기존 `OLD/app.py:267–278`의 무검증 PASS를 방지. REVIEW를 버그로 집계하지 않음 |
| ADR-07 | 설계 채택 | 페이지 전체 대신 region/행동/check 증거 | `OLD/app.py:92–96,316–318`의 위치 부족 보완. 홈 공지/배너/메뉴 구분 |
| ADR-08 | 설계 채택 | 수동 로그인, ID 기억 opt-in, PW 비보존 | 기존 인증 기능 미구현(`OLD/app.py:201–203,288–291`). 사용자 요구에 맞춰 프로필·세션 분리 |
| ADR-09 | MVP 채택/후속 검토 | JSON manifest/result+PNG 우선, 저장 adapter 뒤에 SQLite 후보 | `OLD/app.py:36,331,389–395`의 재시작 손실 해결. 동시성·검색 필요가 커지면 transaction 저장 검증 |
| ADR-10 | 설계 채택 | 실행 threshold와 조회 diff 필터 분리 | `OLD/public/app.js:124–134,167–169`에 수치 조회 필터 없음. 필터가 판정을 바꾸지 않게 함 |
| ADR-11 | 설계 채택 | 명시 Python 시나리오 registry, 제한된 설정 JSON | 기존 sync 엔진 재사용. 임의 YAML 코드/LLM runtime 없이 재현 가능한 assertion |
| ADR-12 | 설계 채택 | 합성 데모 기반 CI/포트폴리오 | 회사 데이터 없이 정상·결함·허용차이 정답 세트로 신뢰성 측정 |

### ADR-08 상세: 수동 로그인과 아이디 기억

1. QA 담당자는 별도 브라우저 context에서 각 환경의 로그인 화면을 직접 조작한다. 최초 ID/PW를 입력하거나 사용자가 직접 붙여넣을 수 있게 한다. Comparator가 클립보드를 읽거나 비밀번호를 로그/설정/결과로 받지 않는다.
2. 로그인 중에는 screenshot/trace/network body/console 증거 수집을 비활성화하거나 안전한 수집 범위만 사용한다. 로그인 완료는 승인된 account marker와 역할로 확인한다. 비밀번호 입력값이나 인증 응답 원문을 성공 증거로 저장하지 않는다.
3. `아이디 기억`은 선택사항이다. 로컬 사용자별 설정에 사이트·환경·계정 별칭과 ID만 저장하며 접근 권한·보호 저장소를 적용한다. ID도 개인정보일 수 있으므로 report/export/Git에서 제외하고 지우기 기능을 제공한다. 기본 선택 여부는 제품 요구로 확정한다.
4. PW는 저장하지 않는다. 계정 기억과 로그인 세션 보존은 별개다. MVP는 현재 실행 세션 메모리만 유지하고, 세션 종료/만료 때 재로그인한다. “한 번 입력하면 영구 자동 로그인”을 약속하지 않는다.
5. 장기 세션 재사용이 필요하면 OS 보호 저장소/암호화·만료·철회·파일 권한을 별도 구현한 뒤 opt-in으로 제공한다. Playwright `storage_state`에는 계정으로 행동할 수 있는 인증 상태가 포함될 수 있으므로 Git에 올리지 않는다. [Playwright Authentication 공식 문서](https://playwright.dev/python/docs/auth).
6. A/B 및 두 QA의 context/profile/다운로드/artifact 경로를 격리한다. SSO가 있더라도 계정·쿠키를 서로 복사하지 않는다. MFA/CAPTCHA는 수동으로 처리하고 우회하지 않는다.

샘플의 ID 기억은 제품 구현의 참고 사례다. `EPC/src/main/webapp/templates/member/login.html:78–82,119–134`에는 ID cookie, `MVMH/frontend/src/containers/login/LoginForm.js:222–225,356–363`에는 savedId localStorage가 있다. 이것을 Comparator에 이미 구현됐다고 표시하거나 그대로 복제하지 않는다.

### ADR-05 상세: 400과 DB 차이에 대한 판단

“400과 DB 불일치는 모두 사소하다”는 전역 규칙은 채택하지 않는다. 예상한 잘못된 입력의 400은 정상 assertion일 수 있지만, 정상 검색의 필수 API 400은 기능 실패일 수 있다. DB의 내용·개수 차이는 기본 비교에서 제외해도, 목록이 사라지거나 상세가 잘못 연결되거나 버튼이 가려지는 문제는 계속 검사한다.

실제 두 DB의 차이 정도·스키마·동기화 상태는 이번 소스 읽기만으로 입증할 수 없다. 사용자의 “서버별 데이터가 다를 수 있음”을 환경 정책의 전제로 사용하고, 직접 DB 대조 완료라고 쓰지 않는다. 기존 수집은 같은 origin document/script/style만 FAIL, 외부·XHR/fetch는 대개 REVIEW다(`OLD/app.py:124–135`). 401/403 일괄 FAIL이라고 잘못 설명하지 않는다.

## 4. 샘플 코드 읽기 인덱스 — 복사 대신 테스트 계약 추출

샘플은 빌드/실행하지 않았다. 아래 라인은 특정 기능이 소스에 있다는 근거이며 실제 서비스 정상 작동·Comparator 검사 완료의 근거가 아니다. 민감 설정 파일·DB 자격증명은 문서로 옮기지 않았다.

| 표본 | 파일·라인 | 확인된 코드 구조 → 테스트 설계 |
|---|---|---|
| PC stack | `EPC/pom.xml:8–21,39–54,91–109,111–156` | Java8/Spring Boot2.5/WAR/MVC/Thymeleaf/MyBatis·로컬 JAR → 샘플만으로 독립 빌드 재현 보장 금지 |
| 모바일 stack | `MVMH/build.gradle:11–23,29–44,107–110`; `MVMH/frontend/package.json:5–48` | Java8/Spring4.3.25/WAR + React16.5.2/router4.3.1/Redux/Axios → Comparator의 기술 스택과 분리 |
| hash 라우팅 | `MVMH/frontend/src/index.js:3,104–134,175–177`; `MVMH/frontend/src/App.js:158–176` | hash 및 직접 진입 변환, 교과서·검색·공지 → route/state/instance 보존 |
| 홈 영역 | `EPC/src/main/java/com/vivasam/elementary/mvc/controller/MainController.java:94–120` | 배너·시즌 자료·공지 service 결과 → home.notice/banner/navigation별 계약 |
| 공지 PC | `EPC/src/main/webapp/templates/support/notice/list.html:26–50,61–101` | keyword/page GET 검색, 빈 결과·noticeId/title/date → 각 서버 내 렌더·상세 연결 |
| 공지 모바일 | `MVMH/frontend/src/containers/cs/NoticeListContainer.js:23–50,94–103,109–129` | API·지연 렌더·학교급·더보기 → ready·필터·페이지 상태 및 href 없는 후보 |
| 검색 | `MVMH/frontend/src/components/main/MainSearch.js:26,30,64,80,94–96`; `MVMH/frontend/src/containers/main/MainSearchContainer.js:54–100,117–177` | Enter/버튼·자동완성·검색 history·Redux → 상태/이벤트 구분, 기록 삭제 기본 차단 |
| 뒤로가기 | `MVMH/frontend/src/pages/cs/NoticePage.js:7–28` | 상세/목록/direct entry의 history 처리 → UI back과 browser back 별도 TC |
| 길이 제한 | `MVMH/frontend/src/components/login/JoinSearchBelongPopup.js:248–255`; `EPC/src/main/webapp/templates/member/login.html:368` | maxlength 속성 존재 → 명세 단위 확인, 가입·비밀번호 제출을 범용 crawler에서 실행 금지 |
| 다운로드 | `MVMH/frontend/src/components/common/DownloadInfo.js:30–48,66–81`; `MVMH/frontend/src/lib/api.js:1092–1098` | 동적 anchor·새 창·이력 POST → 단순 링크 클릭으로 분류 금지 |
| 자료 popup | `EPC/src/main/java/com/vivasam/elementary/mvc/controller/textbook/TextbookDownloadController.java:54–76,111–123`; `EPC/src/main/webapp/templates/textbook/download.html:1–4,21–31` | popup route·자료 ID → 승인 자료·모달/새 탭/파일 구분 |
| 방문 로그 | `MVMH/frontend/src/index.js:54–78` | beacon/POST 로그 → 모든 쓰기 차단과 정상 서비스 관찰을 동일시하지 않음 |

다음 개발에서는 이 표에서 **공개 가능한 합성 route·selector 계약·기대 결과**를 직접 작성한다. 기업 소스를 examples에 복사하거나 실제 공지·교과자료를 fixture로 만들지 않는다.

## 5. 미결정 질문과 안전한 기본값

질문은 후속 구현 착수 전에 담당자가 결정 로그에 답을 남기기 위한 것이다. 이번 문서 작성은 이 답변을 기다리지 않고 완료한다.

| ID | 확인할 질문 | 담당·확정 시점 | 미확정일 때 기본값·영향 |
|---|---|---|---|
| Q-01 | 중고등 모바일 STG의 정확한 호스트는 무엇인가? | 사용자/서비스 담당, live profile 등록 전 | 해당 profile disabled; 임의 도메인 교정 금지 |
| Q-02 | 운영/STG별 허용 계정·역할·SSO 호스트와 자동 조회 범위는? | 사용자/서비스 담당, live 실행 전 | 합성 데모만 실행; 보호 페이지는 SKIP |
| Q-03 | 아이디 기억 기본 체크 여부·보존 기간·공용PC 정책은? | 사용자+B, auth UI 구현 전 | opt-in/개인 로컬; PW 미저장; 세션 메모리만 |
| Q-04 | URL이 다를 때 동일 기능을 확인할 menu/heading/고유 anchor는? | A+B QA, mapping 승인 전 | 후보 REVIEW, 수동 확정 전 자동 동일성 주장 금지 |
| Q-05 | 입력 N의 단위, 공백 처리, 초과시 절단/오류 정책은? | B/제품 담당, length TC 전 | 속성 관찰만; 요구 미정 REVIEW, 데모 fixture와 구분 |
| Q-06 | 새로고침/back/UI back에서 검색·탭·스크롤을 얼마나 보존해야 하나? | B/제품 담당, history TC 전 | 요구 미정 REVIEW; 코드 현재 동작을 정답으로 고정 금지 |
| Q-07 | 공지·배너·교과자료의 동적 region과 공통 필수 구조는? | B QA, region adapter 전 | 내용값 비교 제외하되 알려진 구조 검사 유지 |
| Q-08 | 401/403/400·외부 위젯의 예상 endpoint와 기능 중요도는? | A+B/서비스 담당, 예외 rule 전 | 광역 ignore 금지; 관찰 보존+REVIEW |
| Q-09 | 다운로드의 이력 기록 허용·시험자료·크기/횟수 한도는? | 사용자/서비스 담당, live download 전 | live 자동 실행 SKIP, 합성 파일로 검증 |
| Q-10 | 한도/간격·운영 실행 시간대·rate limit 정책은? | 서비스 담당+A, live scan 전 | TEST_STRATEGY 초안은 제안치; 확인 전 live 광역 탐색 금지 |
| Q-11 | 두 사람이 별도 PC/로컬 실행인가, 하나의 공유 서버인가? | 사용자, 공유 운영 전 | 각자 로컬 실행+operator별 비밀 제거 report 공유 |
| Q-12 | 결과·trace·다운로드의 보관 기간과 삭제 책임자는? | 사용자+B, 실자료 보존 전 | 최소 필요 증거만 로컬; 미정 민감자료 export 차단 |
| Q-13 | source/사이트/화면 공개 허용 및 라이선스는? | 사용자/회사, 공개 포트폴리오 전 | 합성 데모만 공개, 내부 소스·URL·계정·실자료 제외 |
| Q-14 | 공통 fixture 준비 권한/데이터와 legacy↔new pair는? | 사용자/서비스 담당, 정밀비교 전 | LIVE 독립 계약 유지, 정확한 DB 값 대조 안 함 |
| Q-15 | 시각 임계값·폰트·브라우저 지원 범위는? | A+B, baseline 승인 전 | 단일 검증 Chromium 환경, 차이는 REVIEW; 수치는 실험 후 교정 |

## 6. 기획 원본에 대한 수정 제안 — 원본은 보존

| 원본 근거 | 제안 | 이유 |
|---|---|---|
| SPEC:50,71 | 검수 enum을 `RETEST_REQUIRED`로 통일, `NEEDS_RETEST`는 입력 alias. 정상 PASS 표본의 검수 완료는 `VERIFIED_OK` 추가 제안 | 두 표현 혼재와 정상 표본의 오탐 집계 방지 |
| SPEC:78–82 | hash-router identity, query 반복 순서, root 인증 gate 추가 | 실제 모바일 코드와 OLD 함수 재현에서 중요성 확인 |
| SPEC:113–128 | SQLite는 후속 저장 adapter 후보로 표현 | 현재 JSON 보존도 없고 로컬 단일 worker 재사용이 우선 |
| SPEC:89–94,102 | 다운로드 이력·telemetry/조회 POST·unknown 행동 정책 보완 | GET/POST만으로 안전 구분 불가 |
| SPEC:154–158 | ID 기억과 세션 재사용을 분리, 로그인 중 캡처 제외 명시 | 사용자 입력 요구와 증거 보안 충족 |
| SPEC:176–184 | 1주 범위를 한 제품 프로필+2~3 시나리오로 제한 | 4제품·모든 클릭 동시 완성의 과도한 범위 방지 |

## 7. 이번 감사에서 확인하지 않은 것

실사이트 현재 화면/배포 버전/권한/HTTP 오류 재현, DB 실제 불일치 범위, 브라우저 E2E, 성능·부하·오탐률·탐지율, 두 사람 실제 동시 사용, 완전한 보안 감사, 4제품 전체 소스 대표성은 확인하지 않았다. 이전 PNG 파일이 있다는 사실은 실행 설정·성공률·성능의 증거가 아니다.

확인한 것은 실제 소스의 제어 흐름, 로컬 함수의 합성 입력 재현, 기존 5개 단위 테스트 및 문서/코드 연결이다. 다음 구현 단계의 검증과 혼동하지 않는다.
