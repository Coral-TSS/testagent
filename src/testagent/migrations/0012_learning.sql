-- M1-12 corrections → memories / prompt versions (architecture §4.4), skills/MCP registry only.
ALTER TABLE correction
  ADD COLUMN sut_id uuid REFERENCES sut(id),
  ADD COLUMN kind text NOT NULL DEFAULT 'correction' CHECK (kind IN ('correction', 'omission')),
  ADD COLUMN attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN error text,
  ADD COLUMN agent_run_id uuid REFERENCES agent_run(id),
  ADD COLUMN outputs jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE correction DROP CONSTRAINT correction_status_check;
ALTER TABLE correction ADD CONSTRAINT correction_status_check
  CHECK (status IN ('pending', 'processing', 'processed', 'failed'));
CREATE INDEX correction_status ON correction(status, created_at DESC);

ALTER TABLE prompt_template
  ADD COLUMN created_by text NOT NULL DEFAULT 'system',
  ADD COLUMN note text,
  ADD COLUMN agent_run_id uuid REFERENCES agent_run(id);

ALTER TABLE agent_memory
  ADD COLUMN created_by text NOT NULL DEFAULT 'system',
  ADD COLUMN agent_run_id uuid REFERENCES agent_run(id);

ALTER TABLE skill ADD COLUMN source text;
ALTER TABLE mcp_server ADD COLUMN url text, ADD COLUMN description text;
