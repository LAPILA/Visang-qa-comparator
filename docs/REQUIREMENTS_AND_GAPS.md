# 요구사항 대비 구현 현황과 격차

> **아래 매트릭스는 구현 전 OLD 버전의 감사 결과입니다.** 후속 MVP 구현 현황은 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)에 별도로 기록합니다. 과거 코드의 라인 근거를 현재 코드로 오인하지 마세요.

작성일: 2026-10-30 KST · 최초 작업 범위: 읽기 전용 코드 감사와 설계 문서 작성. 8절은 후속으로 선택한 추가 요구사항이며 OLD 감사 결과와 구분한다.

## 1. 감사 대상과 판정 범위

**현재 Git 저장소에는 감사 시작 시 `.git`만 있었고 커밋·실행 소스가 없었다. 아래의 구현 판정은 Downloads에 있는 이전 Comparator에 관한 것이며, 현재 저장소에 기능이 구현되어 있다는 뜻이 아니다.** GitHub 연결의 저장소 조회는 404였으므로 원격 코드·브랜치·CI 상태는 확인 불가다. 로컬 상태와 원격 상태를 동일시하지 않는다.

| 표기 | 실제 위치와 역할 |
|---|---|
| `CURRENT` | `C:\Users\ASUS\Documents\GitHub\Visang-qa-comparator` — 이번에 설계 문서만 작성하는 저장소 |
| `OLD/` | `C:\Users\ASUS\Downloads\web-qa-comparator\web-qa-comparator\` — 실제 구현을 감사한 이전 시제품 |
| `SPEC/` | `C:\Users\ASUS\Downloads\web-qa-planning-docs\web-qa-planning\` — `QA_AUTOMATION_PROJECT_SPEC.md`, `CODEX_REPOSITORY_AUDIT_PROMPT.md` 원본 |
| 대상 사이트 샘플 | `C:\Users\ASUS\Desktop\viva-e-pc`, `C:\Users\ASUS\Desktop\viva-mv-mh` — 검사 대상 애플리케이션의 참고 소스. Comparator의 구현으로 세지 않는다. |

`SPEC`의 두 파일은 먼저 발견한 Downloads 루트의 동명 파일과 SHA-256이 동일함을 확인했다. 기획서는 목표이며 구현 증거로 사용하지 않았다. 구현 증거는 아래 `OLD/파일:시작–끝 라인`으로 표시한다. 미구현 판단의 라인 범위는 해당 책임을 현재 처리하는 코드를 가리키며, 해당 함수만으로 저장소 전체의 부재를 증명한다는 뜻은 아니다. 이전 버전 전체 파일 목록과 서버·UI·테스트 경로를 함께 조사했다.

주요 원본: [app.py](C:/Users/ASUS/Downloads/web-qa-comparator/web-qa-comparator/app.py), [UI JavaScript](C:/Users/ASUS/Downloads/web-qa-comparator/web-qa-comparator/public/app.js), [입력·결과 화면](C:/Users/ASUS/Downloads/web-qa-comparator/web-qa-comparator/public/index.html), [단위 테스트](C:/Users/ASUS/Downloads/web-qa-comparator/web-qa-comparator/tests/test_core.py), [기획서](C:/Users/ASUS/Downloads/web-qa-planning-docs/web-qa-planning/QA_AUTOMATION_PROJECT_SPEC.md).

판정 용어:

- **구현됨**: 해당 범위의 동작 경로를 실제 코드에서 확인했다. 운영 사이트에서 검증되었다는 뜻은 아니다.
- **부분 구현**: 일부 경로는 있으나 요구 범위·실패 처리·재현성 조건을 충족하지 못한다.
- **미구현**: 조사한 이전 버전에서 해당 실행 경로·정책·저장 모델을 찾지 못했다.
- **확인 불가**: 코드만으로 알 수 없는 외부 사실, 요구 명세 또는 측정 결과다.
- 우선순위 **P0**는 잘못된 판정·안전·증거 손실 방지, **P1**은 1주 MVP의 핵심 기능, **P2**는 안정화·포트폴리오 확장이다. P0라고 모두 첫 주에 완성한다는 뜻은 아니다.

전체 호출 흐름과 재사용 대상은 [AS_IS_ARCHITECTURE.md](AS_IS_ARCHITECTURE.md), 목표 정책과 테스트 명세는 [TEST_STRATEGY.md](TEST_STRATEGY.md), 담당자·PR·인수 조건은 [ROADMAP.md](ROADMAP.md)를 따른다.

## 2. 요구사항 추적표

기획서 대응: 탐색·매칭 `SPEC/QA_AUTOMATION_PROJECT_SPEC.md:75–83`, 기능 `:85–103`, 데이터·시각 `:105–111`, 결과·검수 `:67–73`, 품질 `:152–160`, 단계·협업 `:162–194`.

| ID | 요구사항 | OLD 상태 | 실제 코드 근거 | 현재 동작 / 부족한 점 | 권장 개선 | 우선순위 |
|---|---|---|---|---|---|---|
| R01 | 로컬 설치·실행과 의존성 재현 | 부분 구현 | `OLD/README.md:5–21`; `OLD/requirements.txt:1–2`; `OLD/app.py:448–456` | Python 서버와 설치법 존재. 의존성 범위만 지정하고 확정 버전·브라우저 빌드 고정 없음 | 검증 버전과 설치·브라우저 정보를 run manifest에 기록 | P1 |
| R02 | 두 시작 URL 입력과 기본 유효성 검사 | 구현됨 | `OLD/public/index.html:20–27`; `OLD/app.py:45–59, 423–430` | http/https·hostname 검사, URL 내 자격증명 거부. 두 URL을 API에 전달 | 기존 검사를 재사용하고 허용 호스트 정책을 별도로 추가 | P1 |
| R03 | 양쪽 서버 독립 탐색·세션 분리 | 구현됨 | `OLD/app.py:199–231, 293–296` | A와 B를 각각 새 context로 순차 탐색 | 각 환경의 결과를 독립 검사 결과로 보존 | P1 |
| R04 | 페이지·깊이·시간·동작·속도 제한 | 부분 구현 | `OLD/app.py:29, 199–228, 426–430` | 페이지 수·깊이·대기 제한 일부 존재. 전체 시간·행동 예산·host별 속도 제어 없음 | 전역 예산과 종료 사유, 미실행 항목 기록 | P0 |
| R05 | 허용 호스트·위험 동작 차단 | 부분 구현 | `OLD/app.py:31–34, 77–84, 163–165` | same-origin과 URL 문자열 denylist. 허용 서브도메인·동작 위험등급·네트워크 정책 없음 | 환경별 allowlist와 동작별 사전 승인 규칙 | P0 |
| R06 | SPA hash 라우트 발견·구분 | 미구현 | `OLD/app.py:56–59, 67–74, 222–226`; `OLD/tests/test_core.py:11–14` | fragment 전체 제거. `/#/notice`와 `/#/search`의 경로 키가 모두 `/` | SPA route hash와 문서 앵커를 구분하는 사이트 프로필 | P0 |
| R07 | 버튼·JS 메뉴·탭의 안전한 발견·실행 | 미구현 | `OLD/app.py:103–115, 219–226`; `OLD/README.md:31, 35` | `a[href]`만 수집하고 goto로 방문. 버튼 클릭·상태 그래프 없음 | 후보 inventory와 allowlisted action runner 분리 | P1 |
| R08 | 등록 경로·프레임·미발견 후보의 제한적 재확인 | 미구현 | `OLD/app.py:103–115, 199–228, 300–318` | 시작 URL과 발견 링크만 사용. 프레임 탐색·등록 경로·상대 환경 재확인 없음 | profile seed routes와 상한 있는 candidate probe | P2 |
| R09 | URL 정규화·의미 있는 쿼리 보존 | 부분 구현 | `OLD/app.py:56–74`; `OLD/tests/test_core.py:11–18` | query 정렬·추적값 제외·trailing slash 처리. 라우트 유형·데이터 ID 분리 없음 | `page_class`와 `instance_key` 분리, 충돌 회귀 테스트 | P0 |
| R10 | `.do` 등 명시적 라우트 별칭 | 미구현 | `OLD/app.py:67–74, 300–306`; `OLD/README.md:32, 53` | 상대 경로와 query가 같아야 매칭. `.do` 유무는 다른 키 | 승인된 양방향 별칭 테이블, 충돌 시 REVIEW | P1 |
| R11 | 다른 경로의 동일 기능 후보·수동 확정 | 미구현 | `OLD/app.py:300–318`; `OLD/public/app.js:84–122` | title·h1·UI 유사도로 후보 추천하지 않으며 매핑 승인 UI도 없음 | 메뉴·구조 신호로 후보 제시, 확정·근거·버전 저장 | P1 |
| R12 | 두 시작 페이지의 기능적 동치 확인 | 부분 구현 | `OLD/app.py:67–69, 204, 210, 301–306` | 양쪽 시작 URL을 무조건 `__ROOT__`로 묶음 | 시작 URL도 page type·필수 요소·인증 상태 확인 | P0 |
| R13 | 미발견·접근불가·실제 404 구분 | 부분 구현 | `OLD/app.py:160–165, 192–193, 309–310`; `OLD/public/app.js:59–60` | 한쪽 없으면 ONLY 플래그. 예산 소진·미발견·권한 원인별 상태 없음 | discovery 상태와 match 상태를 분리하고 사유 기록 | P0 |
| R14 | HTTP 상태·resource type·출처 수집 | 부분 구현 | `OLD/app.py:124–137, 156–162` | 응답 4xx/5xx와 종류·출처를 수집하나 일부는 message 문자열에 묶임 | method·status·resourceType·origin·initiator를 구조화 | P1 |
| R15 | 예상 401/외부 403/실제 실패의 정책 분리 | 부분 구현 | `OLD/app.py:129–135, 160–162` | 동일 출처 document/script/stylesheet는 FAIL, 그 외는 REVIEW. 계약 기반 예외 없음 | endpoint·method·상태·시나리오·만료일 있는 예외 규칙 | P0 |
| R16 | JS 예외·콘솔 오류 수집·정제 | 부분 구현 | `OLD/app.py:92–96, 149–153` | pageerror=FAIL, console error=REVIEW. 최대 35 issue와 단순 중복 제거 | 원시 이벤트 보존·fingerprint·반복 횟수·분류 근거 | P1 |
| R17 | 네트워크 실패·탐색 실패 분리 | 부분 구현 | `OLD/app.py:139–147, 190–195` | document 요청 실패와 visit 예외를 FAIL. 테스트 도구 실패도 NAVIGATION_ERROR로 섞일 수 있음 | 제품 장애와 runner ERROR 구분, 단계별 예외 처리 | P0 |
| R18 | 안정적 스크린샷·PC/모바일 환경 | 부분 구현 | `OLD/app.py:30, 166–187, 201–203` | 고정 PC viewport, 애니메이션·caret 제어. viewport 캡처만, 모바일 프로필·명시적 ready 조건 없음 | 기기 프로필·렌더링 준비 조건·요소 캡처 | P1 |
| R19 | 이미지 차이율·실패 처리 | 부분 구현 | `OLD/app.py:234–257, 267–278`; `OLD/tests/test_core.py:36–45` | Pillow 차이율·overlay 있음. 비교 실패/크기 불일치가 PASS로 통합될 수 있음 | diff check 결과와 비교불가 ERROR를 명시 | P0 |
| R20 | 결과의 차이율 범위 필터 | 미구현 | `OLD/public/index.html:37–38, 62–67`; `OLD/public/app.js:124–134` | 설정값은 실행 판정 threshold. 조회 필터는 상태·문자열뿐 | 차이율 min/max와 null 전용 필터; 원래 판정 유지 | P1 |
| R21 | DOM·CSS·위치·겹침·잘림 검증 | 미구현 | `OLD/app.py:103–115, 234–257, 276–277` | h1 텍스트 비교와 이미지 diff만. bounding box는 깨진 이미지 식별에만 사용 | selector별 존재·박스·스타일·overflow 계약 | P1 |
| R22 | 페이지 내부 영역·컴포넌트 단위 보고 | 미구현 | `OLD/app.py:92–96, 300–318`; `OLD/public/app.js:84–111` | URL key 한 개당 한 행. 공지·배너 등 영역과 행동 단계 없음 | region_id·scenario_id·step_id·check_id별 증거 연결 | P1 |
| R23 | 서버별 실데이터 차이 정책 | 미구현 | `OLD/app.py:234–257, 267–278`; `OLD/README.md:33–34` | DB 직접 비교는 없지만 데이터 변화도 픽셀/h1 차이에 포함 | 기본값은 환경별 계약 검증; 내용 차이는 INFO 관찰 | P1 |
| R24 | 공통 fixture·Mock 비교 모드 | 미구현 | `OLD/app.py:281–325`; `OLD/tests/test_core.py:36–60` | 단위 테스트의 합성 이미지·mock visit은 제품의 fixture/Mock 실행 기능이 아님 | 합성 데모 fixture부터 도입, live 검사와 모드 분리 | P2 |
| R25 | 시나리오 registry·runner·assertion 계약 | 미구현 | `OLD/app.py:119–231, 281–325` | 페이지 방문과 캡처만 있음. 준비·행동·기대결과·정리 단계 없음 | 기존 Playwright에 얇은 시나리오 API 추가 | P1 |
| R26 | 검색·정렬·필터·페이지네이션 검사 | 미구현 | `OLD/app.py:103–115, 155–195`; `OLD/README.md:31, 52` | 검색 입력·버튼/엔터 실행·결과 상태 assertion 없음 | 환경별 표본으로 명세가 있는 검색 1개부터 구현 | P1 |
| R27 | 글자 수 경계·한글·이모지·붙여넣기 | 미구현 | `OLD/app.py:103–115, 155–195`; `OLD/tests/test_core.py:10–60` | 입력 조작·N−1/N/N+1·길이 단위 검증 없음 | 정식 명세 N과 길이 단위를 먼저 확정, DOM 속성은 관찰 | P1 |
| R28 | 새로고침·뒤로/앞으로·상태 복원 | 미구현 | `OLD/app.py:122, 156, 194–195` | 페이지마다 new_page/goto/close. 사용자 이력 동작 없음 | 검색→상세→뒤로가기/새로고침 시나리오 | P1 |
| R29 | 팝업·다운로드 기능 검증 | 미구현 | `OLD/app.py:31–34, 149–153, 201–203` | download 경로 차단, accept_downloads=False. popup/dialog/download 이벤트 검사 없음 | 승인된 시나리오에서 이벤트·파일 metadata·창 lifecycle 검사 | P2 |
| R30 | 수동 로그인·ID 기억·비밀정보 비보존 | 미구현 | `OLD/public/index.html:19–43`; `OLD/app.py:201–203, 287–291` | 인증 입력·headed 로그인·storageState·ID 기억 기능 없음 | 첫 로그인 수동 입력, ID만 선택 저장; 암호·토큰 제외 | P1 |
| R31 | PASS/FAIL/REVIEW/SKIP/ERROR 5상태 | 부분 구현 | `OLD/app.py:267–278, 321–322, 328–342`; `OLD/public/index.html:55–66` | 결과 행은 3상태. job.state=error는 check ERROR와 다름 | assertion 결과와 job lifecycle 분리, 미실행 PASS 금지 | P0 |
| R32 | QA 최종 검수·할당·이력 | 미구현 | `OLD/public/app.js:84–122, 183–190`; `OLD/app.py:415–445` | 상세 열람만 가능, POST는 scan 생성뿐 | 검수 actor·reason·revision·재검 링크 저장 | P1 |
| R33 | 결과·증거의 영속 저장·재시작 복구 | 부분 구현 | `OLD/app.py:27, 36–38, 182–189, 251–255, 331, 389–395` | PNG 저장. job/report는 메모리라 재시작 후 판정·CSV 접근 소실 | 결과 manifest와 검수 저장소를 먼저 도입 | P0 |
| R34 | CSV/HTML 보고서·필터·오류 검색 | 부분 구현 | `OLD/app.py:345–349, 387–412`; `OLD/public/app.js:124–143` | CSV 있음. 독립 HTML·검수 export 없음. 검색은 메시지/제목 제외. 숫자 0 CSV 손실 | 내보내기 schema 고정, 0/null 구분, region/검수 포함 | P1 |
| R35 | 2인 실행·검수 구분과 충돌 처리 | 부분 구현 | `OLD/app.py:36–38, 434–444` | 한 프로세스 ACTIVE_JOB 1개, 다음 요청 409. actor/workspace/검수 버전 없음 | MVP는 각자 로컬 실행·고유 run ID; 검수 충돌 정책 명시 | P1 |
| R36 | 자격증명·PII·산출물 보호 | 부분 구현 | `OLD/app.py:45–52, 92–96, 182–189, 379–393, 448–450`; `OLD/.gitignore:1–4` | loopback 바인딩·URL 자격증명 거부·runs/.env 제외. URL/log/screenshot 마스킹·보존주기 없음 | capture 전 마스킹·비밀값 제거·로컬 저장 제한·정리 정책 | P0 |
| R37 | 재현 manifest·trace·버전 증거 | 부분 구현 | `OLD/app.py:201–203, 323–325, 438–439` | 설정 일부·시각·URL 있음. 코드/브라우저/규칙/fixture 버전·trace 없음 | 실행 조건과 정책 hash를 결과에 연결 | P1 |
| R38 | 자동화 자체의 테스트 신뢰성 | 부분 구현 | `OLD/tests/test_core.py:10–60` | 함수 단위 5개. 브라우저 통합·UI·API·실패 주입·복구 검증 없음 | 정상/결함 합성 데모, 경계값·오탐·실패 처리 테스트 | P0 |
| R39 | 저장소 CI와 공개용 합성 데모 | 미구현 | OLD 전체 파일 목록과 `OLD/README.md:39–61`; `OLD/tests/test_core.py:10–60` | OLD에서 CI workflow·합성 사이트 없음. CURRENT에는 실행 소스 없음 | 사내 샘플 복사 없이 fixture demo와 CI 추가 | P2 |
| R40 | 탐색·매칭·실행 검증·SKIP 커버리지 | 부분 구현 | `OLD/app.py:319–325`; `OLD/public/app.js:135–141` | 방문 수·페이지 행 상태만 집계. 발견/미방문/행동/assertion 분모 없음 | 측정 단위별 분모와 미실행 이유를 구분 | P1 |
| R41 | 실행 취소·전역 타임아웃·재시도 이력 | 미구현 | `OLD/public/app.js:147–156`; `OLD/app.py:328–342, 415–445` | polling은 done/error까지 반복. cancel endpoint·deadline·시도별 기록 없음 | 취소 토큰·정리 보장·재시도 예산과 원래 실패 보존 | P2 |
| R42 | PC/모바일 4쌍 환경 프로필 | 미구현 | `OLD/public/index.html:20–38`; `OLD/app.py:30, 201–203` | URL 2개 임의 입력과 고정 PC 설정. 쌍·기기·라우트·인증 정책 없음 | 제공 URL을 검증 전 후보로 등록, 오타 의심 host는 확정 전 실행 제외 | P1 |
| R43 | 실제 서버 권한·계정·로그인·정식 기능 명세 | 확인 불가 | `OLD/README.md:31, 35–36`; `OLD/public/index.html:19`; SPEC는 목표 명세 | 실제 서버 로그인·크롤링을 이번 감사에서 하지 않음. 샘플 코드만으로 운영 요구 확정 불가 | 담당 QA가 계정권한·테스트 대상·길이/상태유지 명세 확인 | P0 |
| R44 | 성능·오탐률·재현 성공률·수동 대비 절감 | 확인 불가 | `OLD/tests/test_core.py:10–60`; `OLD/app.py:319–325` | 측정 실험·판정 정답셋·동일 조건 수동 비교 자료 없음 | [ROADMAP.md](ROADMAP.md)의 실험 설계 후 실제 값만 공개 | P2 |
| R45 | 빠른 탐색/화면/시나리오/조합 실행 유형 선택 | 부분 구현 | `OLD/public/index.html:19–43`; `OLD/app.py:281–325, 423–430` | 탐색+화면 비교의 단일 흐름만 존재. 기능 시나리오 모드와 유형 선택 없음 | run_mode와 모드별 계획 check/제외 범위를 manifest에 기록 | P1 |
| R46 | 선택적 기본 접근성 검사 | 미구현 | `OLD/app.py:103–115, 119–196`; `OLD/tests/test_core.py:10–60`; `SPEC/QA_AUTOMATION_PROJECT_SPEC.md:160` | 접근성 자동 검사·키보드/스크린리더 검증 경로 없음 | 안정화 이후 선택 도구·범위 평가, 자동 검사만으로 WCAG 적합성 주장 금지 | P2 |

