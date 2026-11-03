# 현재 구현 현황 — v0.3.1

기준일: 2026-11-03 KST. 기존 Python/Playwright/Pillow/순수 JS를 유지하며 동료 MD의 AR01~AR04와 환경별 탐색·기능 매핑을 확장했다. 공통 인터페이스는 [RESULT_CONTRACT](RESULT_CONTRACT.md), 사용 순서는 [ENVIRONMENT_DISCOVERY](ENVIRONMENT_DISCOVERY.md), 운영·검수는 [OPERATIONS](OPERATIONS.md)를 따른다. 원래 감사 문서와 [v0.1 기록](releases/0.1.0.md)은 과거 사실·장기 설계를 구분해서 읽는다.

## 1. 구현 범위와 코드 근거

| 기능 | 현재 구현·한계 | 실제 코드 |
|---|---|---|
| 네 제품·환경 분리 | 사용자 제공 4제품 × 4환경의 16주소 등록. A/B 환경 선택·URL 자동 입력·직접 입력·기존 설정 복원. 중고등 모바일 STG도 확인 주소 적용. | `qa/environments.py:1`, `qa/config.py:90`, `qa/config.py:164` |
| 조회 링크 탐색 | 기본 승인 경로 유지. opt-in 동일 출처 안에서 위험 경로·계정·API·다운로드·변경 query 제외, 시간/페이지/깊이 한도. | `qa/policy.py:220`, `qa/engine.py:682` |
| 페이지 특징·개인 영역 | 메뉴 경로·구조/heading·폼 이름/타입·버튼 수집. 입력값 미열람, private subtree/자손 텍스트 제외, selector 오류는 ERROR. | `qa/engine.py:141` |
| 기능 매칭 후보 | alias/시작 쌍/정확 경로를 먼저 예약. 서로 유일한 메뉴·폼·구조 후보만 REVIEW. 모순·상세 ID 차이·중복은 강제 연결하지 않음. | `qa/matching.py:172` |
| 목록·매핑 초안·내보내기 | 환경별 방문/보류·URL·근거, 수동 alias 초안, 페이지 CSV와 전체 JSON. 과거 결과/검수 변경·자동 실행 없음. | `qa/inventory.py:20`, `public/app.js:549`, `app.py:61` |
| URL 보존 | query 순서·중복·percent encoding·hash 보존. 비밀 제거가 필요한 URL은 redact하고 자동 alias 비활성. | `qa/matching.py:55`, `qa/store.py:22` |
| 4목적·7상태 | 환경 비교·단일·회귀·조건 UI와 PASS/FAIL/DIFF/SKIP/BLOCKED/ERROR/REVIEW. 단일 계열 B 방문 없음. | `qa/engine.py:871`, `qa/policy.py:84` |
| 시각·DOM·데이터 | 영역 PNG·마스크·존재/가시성·차이율·분모. 전체 DB 동일성·자동 동적 영역 탐지·범용 겹침 탐지는 미지원. | `qa/engine.py:356`, `qa/comparison.py:12` |
| 관찰·유형·중복 | HTTP/JS/네트워크·단계/출처/요청 ID·발생 수. 정책 영향 REVIEW와 실제 제품 오류를 구분. 모든 세부 수집기 구현을 뜻하지 않음. | `qa/engine.py:255`, `qa/findings.py:209` |
| 조건·회귀 | 읽기 전용 조건과 전제 검사. 과거/현재의 규칙·범위·캡처 비교. 누락으로 해결 추정 금지, 과거 PNG 픽셀 회귀 미지원. | `qa/conditions.py:147`, `qa/regression.py:55` |
| 저장·검수·재현 | 원자적 저장·복구·저장 실패 ERROR/메모리 보존·revision·이슈 이력·서버 폴더 잠금, 버전과 source/rule/scope hash. | `qa/store.py:108`, `app.py:80` |
| 로그인·기능 시나리오 | 수동 로그인/메모리 세션·opt-in ID 메모. 합성 검색/길이/history. 자동 로그인·실사이트 팝업/다운로드 시나리오는 미지원. | `app.py:91`, `qa/scenarios.py:178` |

AR01 네 목적·AR02 7상태·AR03 분류/중복·AR04 결과 화면은 위 범위에서 구현했다. 실제 제품 기능을 명세 없이 PASS하지 않으며, 화면 유사도 AI·범용 CSS 레이아웃 검증·API 업무/스키마 계약 수집기가 전부 구현된 상태는 아니다. CI 파일은 있으나 이번 원격 CI 성공은 측정하지 않았다.

## 2. 실제 검증

Windows / Python 3.14.10 / Playwright 1.64.1 / Pillow 12.3.0 / 설치된 Chromium. loopback 합성 사이트와 메모리 HTML만 사용했다.

v0.3.1은 [16개 환경 등록표](ENVIRONMENT_URLS.md)를 기준으로 주소·환경 ID/이름·선택 URL을 구현했다. 최종 전체 테스트 **203개 통과, SKIP 0개**, `node --check public/app.js` 통과. 등록 테스트는 64개 A/B 조합과 모바일 hash/nohash, 등록 ID/URL 충돌, 선택 호스트만 승인, 기존 직접 입력·별칭·단일 환경 호환을 확인했다. UI는 4제품의 A/B 환경 선택과 과거 URL 복원·ID 메모 보존을 검증했다. 이는 실제 사이트 접속 테스트가 아니다.

