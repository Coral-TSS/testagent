-- 2026-11-01: environment preflight and start command.
-- 1) An environment may carry the command that starts the system under test locally; the
--    platform can start it on request and the launcher starts it when it is not reachable.
ALTER TABLE environment ADD COLUMN start_command text
  CHECK (start_command IS NULL OR length(start_command) <= 1000);
-- 2) Automation that could not run because the environment was down is not a broken script.
ALTER TABLE test_case DROP CONSTRAINT IF EXISTS test_case_automation_status_check;
ALTER TABLE test_case ADD CONSTRAINT test_case_automation_status_check CHECK
  (automation_status IS NULL OR automation_status IN ('ok','needs_fix','env_unavailable'));
-- 3) The bundled procurement demo (ops/seed_procurement.py) starts with this command.
UPDATE environment e SET start_command =
  'uv run uvicorn examples.procurement.api:create_app --factory --host 127.0.0.1 --port 8766'
FROM sut s
WHERE s.id = e.sut_id AND s.code = 'procurement' AND e.start_command IS NULL
  AND rtrim(e.base_url, '/') IN ('http://127.0.0.1:8766', 'http://localhost:8766');