이 표에서 상태가 구현됨인 R02/R03도 해당 범위에 한정된다. 예를 들어 URL을 두 개 받는 것과 안전한 모든 호스트 탐색, context를 나누는 것과 인증 세션 관리 완료는 서로 다른 요구사항이다.

## 3. 확인된 결함, 설계 위험, 아직 확인하지 않은 현상

### 3.1 코드 경로 또는 로컬 함수 실행으로 확인한 결함

| ID | 결함과 재현 조건 | 근거 / 확인 수준 | 영향 |
|---|---|---|---|
| D01 | 양쪽 issue가 없고 h1이 같을 때, diff가 `None` 또는 `differencePercent=None`이면 PASS | `OLD/app.py:234–257, 267–278`; 로컬 함수 직접 호출로 PASS 확인 | 비교 미실행·실패를 정상으로 오인 |
| D02 | `/#/notice`, `/#/search`가 같은 `/` 경로 키가 됨 | `OLD/app.py:56–59, 67–74, 222–226`; 로컬 함수 직접 호출 확인 | 모바일 SPA 화면 합쳐짐·누락 가능 |
| D03 | `/qbank/gate/qbank_subject.do`와 확장자 없는 경로의 key가 다름 | `OLD/app.py:67–74, 300–310`; 로컬 함수 직접 호출 확인 | 같은 기능이어도 두 ONLY 행, 이미지 비교 불가 |
| D04 | 화면 차이 설정은 결과 차이율 필터로 동작하지 않음 | `OLD/public/index.html:37–38`; `OLD/public/app.js:124–134, 167–169`; 정적 확인 | 사용자가 차이율로 결과를 좁힐 수 없음 |
| D05 | 결과는 URL key 하나에 모든 issue와 viewport diff를 묶음 | `OLD/app.py:92–96, 300–318`; `OLD/public/app.js:84–111`; 정적 확인 | 공지·배너·검색창 등 문제 위치 특정이 어려움 |
| D06 | 서버 재시작 시 job/report 접근 소실 | `OLD/app.py:36–38, 331, 389–395, 437–441`; 저장 구조의 정적 확인, 실제 재시작 실험 미실시 | 이미지와 판정·입력·검수의 추적성 단절 |
| D07 | 차이율 0을 CSV로 내보내면 빈 문자열이 됨 | `OLD/app.py:345–346, 405–408`; `csv_safe(0)` 직접 호출로 `''` 확인 | 정확히 0%와 계산 불가 구분 소실 |

