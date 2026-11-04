-- A task run in which no case was executed because every case lacks an automation script
-- ends as 'not_executed' instead of 'passed' (batch 2 follow-up).
DO $$
DECLARE c text;
BEGIN
  FOR c IN
    SELECT con.conname FROM pg_constraint con
    WHERE con.conrelid = 'task_run'::regclass AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) LIKE '%status%'
  LOOP
    EXECUTE format('ALTER TABLE task_run DROP CONSTRAINT %I', c);
  END LOOP;
END $$;
ALTER TABLE task_run ADD CONSTRAINT task_run_status_check
  CHECK (status IN ('queued','running','passed','failed','error','cancelled','not_executed'));

-- Runs finished since 0023 whose every execution was skipped for a missing script (they were
-- recorded as passed). Older runs recorded such cases as error and keep their status.
UPDATE task_run r SET status = 'not_executed'
WHERE r.status = 'passed'
  AND EXISTS (SELECT 1 FROM case_execution e WHERE e.task_run_id = r.id)
  AND NOT EXISTS (
    SELECT 1 FROM case_execution e WHERE e.task_run_id = r.id
      AND NOT (e.status = 'skipped' AND e.failure_kind = 'no_script'));
