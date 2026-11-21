-- Per-requirement case-generation scope: depth and the confirmed manifest.
-- Global default depth is 1; a requirement may override it with 0, 1 or 2.

ALTER TABLE agent_config ADD COLUMN default_scope_depth smallint NOT NULL DEFAULT 1
  CHECK (default_scope_depth BETWEEN 0 AND 2);

ALTER TABLE requirement ADD COLUMN scope_depth smallint
  CHECK (scope_depth IS NULL OR scope_depth BETWEEN 0 AND 2);

CREATE TABLE case_gen_scope (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES version(id) ON DELETE CASCADE,
  requirement_id uuid NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
  depth integer NOT NULL CHECK (depth BETWEEN 0 AND 2),
  manifest jsonb NOT NULL,
  edited boolean NOT NULL DEFAULT false,
  confirmed_at timestamptz,
  confirmed_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX case_gen_scope_req_uq ON case_gen_scope(requirement_id);
CREATE INDEX ON case_gen_scope(version_id);
CREATE TRIGGER case_gen_scope_touch BEFORE UPDATE ON case_gen_scope
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