아래 v0.3.0 기록은 이전 단계이며 v0.3.1의 전체 검증은 별도 로그 `output/validation-v0.3.1.log`로 구분한다.

- 전체 단위·HTTP·Chromium 엔진/UI 회귀 **189개 통과, SKIP 0개**: `python -u -B scripts/run_tests.py`, 로그 `output/validation-v0.3.0.log`.
- 이후 URL 저장 보존을 보완하고 저장·비밀 제거 회귀 **14개 통과**: 로그 `output/validation-v0.3-url-storage.log`. 앞의 13개와 중복이고 1개가 신규이므로 **총 190개의 서로 다른 테스트 통과**다. 단일 실행에서 190개를 실행했다고 표시하지 않는다.
- `node --check public/app.js` 통과. 실제 UI→API→엔진 목록·CSV·이력·검수, 후보 초안·원본 보존, 모바일 가로 넘침·pageerror·외부 요청을 검증했다.
- 탐색 fixture: 구형 hash route/새 경로를 각각 3페이지 방문, 같은 메뉴·폼 후보를 REVIEW로 제안, 삭제·계정·다운로드·API 함정 HTTP 호출 0건.
- privacy fixture: 입력값 getter 미접근, private marker JSON/CSV 노출 0, 원본 DOM 불변, 잘못된 selector ERROR와 수집·캡처 중단.
- 인코딩 fixture: `%20`·반복 query·hash를 목록/alias/저장에서 유지하고, 추천 alias를 다음 matcher에 넣어 EXPLICIT_ALIAS를 확인했다.

새 앱의 로컬 합성 이력 `DISCOVERY-0.3`을 저장했다. A/B 각각 방문 3·보류 2, 시작 쌍 1·미승인 기능 후보 2, CSV 다운로드와 저장/삭제 함정 0건을 확인했다. 결과는 Git 제외 폴더에만 있으며 새 clone에서 자동 생성되지 않는다.

초기 실행에서 서로 다른 주기능 heading을 가진 fixture의 자동 연결 기대가 실패했다. 모순을 보수적으로 유지하고 실제 구형 모바일처럼 한쪽 h1이 없는 fixture로 구분해 재검증했다. 초기 로그는 `output/validation-v0.3-initial.log`에 보존했다.

이번에 재현·수정한 문제:

1. private 영역이 구조 특징/메뉴/내보내기에 남음 → 수집 전 제외, 입력값 미열람, selector 오류 시 중단.
2. `op=reset`/`actionType=update`·중첩 인코딩 명령이 조회 탐색을 우회 → 제어 query 차단, 검색 내용/원래 URL 보존.
3. 후보 내보내기·저장이 URL 인코딩을 바꿈 → 일반 identity 보존, 비밀 URL alias 비활성.
4. 미확정 STG 때문에 중고등 모바일 전체 선택 불가 → 비교 B 직접 입력과 단일 운영 검사·모바일 viewport 지원.

실제 운영/STG/DEV1/DEV2 전체 크롤링·로그인·탐지율·오탐률·속도·업무 시간 절감·공유 서버 부하·원격 CI 성과는 측정하지 않았다. 실제 환경은 확인된 URL·수동 로그인·승인된 검사 범위가 필요하다. GET도 무조건 안전하지 않으므로 확장 탐색은 알려진 위험을 보수적으로 배제하는 opt-in 방식이다.

## 3. 이전 단계 기록

- v0.2.1: 전체 145개 통과, SKIP 0. `output/validation-v0.2.1.log`. `/#/`와 `/` 시작 쌍, 정적 CDN 권한 분리·정책 영향 JS/console·탐색 모드 안내를 보완했다.
- v0.2.0: 전체 127개 통과, SKIP 0. `output/validation-v0.2.log`. 관찰 지문·종료 중 검수 이력·로그인 중단의 A 결과 보존·저장 실패 ERROR를 검증했다.
- v0.1의 67개 기록은 별도 버전 기록이며 새 단계와 합산하지 않는다.

## 4. 두 개발자의 다음 작업

| 담당 | 현재 경계 | 다음 작업 |
|---|---|---|
| A: 사용자·핵심 엔진 | engine/policy/matching/inventory와 실행 통합 | 실사이트 준비·읽기 API 계약·중간 checkpoint·선택 재검 |
| B: 협업자·시나리오/검수 | 실제 selector/매핑/TC, conditions/scenarios, public | 네 제품 환경 URL·역할·기대값 확인, 안전 동작·영역 검수와 시나리오 등록 |
| 공동 | config/store/결과 계약·회귀·검증 기록 | 스키마·정책 변경, 개인정보·오탐/미탐 표본, 교차 검수 |

worker는 서버당 하나이며 결과 폴더는 한 프로세스가 소유한다. 환경·담당자 이름은 자기 신고 정보다. 공용 서비스에는 사용자 인증/권한·접근 기록·공유 저장 transaction·증거 암호화/보존·백업 복구가 추가로 필요하다. 시스템 폰트 전체 fingerprint·대상 build ID/역할 자동 수집도 미지원이다. 현재 loopback 바인딩을 유지한다. 회사 소스·실데이터·계정은 복사하지 않았고 커밋·푸시는 사용자가 수행한다.
