-- Coverage gate: a case names the targets it hits, and a waiver counts only after a person confirms it.

ALTER TABLE test_case ADD COLUMN covers jsonb NOT NULL DEFAULT '[]'::jsonb
  CHECK (jsonb_typeof(covers) = 'array');

CREATE TABLE coverage_waiver (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES version(id) ON DELETE CASCADE,
  requirement_id uuid NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
  target_id text NOT NULL,
  reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
  proposed_by text NOT NULL CHECK (proposed_by IN ('agent', 'human')),
  confirmed_by text,
  confirmed_at timestamptz,
  fingerprint text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (requirement_id, target_id, fingerprint));
CREATE INDEX ON coverage_waiver(version_id);
CREATE INDEX ON coverage_waiver(requirement_id);
