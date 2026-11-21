-- Cross-requirement chains derived from action effects and preconditions.

CREATE TABLE case_gen_chain (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES version(id) ON DELETE CASCADE,
  strategy_id uuid REFERENCES test_strategy(id) ON DELETE SET NULL,
  fingerprint text NOT NULL,
  actions jsonb NOT NULL,
  transitions jsonb NOT NULL,
  requirement_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX case_gen_chain_fp ON case_gen_chain(version_id, fingerprint);
CREATE INDEX ON case_gen_chain(version_id);

ALTER TABLE test_case ADD COLUMN chain_id uuid REFERENCES case_gen_chain(id) ON DELETE SET NULL;
CREATE INDEX ON test_case(chain_id);
