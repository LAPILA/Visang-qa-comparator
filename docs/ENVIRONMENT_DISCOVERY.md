# 환경별 페이지 탐색과 기능 매핑

기준일: 2026-11-03 KST · v0.3.1. `stg-`, `dev2-`, `-dev` 같은 배포 환경 표기와 `e`/`v`/`me`/`mv` 제품 구분을 같은 URL 정규화 규칙으로 처리하지 않는다. 사용자가 선택한 제품과 A/B 실제 시작 URL·환경 이름을 별도로 기록한다. 현재 [16개 등록 주소](ENVIRONMENT_URLS.md)는 제품별 A/B 선택 메뉴에서 사용할 수 있다.

## 1. 사용 순서

1. 제품과 A/B 환경을 선택하고 자동으로 채워진 시작 URL을 확인한다. 운영/STG/바이브 개발/레거시 개발을 선택하거나 직접 입력할 수 있다. 환경 이름도 사용자가 변경할 수 있다. 호스트 이름을 바꾸어 추측한 서버에 접속하지 않는다.
2. 검사 모드는 **탐색만**, 탐색 범위는 **환경 내부 읽기 전용 링크 탐색**을 선택한다. 처음에는 페이지·깊이 한도를 작게 잡고 차단 목록을 검수한다. 기본 범위는 기존의 승인 경로 방식이다.
3. 로그인이 필요하면 각 환경 브라우저에 사용자가 직접 로그인한다. 비밀번호·세션 파일을 저장하지 않는다.
4. 실행 결과의 **환경별 페이지 목록·매칭 후보**를 연다. A/B 각각의 방문 URL·최종 URL·메뉴 경로·구조/폼/버튼 특징·실제 방문과 보류 수를 확인한다.
5. 대응 후보의 메뉴·폼·구조 근거와 모순을 확인하고 **매핑 JSON에 추가**한다. 이 동작은 현재 설정의 aliases만 수정한다. 자동 상태·검수·과거 결과를 바꾸거나 새 검사를 시작하지 않는다.
6. 시각/통합 모드로 새 검사하여 승인한 기능 페이지·영역을 비교한다. 실행 설정은 보고서에 저장되므로 다음에 **이 실행 설정 불러오기**로 재사용한다.

예시 대응(합성 형식):

| 기능 | A의 URL | B의 URL | 대응 근거 |
|---|---|---|---|
| 시작 홈 | `/#/` | `/` | 사용자가 지정한 시작 쌍 |
| 공지 목록 | `/#/notice` | `/cs/announcements` | 같은 메뉴 경로 + 폼/구조. 승인 전 REVIEW |
| 교과 자료 | `/old/material.do` | `/materials` | 검수한 별칭 또는 기능 후보 |
| 공지 상세 | `...?id=101` | `...?id=909` | 다른 데이터 instance. 템플릿만 같다는 이유로 자동 연결하지 않음 |

이 표는 실제 서비스의 내부 경로 명세가 아니다. 시작 주소는 [ENVIRONMENT_URLS](ENVIRONMENT_URLS.md)의 사용자 제공 등록표를 사용한다. 중고등 모바일 STG도 `stg-mv.vivasam.com`으로 확인되었다. 단일 환경 검사는 A만 선택한다.

## 2. 안전 탐색 계약

`crawlScope=approved_paths`는 기존 시작/alias/승인 경로만 방문한다. `same_origin_readonly`는 선택한 각 환경의 **scheme + host + 유효 port**가 같은 링크만 확장한다. A/B 호스트가 모두 허용 목록에 있어도 A 탐색에서 B의 링크를 암묵적으로 방문하지 않는다.

확장 탐색은 보이는 승인 가능한 anchor URL을 제한된 큐에 넣어 방문한다. 삭제·저장·변경·계정·개인정보·다운로드·정적 파일·API 링크, submit, 알 수 없는 업무 동작은 보수적으로 제외한다. URL을 검사할 때만 decode하고 실제 query 순서·중복 key·hash는 유지한다. GET만으로 업무 안전을 보장할 수 없으므로 알려진 위험을 배제하는 정책이며, 검토한 작은 범위부터 사용한다.

