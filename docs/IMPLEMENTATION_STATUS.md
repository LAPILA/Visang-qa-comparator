# 현재 구현 현황 — MVP 0.1.0

기준일: 2026-10-30 (KST). 사용자의 후속 제작 요청으로 구현한 **첫 실행 가능한 버전**이다. 이전 다섯 문서는 Downloads의 OLD 코드를 감사한 기록과 목표 설계다. 이 문서와 [README](../README.md)가 현재 코드의 사용법·구현 범위를 설명한다. 커밋·푸시는 수행하지 않았다.

## 1. 구현한 것과 한계

| 항목 | 상태 | 실제 범위와 코드 근거 |
|---|---|---|
| 실행 UI·프로필·단일 worker | 구현 | `app.py:67`, `qa/config.py:76`, `public/app.js:63`. loopback 서버, 환경별 context, 4제품 프로필 중 주소 미확정 STG는 비활성 |
| URL hash·query 보존 | 구현 | `qa/matching.py:7–19`. hash route·반복 query 순서를 보존. `.do` 일괄 제거 없음 |
| 명시적 매핑·후보 제안 | 부분 구현 | `qa/matching.py:22–40`. alias 충돌 REVIEW, heading/구조 후보 REVIEW. 화면 유사도 모델·별도 매핑 승인 UI는 없음. 고급 JSON에서 매핑 편집 |
| 안전 발견·통제 실행 | 부분 구현 | `qa/engine.py:30`, `qa/policy.py:68–129`, `qa/engine.py:162`. 버튼/submit/role/onclick/링크 후보, 허용 host·route·selector, 위험 단어 우선 차단. iframe은 수만 기록하고 shadow/canvas 지원 안 함 |
| 시간·페이지·행동 한도/취소 | 구현 | `qa/engine.py:86`, `qa/engine.py:437`, `app.py:103–120`. A/B 행동 예산 분배, 미실행 사유, 실행 시도/완료 구분. 개별 요청의 총수·서버 부하를 완벽히 제어하는 기능은 아님 |
| HTTP/JS 관찰 | 부분 구현 | `qa/engine.py:125–192`, `qa/policy.py:131`. 출처/resource/method/status·정책 차단 구분. endpoint별 예상 401·API 계약·오류 지문 통합은 후속 |
| 화면·영역 비교 | 구현/MVP 범위 | `qa/engine.py:195–269`, `qa/comparison.py:12`. viewport/region PNG, 마스크·비교 분모, 차이율/overlay. 이미지 오류가 PASS가 되지 않음 |
| DOM/CSS 검사 | 부분 구현 | `qa/engine.py:195–269`. 필수 영역 존재/가시성 assertion, bounding box·일부 computed style 수집. 일반 겹침/잘림·CSS 속성 계약 비교는 미구현 |
| 서버별 데이터 차이 | 부분 구현 | region의 `mask_selectors`로 동적 내용 제외, 존재·가시성 검사 병행. DB 원본 일치 검사 없음. 일반 목록 구조 계약·동적 영역 자동 탐지는 미구현 |
| 기능 시나리오 | 부분 구현 | `qa/scenarios.py:52–178`. 합성 데모의 검색/길이/history 3개, A/B 독립 실행. live 시나리오·팝업/다운로드·IME 검증은 미구현 |
| 수동 로그인 | 부분 구현 | `app.py:123–156`, `qa/engine.py:437`. headed 브라우저에서 사용자 직접 로그인, 메모리 세션만 사용. 자동 성공/권한 역할 판단과 장기 세션 재사용은 없음 |
| ID 기억 | 구현/보조 기능 | `public/app.js:80–105`. opt-in localStorage 메모, 담당자/프로필/A·B 구분, 해제 시 삭제. 사이트 로그인 입력란에서 자동 추출·자동 채움하는 기능은 없음. PW는 입력받지 않음 |
| 자동 5상태 | 구현 | `qa/policy.py:49–65`, `qa/comparison.py:62`, `qa/engine.py:500`. 자동 상태와 검수 상태 분리. 필수 영역 누락 FAIL, 수집/비교 실패 ERROR |
| 필터·내보내기 | 구현 | `public/app.js:325–377`, `app.py:31–53`. 상태/영역/문자열/차이율/null, 독립 FAIL·ERROR 목록, CSV/JSON. standalone HTML export는 미구현 |
| 결과 저장·검수 충돌 | 구현/단일 서버 범위 | `qa/store.py:61`, `app.py:67`. 원자적 JSON 교체, interrupted 복구, 검수 actor/reason/revision/history. 공유 폴더의 다중 프로세스 동시 쓰기·사용자 인증은 지원 안 함 |
| 로컬 보호 조치 | 부분 구현 | `app.py:194–363`, `qa/store.py:22–54`, `qa/policy.py:17–46`. Host/Origin/nonce, JSON 제한, URL/로그 비밀 일부 제거, password/private selector 마스크. 모든 PII 자동 식별/공개 승인/암호화 저장소는 아님 |
| CI | 파일 작성, 원격 실행 미확인 | `.github/workflows/qa.yml`. 합성 테스트만 실행하도록 구성. 푸시하지 않았으므로 GitHub Actions 성공 기록 없음 |

구현 중 기존 Playwright 동기 흐름·BFS·listener·Pillow 비교·CSV 방식을 유지하면서 모듈로 나눴다. 회사 샘플 소스, 기존 runs, 실제 공지/교과자료, 계정·쿠키를 복사하지 않았다. 기존 잘못된 hash 삭제/PASS 기대값은 보존하지 않고 수정된 계약의 회귀 테스트로 대체했다.

## 2. 실제 검증 결과

