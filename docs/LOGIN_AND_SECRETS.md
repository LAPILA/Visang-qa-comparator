# 로그인 · 테스트 계정 · 비밀 관리

기준일: 2026-11-04 · 구현 `qa/secrets.py`, `qa/engine.py:_test_account_login`, `qa/config.py:_login_config`

실사이트는 로그인이 필요하다. 이 도구는 두 가지 방법을 제공하며, 어느 쪽도 **비밀번호를 API·보고서·CSV·화면·로그에 남기지 않는다.**

## 1. 테스트 계정 자동 로그인 (권장 · 반복 실행용)

### 설정은 "폼 모양"만

UI의 *로그인 · 테스트 계정* 또는 API `login` 객체에는 **선택자와 URL만** 넣는다.

```json
{
  "login": {
    "url": "https://stg-e.vivasam.com/login",
    "usernameSelector": "#userId",
    "passwordSelector": "#userPw",
    "submitSelector": "button[type=submit]",
    "successSelector": ".user-name",
    "failureSelector": ".login-error",
    "accountKey": "default"
  }
}
```

| 키 | 필수 | 설명 |
|---|---|---|
| `url` | 아니오 | 로그인 페이지. 비우면 시작 URL. 호스트는 `allowedHosts`에 있어야 한다. |
| `usernameSelector` / `passwordSelector` / `submitSelector` | 예 | 아이디·비밀번호 입력, 로그인 버튼 |
| `successSelector` | 아니오 | 로그인 뒤 보여야 하는 요소(이름, 로그아웃 버튼). 없으면 "비밀번호 입력란이 사라지거나 URL이 바뀜"으로 판단 |
| `failureSelector` | 아니오 | 실패 메시지 요소. 보이면 `LOGIN_FAILED` |
| `accountKey` | 아니오 | 비밀 파일에서 쓸 계정 키(기본 `default`). 역할별 계정(`teacher`, `student`)을 구분할 때 사용 |

`login` 객체에 `password`, `id`, `token` 같은 키가 들어오면 서버가 요청을 **거부**한다(`qa/config.py`). 기존 "비밀번호·인증 상태는 API로 전달하지 않는다" 정책과 같다.

### 자격증명은 PC 안에서만

엔진 프로세스가 로그인 직전에 아래 순서로 찾는다. 첫 번째로 찾은 값을 쓰고, 없으면 추측하지 않는다.

1. 환경변수 `QA_LOGIN_A_ID` / `QA_LOGIN_A_PW` (B 환경은 `QA_LOGIN_B_*`)
2. 공용 환경변수 `QA_LOGIN_ID` / `QA_LOGIN_PW`
3. `QA_SECRETS_FILE` 경로 또는 `./secrets/accounts.json`

```json
{ "accounts": { "default":   { "id": "tester", "pw": "..." },
                "default.b": { "id": "tester-b", "pw": "..." },
                "teacher":   { "id": "t-tester", "pw": "..." } } }
```

`<accountKey>.<side>`가 `<accountKey>`보다 우선한다. `secrets/`는 `.gitignore`에 포함되어 있고 예시는 `secrets/accounts.example.json`이다.

Windows에서 한 번만 쓰려면:

```bat
set QA_LOGIN_A_ID=테스트계정
set QA_LOGIN_A_PW=비밀번호
run_windows.bat
```

### 결과에 남는 것

| 검증식 `a.login` | 상태 | 뜻 | 검수 분류 |
|---|---|---|---|
| `TEST_ACCOUNT_LOGIN_OK` | PASS | 성공 근거 확인. `actual`에는 출처 종류(environment/file)만 기록 | — |
| `LOGIN_FAILED` | BLOCKED | 실패 메시지가 보이거나 폼이 그대로 남음 | 재검 (`AUTH_REQUIRED`) |
| `LOGIN_CREDENTIALS_MISSING` | BLOCKED | 이 PC에 자격증명이 없음 | 재검 |
| `LOGIN_HOST_NOT_APPROVED` | BLOCKED | 로그인 URL 호스트가 허용 목록에 없음 | 재검 |
| `LOGIN_STEP_ERROR` | ERROR | 선택자를 찾지 못함 등 | 재검 |

`manifest.login = {method: TEST_ACCOUNT | MANUAL | NONE, form: {...선택자}, credentialsStored: false}`. 계정 ID·비밀번호·쿠키·storage state는 어디에도 저장하지 않으며, 아이디 입력란 선택자는 캡처 마스크에 자동 추가된다. 비밀번호 입력란은 기본 마스킹이다. 로그인 폼 POST는 "인증 단계" 동안만 네트워크 가드를 통과하고, 그 뒤 탐색은 기존 읽기 전용 정책 그대로다.

## 2. 수동 로그인 (일회성 · SSO/OTP)

*수동 로그인*을 켜면 실제 Chromium 창이 열린다. 각 환경에서 직접 로그인한 뒤 화면의 **로그인 완료 · 계속**을 누른다. 세션은 해당 실행의 브라우저 컨텍스트에만 있고 종료 시 사라진다. 두 방식은 동시에 선택할 수 없다.

## 3. 보안 체크리스트

- [ ] `secrets/accounts.json`이 커밋 대상에서 빠져 있는가 (`git status`로 확인)
- [ ] 공용 PC라면 환경변수 방식 대신 세션 한정 `set`을 쓰고 창을 닫는가
- [ ] 보고서 JSON·CSV에 계정 문자열이 없는가 (`tests/test_login_and_triage.py`가 자동 확인)
- [ ] 캡처에서 아이디 입력란이 가려졌는가 (`privateMaskSelectors`로 헤더의 사용자명도 추가 가능)
- [ ] 테스트 계정 권한이 운영 데이터를 바꾸지 못하는가 — 도구는 POST/변경 동작을 기본 차단하지만 계정 권한 자체는 운영자가 관리한다
