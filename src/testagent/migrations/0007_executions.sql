-- M1-08: executions keep their environment, agent run, executing person and the code commit used.
ALTER TABLE case_execution
  ADD COLUMN environment_id uuid REFERENCES environment(id),
  ADD COLUMN agent_run_id uuid REFERENCES agent_run(id),
  ADD COLUMN executed_by text,
  ADD COLUMN code_commit text,
  ADD COLUMN blocked_reason text;
