-- M1-04: agent run bookkeeping, LLM config key reference, interrupted-run recovery.
ALTER TABLE agent_run
  ADD COLUMN sut_id uuid REFERENCES sut(id),
  ADD COLUMN thread_id text,
  ADD COLUMN result jsonb,
  ADD COLUMN error_code text,
  ADD COLUMN injected jsonb NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX ON agent_run(status);

ALTER TABLE agent_config ADD COLUMN api_key_ref text;  -- name in runtime/secrets.json, never the key

ALTER TABLE task_run ADD COLUMN error text;