자동 POST·목적 불명 버튼·iframe·shadow DOM·canvas의 전체 탐색은 지원하지 않는다. href 없는 UI는 기존 승인 동작/시나리오로 확장해야 한다. 목록에 보였다는 사실, URL을 방문했다는 사실, 실제 버튼을 클릭해 기능을 검증했다는 사실은 서로 다르다. 시간·페이지·깊이 한도로 미방문한 항목은 BLOCKED와 발견 경로로 남긴다.

## 3. 페이지 identity와 후보

우선순위는 명시 alias → 입력 시작 쌍 → 정확 route → 기능 후보다. 먼저 명확한 대응을 양쪽에서 예약한 다음, 남은 페이지 전체에서 서로 유일한 기능 후보만 REVIEW 쌍으로 묶는다. 앞에서 처리한 약한 후보가 뒤의 명확한 대응을 가져가지 않도록 한다.

기능 후보는 다음 정보를 사용한다.

- navigationTrail: 페이지를 발견한 메뉴 경로. URL 자체를 메뉴 이름으로 간주하지 않음.
- pageSignature: landmark 구성, 제한된 heading, 폼의 type/name/label, 비동적 버튼·탭과 탐색 메뉴 이름.
- 명시적인 기능·폼·메뉴 모순, 서로 다른 상세 ID는 자동 연결을 막는 근거.

폼 입력값·비밀번호·전체 body 텍스트를 특징으로 수집하지 않는다. 공통 헤더·메뉴·레이아웃만 비슷하면 같은 기능으로 확정하지 않는다. 후보에는 수치 확률 대신 비교한 원본 특징과 일치/모순 사유를 표시한다. 여러 후보·대응에 이미 사용한 페이지·데이터 instance 충돌은 단독 결과와 후보 목록에 남긴다.

`SEMANTIC_CANDIDATE`와 `STRUCTURE_CANDIDATE`는 승인되지 않은 REVIEW다. 후보가 없어도 페이지가 없거나 404라고 추정하지 않는다. 사용자가 검토한 alias를 다음 실행에서 명시 규칙으로 적용한다. 토큰 때문에 URL을 가린 경우 자동 alias 제안은 비활성화한다.

## 4. 저장·내보내기

신규 보고서 `inventory`:

```text
productId, crawlScope
environments[]
  id / name / seedUrl
  discoveredCount / visitedCount / deferredCount
  pages[]
    id / pageKey / url / finalUrl / title / navigationTrail
    signature / visited / statusCode / captureReady
    actionCount / approvedActionCount / blockedActionCount / notExecutedReasons
matches[]
  baselineUrl / candidateUrl / baselineKey / candidateKey
  method / approved / reason / evidence / candidates / aliasSafe
```

`GET /api/scans/{run-id}/inventory.csv`로 환경별 페이지 목록을 내보낸다. 전체 후보·근거는 JSON에 포함한다. CSV에도 0값과 수식 삽입 방어를 유지한다. 이전 보고서에 목록이 없으면 임의로 복원하지 않고 새 탐색이 필요하다고 표시한다.

매칭 후보의 일반 URL은 `%20`·반복 query·hash를 그대로 보존한다. 저장·내보내기도 같은 규칙을 적용한다. 비밀 파라미터로 URL을 가렸다면 `aliasSafe=false` 또는 후보 `alias=null`로 표시하고 자동 매핑 초안 버튼을 비활성화한다.

방문·보류·후보 목록은 **해당 실행의 제한 안에서 관찰한 범위**다. 전체 사이트 수집 완료·기능 정상·고유 버그 수를 뜻하지 않는다. 현재 구현/실제 검증 범위는 [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md), 공통 계약은 [RESULT_CONTRACT](RESULT_CONTRACT.md)를 따른다.
