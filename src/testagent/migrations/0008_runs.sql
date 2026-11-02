-- M1-09: task runs remember the environment/executor they ran with and their queue job.
ALTER TABLE task_run
  ADD COLUMN environment_id uuid REFERENCES environment(id),
  ADD COLUMN executor text,
  ADD COLUMN requested_by text,
  ADD COLUMN job_id bigint,
  ADD COLUMN total_cases integer;
CREATE INDEX task_run_active ON task_run(task_id) WHERE status IN ('queued', 'running');
CREATE INDEX test_task_due ON test_task(next_run_at) WHERE next_run_at IS NOT NULL;