검증 환경: Windows, Python 3.14.10, Playwright 1.64.1, Pillow 12.3.0, 설치된 Playwright Chromium. 각 실제 run manifest에 브라우저 버전과 source SHA256을 저장한다.

- 기존 단위/HTTP/브라우저/엔진 통합 **66개**: `python -B scripts/run_tests.py` 실행, 전부 통과, SKIP 없음.
- 이후 추가한 실제 UI→worker→보고/검수/CSV/이력 테스트 **1개**: `python -B -m unittest discover -s tests -p test_ui_browser.py -v` 실행, 통과.
- 합계 **67개의 서로 다른 테스트가 통과**했다. 기본 실행 명령은 새 UI 테스트도 자동 발견한다. 두 실행의 합계이며 하나의 실행 로그를 67개라고 바꾸어 쓰지 않는다.
- `node --check public/app.js` 통과. UI 계약 검증에서는 합성 API 응답으로 5상태·수치/null 필터·ID 비전송·충돌 안내 등을 추가 확인했다. 이는 위 67개 unittest 개수에 포함하지 않는다.
- 실제 엔진 테스트에서 A/B 합성 기능 assertion **각 15개, 총 30개 PASS**, 의도한 필수 Help 영역 누락 **FAIL 검출**, 저장/삭제 함정 호출 **0건**, 비교 ERROR **0건**을 확인했다. 실행된 브라우저 함수와 HTTP 상태의 범위에 한정된 결과다.
- UI 테스트는 실제 앱에서 검사 시작, 필터, 검수 저장, CSV 다운로드, 새로고침 후 이력 열기를 수행했다. 모바일 가로 넘침과 UI pageerror도 확인했다.

한 필수 버튼 결함이 여러 페이지/region 행에 반복 표시될 수 있다. `totals.pages`는 현재 **비교 결과 행 수**이고 방문 페이지 수는 `baselineVisited/candidateVisited`, 고유 결함 수는 아직 별도 집계하지 않는다. 결과 행 FAIL 개수를 독립 버그 검출 건수로 발표하지 않는다.

이번에 측정하지 않은 것: 실사이트 탐지율·오탐률·성능·수동 대비 시간 절감, 4제품 전체 기능 정상성, 실제 계정 로그인 성공·권한, CI 실행 성과.

### 검증 중 수정한 결함

- null/크기 불일치/이미지 읽기 실패의 PASS 제거.
- hash route 소실과 과도한 route 허용 방지.
- 0% CSV 값 보존, A/B check ID와 region check ID의 집계 충돌 방지.
- 시나리오를 모든 페이지에서 반복하지 않고 환경당 한 번 실행; A/B 행동 예산 확보.
- Windows의 미소비 POST body 때문에 403 응답이 간헐적으로 연결 초기화되는 문제 수정. 제한된 body를 timeout 안에 읽고 거부하며, 해당 보안 테스트 5회 반복 확인.
- 일반 token/OAuth fragment 비밀 제거 누락과 비밀 제거 시 정상 query/hash까지 잃는 문제 수정.
- 검수 revision 경쟁에서 한 요청만 저장되고 나머지는 409가 되는지 확인.

샌드박스에서 Chromium/localhost 통신이 막혀 로컬 테스트 실행만 승인된 외부 실행 환경에서 수행했다. 테스트 대상은 loopback 합성 서버였으며 운영/STG는 호출하지 않았다.

## 3. 실제 코드의 경계와 다음 작업

1. **실사이트 adapter**: 학교급별 ready/region/계정 역할·안전 조회 POST·SSO/CDN host를 담당 QA와 확인한 다음 등록한다. 현재 기본 프로필은 제품별 자동화 완성품이 아니다.
2. **명세 기반 기능 추가**: 실제 검색·입력 N·back/refresh 기대값을 확정하고 합성 구현의 scenario hook을 확장한다. 안전한 다운로드/팝업도 별도 테스트 데이터로 추가한다.
3. **UI 구조 검증 강화**: data mask 내부의 행 구조/overflow/겹침을 검사하고 region 위치·스타일 비교를 구현한다. 현재 마스킹이 이 전체 기능을 대신하지 않는다.
4. **검수 품질·재현성**: 원시 이벤트의 단계 귀속, fingerprint 중복 제거, 정책 버전별 재평가, storage 실패·완전 중단 시 부분 증거 보존을 강화한다.

현재 모든 픽셀이 가려진 영역은 `NO_COMPARABLE_PIXELS/ERROR`로 표시한다. 설계 문서의 SKIP 제안과 달리 이 MVP는 비교 설정 오류로 취급한다. 어느 경우든 PASS로 표시하지 않는다. API 바깥쪽 필드 일부는 이전 UI와 호환되는 camelCase, check/설정 내부는 snake_case다. 외부 연동 전에 schema migration 계약을 확정한다.

## 4. 파일과 담당 경계

담당 A: `qa/engine.py`, `matching.py`, `comparison.py`, `policy.py`, `app.py` 실행 통합. 담당 B: `qa/scenarios.py`, 제품별 region/route 설정, `public/`, `qa/store.py`, 합성 데모/회귀 테스트. `qa/config.py`와 결과 JSON 계약은 공동 검토한다. 기존 [ROADMAP](ROADMAP.md)은 장기 목표이며 이번 구현을 모든 항목 완료로 처리하지 않는다.

사용자는 `run_windows.bat` 또는 README 명령으로 실행할 수 있다. 결과/임시파일/스크린샷은 `runs/`, `output/`에 있고 Git에서 제외된다. 이번 작업에서 생성한 로컬 데모는 실행 이력의 `MVP-DEMO` 담당자로 구분된다.
