# 로그인 · 테스트 계정 · 비밀 관리

기준일: 2026-11-04 · 구현 `qa/secrets.py`, `qa/engine.py:_test_account_login`, `qa/config.py:_login_config`

실사이트는 로그인이 필요하다. 이 도구는 두 가지 방법을 제공하며, 어느 쪽도 **비밀번호를 API·보고서·CSV·화면·로그에 남기지 않는다.**

## 1. 테스트 계정 자동 로그인 (권장 · 반복 실행용)

### 선택자 없이: 자동 탐지 (기본)

`login` 객체에 선택자를 비우면(`{"url": null}` 또는 UI에서 체크만) 엔진이 ① 보이는 비밀번호 입력란을 찾고, 없으면 `로그인/login/Sign in` 링크·버튼을 한 번 누른 뒤 ② 비밀번호 입력란 **바로 앞의** 보이는 text/email/tel 입력란을 아이디로, ③ 같은 폼의 submit 버튼 또는 `로그인` 글자 버튼을 제출로 씁니다(없으면 Enter). 성공 판단은 `로그아웃/마이페이지` 표시, 또는 비밀번호 입력란 소멸·URL 변경입니다. 폼을 못 찾으면 `LOGIN_FORM_NOT_FOUND`(BLOCKED·재검)로 기록하고 추측하지 않습니다. 자동 탐지가 실패하는 사이트만 아래 선택자를 적습니다.

### 선택자 없이도 됩니다 (자동 탐지)

`login`에 선택자를 비우면 엔진이 ① 보이는 비밀번호 입력란을 찾고, 없으면 ‘로그인/Login/Sign in’ 링크·버튼을 한 번 눌러 찾은 뒤 ② 그 앞의 text/email/tel 입력란을 아이디로, ③ 같은 폼의 submit 또는 ‘로그인’ 버튼(없으면 Enter)을 제출로 씁니다. 성공은 로그아웃/마이페이지 표시 또는 비밀번호 입력란 소멸·URL 변경으로 판단합니다. 자동 탐지가 실패하면 `LOGIN_FORM_NOT_FOUND`(BLOCKED·재검)로 기록되며, 그때만 아래 선택자를 적습니다.

### 모바일처럼 커버 게이트가 로그인까지 막는 경우

로그인 단계는 **탐색과 같은 탭**에서 실행되며, 진입 동작(entry)이 설정돼 있으면 로그인 페이지를 찾기 전에 커버 게이트를 먼저 통과합니다. 로그인 링크가 햄버거 메뉴 안에 숨어 있으면 숨은 `<a href*=login>`의 주소로 바로 이동하고, 그것도 없으면 `/login`, `/#/login`, `/member/login`, `/signin` 등 흔한 경로를 순서대로 시도합니다. 성공 검증식의 `actual`에 어느 URL에서 로그인했고(`loginUrl`) 게이트 통과 기록(`gate`)이 무엇인지 남습니다.

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

### 공용 계정 한 개로 끝내기 (가장 쉬운 방법)

```bat
setup_login_windows.bat
```

ID와 비밀번호(입력 중 미표시)를 물어본 뒤 `secrets/accounts.json`에 `default` 계정으로 저장합니다. 이 하나가 A/B 모든 환경·모든 프로필에 쓰이며, `accountKey`를 비워 두면 됩니다. 환경별 계정이 필요할 때만 `default.a`/`default.b`를 추가합니다.

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