D01의 구분이 중요하다. 스크린샷 **캡처 실패**는 `SCREENSHOT_ERROR` issue를 만들어 REVIEW가 된다(`OLD/app.py:185–191`). 반면 캡처 후 **이미지 비교 실패·크기 불일치**는 note만 반환하므로 통합 판정에서 PASS로 빠질 수 있다. 모든 실패가 동일하게 처리된다고 적으면 부정확하다.

### 3.2 아직 사고 발생을 입증하지 않은 설계 위험

| ID | 위험 | 코드 근거 | 필요한 통제 / 검증 |
|---|---|---|---|
| K01 | URL denylist를 통과한 GET·페이지 JS도 서버 상태를 바꿀 수 있음 | `OLD/app.py:31–34, 77–84, 156` | 경로·동작 허용 정책, 합성 서버에서 요청 부작용 차단 테스트 |
| K02 | 시간·배너·공지·폰트·데이터 차이가 전체 화면 차이에 섞임 | `OLD/app.py:166–187, 234–245` | 안정화 조건·영역별 정책·실데이터 구조 검사; 실제 오탐률은 미측정 |
| K03 | grayscale 차이와 고정 픽셀 기준 25가 미세한 색 차이를 놓칠 수 있음 | `OLD/app.py:242–245` | 승인된 색/크기 fixture로 알고리즘 특성 검증; 즉시 교체 결론은 보류 |
| K04 | 처음 입력한 두 페이지가 다른 기능이어도 root끼리 비교 | `OLD/app.py:67–69, 204, 301–306` | 기능 identity·필수 요소·인증 상태 검증 |
| K05 | A/B의 기존 오류와 신규 회귀가 하나의 FAIL로 합쳐짐 | `OLD/app.py:267–269, 307–318` | 환경별 검사와 A/B 비교 결과 분리; baseline 오류도 숨기지 않음 |
| K06 | issue 상한 35개 이후 이벤트 손실, 수집 예외 묵살 | `OLD/app.py:92–96, 124–147` | 원시 이벤트·집계·truncated/collector error 표시 |
| K07 | 화면·URL·오류 문자열에 비밀·개인정보가 포함될 수 있음 | `OLD/app.py:92–96, 182–189, 263–264, 379–393` | redaction·접근·보관·삭제 정책; 이번 감사에서 실제 유출은 조사/확정하지 않음 |
| K08 | 재현 조건이 고정되지 않아 다른 설치에서 결과가 달라질 수 있음 | `OLD/requirements.txt:1–2`; `OLD/app.py:289–290, 323–325` | 확정 버전·브라우저 빌드·환경 설정·규칙 버전 기록 |
| K09 | 두 작업자가 같은 서버를 사용하면 두 번째 실행 거절 | `OLD/app.py:434–444` | 첫 주에는 각자 local runner, 결과 식별과 검수 담당 분리; 공유 queue는 후속 |
| K10 | READY 조건 불충분·동적 UI 지연으로 화면을 너무 일찍 수집할 가능성 | `OLD/app.py:166–175` | 페이지별 readiness와 timeout 사유·상태 스냅샷; 무조건 sleep 증가는 해결책 아님 |

