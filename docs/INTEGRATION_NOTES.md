# 브랜치 통합 노트 — taehwan- × 1105_mia (v0.5.0)

기준일: 2026-11-06 (KST) · 통합 기준 커밋: `taehwan-` 9ec1d0f, `origin/1105_mia` 1a9b7d2 · 공통 조상 6454bde

## 1. 두 브랜치가 각각 한 일

| 브랜치 | 커밋 | 내용 |
|---|---|---|
| taehwan- | 5f468ee · 7b8c535 · 1e4fd1a · cb325ff · 9ec1d0f | VISANG QA AI 엔진(동등 라우트·짝 우선 탐색·자동 로그인·커버 게이트·캡처 안정화·팝업 닫기·검수 분류·샘플링), 라이트/다크 셸, 1105_mia 첫 버전(72c56f6)의 대시보드·프로젝트 설정 화면 재스타일 |
| 1105_mia | 72c56f6 | 대시보드·프로젝트 설정 화면 (localStorage) — taehwan-에 이미 반영돼 있었음 |
| 1105_mia | ccc6339 | 검사 규칙 화면(`m_rules.*`), 활성 규칙 → 조건 기반 UI QA 전달 |
| 1105_mia | c0fcc36 | 프로젝트 설정을 PostgreSQL로(`qa/projects_db.py`, `docs/db/*`), 환경별 로그인 URL·ID·비밀번호 암호화 저장, 검사 화면 사이드바 |
| 1105_mia | 1a9b7d2 | 로그인/비로그인 검사 분할 요구사항(`docs/m_requirements.md`), 로그인 정보 삭제 옵션 |

## 2. 충돌 정리 원칙

- **화면 파일(index/app.js/m_*)**: taehwan-의 공통 셸·테마·ID 계약을 유지하고 1105_mia의 *기능*을 옮겨 심었다. 1105_mia 전용 스타일(`m_workspace.css`, `m_project_settings.css`, `scan_shell.css`)은 `styles.css` 18절로 합쳐 삭제했다. 화면 문구·필드·저장 동작은 1105_mia 원안을 따른다.
- **app.py**: taehwan-의 API·보안 검사(Host/Origin/토큰) 위에 `/api/projects`, `/api/projects/save`, `/api/projects/delete`, `/m_rules.*`를 추가했다. `psycopg`를 최상단에서 import하지 않아 DB 패키지·서버가 없어도 앱이 뜬다.
- **README**: taehwan- 본문을 유지하고 1105_mia의 DB·로그인 정보 설명을 "프로젝트 설정 저장소" 절로 옮겼다.
- **`.idea/`**: IDE 개인 설정이라 저장소에서 제외(`.gitignore`).

## 3. 통합하며 내린 결정

| 결정 | 이유 |
|---|---|
| 프로젝트 저장소 2중화: PostgreSQL(PG* 설정 시) / `local-settings/projects.json`(기본) | 1105_mia 방식은 PostgreSQL이 없으면 프로젝트 화면·검사 화면이 503으로 멈춘다. 같은 계약(검증·암호화·API)으로 파일 백엔드를 두어 설치 없이 동작하고, DB를 쓰는 사람은 `.env`만 채우면 된다 |
| 환경별 비밀번호를 실제 자동 로그인에 연결 | 1105_mia에서는 "등록만으로 자동 로그인이 실행되지 않음". 요구사항 문서가 사용을 요청하므로 `credentialRefs`(ID만)로 연결하고 비밀번호는 서버에서만 복호화 |
| 계정 우선순위: 환경별 환경변수 → 프로젝트 환경 → 공용 환경변수 → 공용 파일 | 특정 환경 계정이 공용 계정보다 구체적이다. 단, 그 PC의 환경변수 지정은 항상 이긴다 |
| 인증 상태 3택(`authMode`)이 유일한 기준 | 요구사항의 "수동 로그인 옵션과 모순되지 않게". 서버가 정규화하므로 예전 API(`manualLogin`, `login`)도 그대로 동작 |
| 비로그인 기본값 | 계정 없이 실행한 기존 실행은 원래도 로그인하지 않았다. 차이는 로그인 화면 도달이 PASS 대신 SKIP으로 기록된다는 점뿐 |
| 검사 규칙은 브라우저 저장 유지 | 1105_mia 원안 그대로. 서버 저장은 규칙 스키마 확정 후 |

## 4. 검증

- 전체 테스트: 기존 231개 + 통합 테스트 10개(`tests/test_projects_and_auth.py`) 통과
  - 파일 저장소 왕복·비밀번호 미노출·암호문 저장·삭제 / URL 검증
  - 계정 우선순위, `authMode`·`credentialRefs` 검증, 로그인 화면 판정
  - 합성 데모 회원 전용 페이지(`/demo/a/mypage`, 비로그인 시 로그인으로 302)에서 비로그인 SKIP·복귀 기록, 로그인(프로젝트 환경 계정) 접근·비밀 미노출
  - API 저장/조회/삭제, 로그인 모드 계정 없음 → 시작 전 400
- PostgreSQL 백엔드는 이 통합 환경에 DB 서버가 없어 **실제 연결은 검증하지 않았다**. SQL은 1105_mia 원안과 같다.
