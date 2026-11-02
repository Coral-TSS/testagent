-- M1-06: strategy-generated tasks carry their scope and provenance (BR-03).
ALTER TABLE test_task
  ADD COLUMN description text,
  ADD COLUMN requirement_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN source text NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'agent')),
  ADD COLUMN agent_run_id uuid REFERENCES agent_run(id);
ALTER TABLE test_strategy
  ADD COLUMN confirmed_at timestamptz,
  ADD COLUMN confirmed_by text;
ALTER TABLE task_case ADD CONSTRAINT task_case_seq_positive CHECK (seq > 0);
CREATE UNIQUE INDEX task_case_seq_uq ON task_case(task_id, seq);