### 3.3 실제 사이트에서 재현하지 않은 사항

- 제공된 운영/STG URL의 현재 접속 가능 여부, 로그인 과정, 메뉴·검색·다운로드 동작은 확인하지 않았다. 이번 단계는 코드 감사이며 외부 운영/STG 크롤링을 실행하지 않았다.
- 사용자가 제시한 중고등 모바일 STG host 표기는 다른 환경과 형태가 달라 확인이 필요하다. 유사한 도메인을 추측해 자동 교정·접속하지 않는다.
- Desktop 샘플의 selector·maxlength·라우트는 구현 관찰 자료다. 현재 배포 코드나 승인된 기능 요구사항과 동일하다는 보장은 없다.
- 저장된 PNG가 존재해도 과거 실행 조건·판정 정답·현재 테스트 성공을 입증하지 못한다.
- 원격 GitHub 조회 404는 저장소 부재·권한·연결 문제를 구분하지 못한다. 로컬 파일 상태만 확정했다.

## 4. 사용자 문제 제기의 해석과 과잉 진단 방지

| 사용자 문제 | 실제 코드에서 확인한 설명 | 이번 설계의 대응 |
|---|---|---|
| “클릭 가능한 것을 안 누름” | 의도적으로 링크 방문만 구현. README도 클릭·로그인·검색·다운로드 미지원 명시(`OLD/README.md:31, 35`) | 모든 후보를 발견하되 허용 행동만 실행. 나머지는 위험/명세부족/SKIP 이유를 보고 |
| “URL이 조금 다르면 같은 기능인데 분리됨” | 상대 경로+query exact key. `.do` 별칭·기능 매핑 없음(`OLD/app.py:67–74, 300–310`) | 명시적 매핑 우선, 구조 유사성은 후보 추천. 제목/스크린샷만으로 자동 확정 금지 |
| “차이율 기반 필터가 잘 안 됨” | 실행 임계값은 있으나 결과 수치 필터가 없음(`OLD/public/app.js:124–134`) | 판정 threshold와 조회 filter를 별도 계약으로 정의 |
| “홈화면 다름처럼 너무 광범위함” | viewport 전체 비교와 페이지 key 중심 결과(`OLD/app.py:186, 234–255, 316–318`) | `home.notice-list` 등 영역·요소·단계별 증거 |
| “400이나 DB 차이는 사소할 수 있음” | HTTP는 출처·자원별 일부 구분, DB 값 직접 비교는 없음. 그러나 DB 콘텐츠는 이미지 diff에 반영됨 | 모든 4xx를 낮추거나 무시하지 않음. 기대 인증 401, 외부 위젯 403, 핵심 검색 API 400, 문서 404를 기능 영향에 따라 구분 |

