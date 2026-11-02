-- M1-05: requirement confirmation bookkeeping and model-suggestion de-duplication.
ALTER TABLE requirement
  ADD COLUMN confirmed_at timestamptz,
  ADD COLUMN confirmed_by text;

ALTER TABLE model_suggestion
  ADD COLUMN kind text NOT NULL DEFAULT 'node' CHECK (kind IN ('node', 'attribute')),
  ADD COLUMN dedup_key text NOT NULL DEFAULT '',
  ADD COLUMN resolved_node_id uuid REFERENCES model_node(id),
  ADD COLUMN reason text,
  ADD COLUMN decided_by text;
CREATE UNIQUE INDEX model_suggestion_pending_uq ON model_suggestion(sut_id, dedup_key)
  WHERE status = 'pending';
