# 제품별 환경 URL 등록표

등록 기준: 2026-11-03 KST 사용자 제공 주소. 주소 등록은 접속·로그인·기능 검증 완료를 의미하지 않는다. 코드의 단일 등록 원본은 `qa/environments.py`의 `PRODUCT_ENVIRONMENTS`다.

| 제품 | 운영 | STG | 바이브 개발 | 레거시 개발 |
|---|---|---|---|---|
| 초등 PC | [https://e.vivasam.com/main](https://e.vivasam.com/main) | [https://stg-e.vivasam.com/](https://stg-e.vivasam.com/) | [https://dev2-e.vivasam.com/main](https://dev2-e.vivasam.com/main) | [https://e-dev.vivasam.com/](https://e-dev.vivasam.com/) |
| 중고등 PC | [https://v.vivasam.com/main](https://v.vivasam.com/main) | [https://stg-v.vivasam.com/](https://stg-v.vivasam.com/) | [https://dev2-v.vivasam.com/main](https://dev2-v.vivasam.com/main) | [https://v-dev.vivasam.com/](https://v-dev.vivasam.com/) |
| 초등 모바일 | [https://me.vivasam.com/](https://me.vivasam.com/) | [https://stg-me.vivasam.com/](https://stg-me.vivasam.com/) | [https://dev2-me.vivasam.com/](https://dev2-me.vivasam.com/) | [https://me-dev.vivasam.com/#/](https://me-dev.vivasam.com/#/) |
| 중고등 모바일 | [https://mv.vivasam.com/](https://mv.vivasam.com/) | [https://stg-mv.vivasam.com/](https://stg-mv.vivasam.com/) | [https://dev2-mv.vivasam.com/](https://dev2-mv.vivasam.com/) | [https://mv-dev.vivasam.com/#/](https://mv-dev.vivasam.com/#/) |

## 등록 규칙

- STG는 도메인만 제공되어 `https://도메인/`으로 등록했다. `/main` 등 다른 시작 경로가 필요하면 URL 직접 입력으로 지정할 수 있다.
- 운영·바이브 개발 PC의 `/main`, 레거시 모바일의 `/#/`는 제공된 그대로 유지한다. 운영 모바일에는 임의로 `/#/`를 붙이지 않는다.
- 중고등 모바일 STG는 `stg-mv.vivasam.com`이다. 과거 미확정/오타 기록을 현재 설정으로 사용하지 않는다.
- 사용자 입력값으로 확인한 주소만 등록한다. 다른 환경 호스트를 문자열 치환으로 생성하지 않는다.

## 앱과 API

제품 선택 후 A/B 환경을 각각 선택하면 그 제품의 등록 URL과 기본 환경 이름이 채워진다. 직접 URL 수정도 가능하며, 등록 URL과 정확히 일치하지 않으면 `custom`으로 구분한다. 과거 실행을 불러올 때는 저장된 URL을 우선하여 기존 `/main` 또는 `/#/`를 변경하지 않는다.

API 환경 ID는 `production` / `staging` / `vibe-dev` / `legacy-dev` / `custom`이다. ID만 제공하면 등록 URL을 선택한다. 등록 ID와 다른 URL을 함께 제공하면 거부하고 직접 입력으로 전환하도록 안내한다. ID가 없는 과거 요청은 URL의 정확한 일치로 추론한다. 사용자 지정 환경 이름은 유지한다.

등록 목록의 16개 호스트가 모두 탐색 권한을 얻는 것은 아니다. 실행에서 선택한 A/B URL과 명시적으로 승인한 호스트만 해당 실행 설정에 포함한다. 단일 환경에서는 B URL·ID를 검사하지 않는다.

이 등록표를 이용한 실제 탐색·후보 검수 절차는 [ENVIRONMENT_DISCOVERY](ENVIRONMENT_DISCOVERY.md)를 따른다. 이번 등록 작업은 실제 사이트를 자동으로 탐색하거나 로그인하지 않았다.