**“외부 401/403을 전부 FAIL로 처리한다”는 평가는 현재 코드와 맞지 않는다.** `on_response()`에서 동일 출처의 document/script/stylesheet만 FAIL이고 그 외는 REVIEW다(`OLD/app.py:129–135`). 콘솔 error도 REVIEW다(`OLD/app.py:149–151`). 다만 최상위 navigation 응답이 4xx/5xx면 FAIL을 추가하고(`OLD/app.py:160–162`), 외부 스크립트에서 기원한 예외도 pageerror이면 FAIL이 될 수 있다(`OLD/app.py:149`). 요청의 endpoint 계약·예상 인증 상태·실제 사용자 기능 영향이 없어 정교한 판단이 어려운 것이 정확한 격차다.

“동일 페이지”는 데이터까지 동일하다는 뜻이 아니다. 서버별 공지 ID·제목·개수는 다를 수 있으므로 페이지 유형을 맞춘 다음 각 환경의 데이터로 목록·상세·검색 계약을 독립 검사한다. 정확한 값의 A/B 비교는 공통 fixture 또는 승인된 Mock 조건에서만 한다. 세부 정책은 [TEST_STRATEGY.md](TEST_STRATEGY.md)를 따른다.

## 5. 가장 심각한 문제 5개

| 순위 | 문제 | 근거와 우선 해결 이유 |
|---|---|---|
| 1 | **검사 실패·미수행이 PASS로 통합됨** | `OLD/app.py:234–257, 267–278`; 잘못된 정상 판정은 포트폴리오의 신뢰성을 직접 훼손. check 상태·증거 완결성부터 수정 필요 |
| 2 | **페이지 identity가 URL 문자열에 묶이고 SPA hash가 사라짐** | `OLD/app.py:56–74, 222–226, 300–310`; 같은 기능 분리와 다른 화면 합침이 동시에 발생 가능 |
| 3 | **기능 assertion과 통제된 행동 실행이 없음** | `OLD/app.py:103–115, 119–231`; 페이지 방문 성공을 검색·입력·뒤로가기 정상으로 해석할 수 없음 |
| 4 | **DB 차이·컴포넌트 차이를 분리하지 않는 전체 화면 비교** | `OLD/app.py:186, 234–255, 316–318`; 위치 특정과 정상 차이 정책 부재. 실제 오탐률은 아직 측정하지 않음 |
| 5 | **판정·실행 조건·검수 이력의 영속성이 없음** | `OLD/app.py:36–38, 331, 389–395`; 두 사람의 검수·재현·회귀 추적이 어려움 |

