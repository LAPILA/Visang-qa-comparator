# 프로젝트 설정 공유 SQL

2026-11-05 로컬 PostgreSQL의 `projects`, `project_environments` 값을 기준으로 작성했다. `m_local_db_schema.md`의 테이블을 먼저 생성한 후 아래 SQL을 실행한다. 프로젝트 ID와 환경 ID를 그대로 사용하므로 같은 SQL을 다시 실행해도 중복 행을 만들지 않는다. 기존 프로젝트의 이름·환경 URL·표시 순서는 이 값으로 갱신된다.

```sql
BEGIN;

INSERT INTO projects (id, name, created_at, updated_at) VALUES
  ('fa509809-246a-459f-879d-d803df29bb7e', '초등 모바일', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
  ('24b5a282-dc22-4f11-b1b8-d6d8ab327802', '중고등 모바일', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, updated_at = EXCLUDED.updated_at;

INSERT INTO project_environments
  (id, project_id, name, start_url, sort_order, created_at, updated_at) VALUES
  ('d95ac33b-a8e7-4a19-8acc-37a1275a3edc', 'fa509809-246a-459f-879d-d803df29bb7e', '운영', 'https://me.vivasam.com/#/', 0, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
  ('97fc41b6-1493-47b5-8cc7-afc8ebb25f34', 'fa509809-246a-459f-879d-d803df29bb7e', 'dev', 'https://me-dev.vivasam.com/#/', 1, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
  ('e561f2fe-6943-4341-8fd6-8f49158e6327', 'fa509809-246a-459f-879d-d803df29bb7e', 'dev2', 'https://dev2-me.vivasam.com/', 2, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
  ('4db00e4f-0021-4f9d-9fe7-c7998a852855', '24b5a282-dc22-4f11-b1b8-d6d8ab327802', '운영', 'https://mv.vivasam.com/#/', 0, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
  ('b55d66a3-13f3-4ff2-92e2-6ae36b4e75cc', '24b5a282-dc22-4f11-b1b8-d6d8ab327802', 'dev', 'https://mv-dev.vivasam.com/#/', 1, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
  ('1048e83f-0856-44c4-8f21-4d6445dca8aa', '24b5a282-dc22-4f11-b1b8-d6d8ab327802', 'dev2', 'https://dev2-mv.vivasam.com/', 2, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  start_url = EXCLUDED.start_url,
  sort_order = EXCLUDED.sort_order,
  updated_at = EXCLUDED.updated_at;

COMMIT;
```

적용 후 확인:

```sql
SELECT p.name AS project_name, e.name AS environment_name, e.start_url, e.sort_order
FROM projects p
JOIN project_environments e ON e.project_id = p.id
WHERE p.id IN ('fa509809-246a-459f-879d-d803df29bb7e', '24b5a282-dc22-4f11-b1b8-d6d8ab327802')
ORDER BY p.name, e.sort_order;
```

새 DB에서는 프로젝트 2개, 환경 6개가 조회되어야 한다. 이미 같은 프로젝트에 다른 ID의 환경이 같은 순서로 등록되어 있다면 `UNIQUE (project_id, sort_order)` 제약으로 삽입이 거부된다. 그 경우 기존 환경과의 병합 방식을 정한 후 적용한다.