이는 이전 코드의 우선 개선 순위다. 현재 저장소의 첫 개발 작업은 검토한 이전 코드의 재사용 범위를 정하고 재현 가능한 시작점을 마련하는 일도 포함한다. 내부 대상 사이트 소스를 Comparator 저장소에 복사하는 것으로 대체하지 않는다.

## 6. 실제 검증 결과와 증거의 한계

이번 감사의 로컬 검증 환경은 **Python 3.14.10 / Playwright 1.64.1 / Pillow 12.3.0**이었다. 기존 `tests/test_core.py`의 **5개 단위 테스트가 통과**했다. 최초 실행에서는 임시 디렉터리 생성/접근에 sandbox `PermissionError` 1건이 발생했다. 코드 변경 없이 `tempfile.tempdir`를 쓰기 가능한 visualization 디렉터리로 지정한 후 다시 실행하여 통과했다. 이 최초 오류를 제품 기능 결함으로 집계하지 않는다. 상세 실행 방법과 한계는 [AS_IS_ARCHITECTURE.md](AS_IS_ARCHITECTURE.md)에 기록한다.

| 기존 테스트 | 검증 범위 | 근거 |
|---|---|---|
| URL validation / route key | fragment 제거, 추적값 제외, root key, URL 내 자격증명·file scheme 거부 | `OLD/tests/test_core.py:11–18` |
| crawl allowlist | same-origin, 외부 origin·logout·pdf 제외 | `OLD/tests/test_core.py:20–25` |
| status classification | 정상·한쪽 없음·높은 diff·FAIL issue | `OLD/tests/test_core.py:27–34` |
| visual diff | 20×20 합성 흰색/검정 이미지 차이율 100%, diff 폴더 생성 | `OLD/tests/test_core.py:36–45` |
| crawl links / limit | 가짜 Browser/Context와 patch한 visit, 2페이지 제한 | `OLD/tests/test_core.py:47–60` |

추가 함수 확인에서 SPA hash 키 충돌, `.do` 키 차이, null/absent diff의 PASS를 확인했다. 이후 Image.open을 합성 이미지/예외로 대체해 이미지 크기 불일치·읽기 실패의 실제 반환값도 통합 PASS가 됨을 확인했고, `csv_safe(0)`의 빈 문자열 반환도 확인했다. 이 검증은 외부 네트워크·실제 브라우저 사용자 흐름을 검증하지 않는다. 기존 5개 테스트는 DOM/CSS 비교·기능 시나리오·모바일·인증·보고서 복구·검수 충돌을 검사하지 않으므로 전체 기능 정상률로 환산할 수 없다.

측정하지 않은 항목: 운영 사이트 오탐률, 결함 검출률, 실제 페이지 커버리지, 처리 성능, 수동 대비 시간 절감, 다회 실행 재현율. 목표·인수 조건은 [ROADMAP.md](ROADMAP.md)에 제안하며, 수치는 실험 후 기입한다.

## 7. 기존 문서의 정정 제안과 다음 작업 연결

원본 README·기획서는 이번 작업에서 수정하지 않았다.

| 원본 위치 | 정정 또는 명확화 제안 |
|---|---|
| `OLD/README.md:36–37` | “입력 URL/페이지 정보/이미지는 runs에 저장”은 구현보다 넓다. 실제 디스크 저장은 PNG이며 job/report는 메모리임을 분명히 표현 |
| `OLD/README.md:32` | 수동 매핑이 필요하다는 설명에 현재 매핑 입력/저장 기능은 없다는 점을 추가 |
| `OLD/public/index.html:37–38` | “화면 차이 검토 기준”과 결과 조회용 “차이율 필터”를 구분. 현 UI를 고치는 작업은 후속 구현 PR에서 수행 |
| `SPEC/QA_AUTOMATION_PROJECT_SPEC.md:50, 71` | `NEEDS_RETEST`와 `RETEST_REQUIRED` 혼재. 목표 계약은 `RETEST_REQUIRED`로 통일하고 migration alias 여부 결정 |
| `SPEC/QA_AUTOMATION_PROJECT_SPEC.md:128–130, 180–184` | 기존 Python/Playwright/Pillow/UI를 우선 재사용. 모듈 경계와 담당자 계약만 점진 도입 |

최우선 개발 축은 **(1) 판정·증거·실행 기록의 신뢰성, (2) 페이지 identity와 안전한 발견, (3) 영역·데이터 정책을 갖춘 핵심 기능 시나리오**다. 사용자 A는 핵심 엔진·실행 통합, 동료 B는 명세·시나리오·검수/결과 UI를 중심으로 맡되 결과 schema를 공동 계약으로 고정한다. 구체적인 파일 단위 PR, 첫 주 범위, 인수 조건은 [ROADMAP.md](ROADMAP.md)에 둔다. 미확정 정책과 확인 책임자는 [DECISIONS_AND_OPEN_QUESTIONS.md](DECISIONS_AND_OPEN_QUESTIONS.md)에서 추적한다.

## 8. 추가 적용 요구사항 — 테스트 유형과 결과 관리

2026-10-30 사용자 선택 사항을 반영한다. 아래는 당시 추가한 목표 요구사항이며, 앞의 OLD 감사 추적표와 구분한다. **2026-11-03 v0.2의 실제 반영 범위·한계·코드 근거는 [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md)에 기록했다.** 기존 R01~R46과 구분해 추가 요구사항에는 AR 접두사를 사용한다.

### 8.1 지원할 테스트 유형

| 테스트 유형 | 대상 예시 | 주요 검증 |
|---|---|---|
| 단일 환경 QA | 개발1 | HTTP / JS / API / 이미지 / 링크 오류 |
| 환경 비교 QA | 운영 ↔ 스테이징, 개발1 ↔ 개발2 | 구조·기능·UI 차이, 변경 사항 및 이상 징후 |
| 회귀 테스트 | 과거 실행 ↔ 현재 실행 | 신규 발생·재발·해결 후보 |
| 조건 기반 UI QA | 개발1 | 긴 제목, 빈 목록, 페이지네이션 등 |

환경 비교의 운영↔스테이징과 개발1↔개발2는 같은 유형의 사용 예다. 환경 이름을 고정하지 않고 A/B를 선택하며 URL이 달라도 승인된 페이지 매핑으로 같은 기능을 비교한다. 회귀 비교는 규칙 버전·화면 조건·검사 범위의 비교 가능 여부를 표시한다. 검사 누락만으로 해결을 확정하지 않는다.

테스트 유형은 목적을 나타낸다. 탐색·시각·시나리오·통합 같은 검사 구성과 별도로 구분하고, 한 실행에서 필요한 검사 종류를 선택한다. 조건 기반 검사는 단일 환경에서도 수행할 수 있다.

### 8.2 추가 요구사항 추적표

| ID | 요구사항 | 적용 기준 | 현재 구현과의 구분 |
|---|---|---|---|
| AR01 | 네 가지 테스트 유형 | 단일 환경·환경 비교·회귀·조건 기반 UI QA 지원 | 현재 A/B 검사와 합성 시나리오가 전체 유형 지원을 의미하지 않음 |
| AR02 | 테스트 결과 7상태 | PASS / FAIL / DIFF / SKIP / BLOCKED / ERROR / REVIEW | v0.2에서 적용. 과거 v0.1의 5상태 결과는 재분류하지 않음 |
| AR03 | 오류 유형 분류와 중복 처리 | 대분류·세부 유형을 판정과 분리하고 대표 유형·관련 증거·중복 기준 보존 | 현재 관찰 category가 목표 분류 전체 구현을 의미하지 않음 |
| AR04 | 결과 화면 구성 | 요약·필터·목록·상세에 상태·유형·증거·검수 정보를 표시 | 기존 필터·상세 화면을 확장하는 요구사항 |

상태의 의미와 판정 경계는 [TEST_STRATEGY.md의 8절](TEST_STRATEGY.md#8-자동-상태심각도qa-최종-검수), 오류 분류·중복 처리는 4.1~4.2절, 결과 화면은 5.4절을 기준으로 한다. 현재 구현 사실은 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)에 기록한다.
