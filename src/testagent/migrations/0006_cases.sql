-- M1-07: cases record the model snapshot (BR-02) and their normal/boundary/exception scenario (BR-04);
-- coverage reports keep their origin; corrections are looked up by target.
ALTER TABLE test_case
  ADD COLUMN snapshot_id uuid REFERENCES model_snapshot(id),
  ADD COLUMN scenario text CHECK (scenario IN ('normal', 'boundary', 'exception'));
ALTER TABLE coverage_report
  ADD COLUMN source text NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'agent')),
  ADD COLUMN agent_run_id uuid REFERENCES agent_run(id);
CREATE INDEX ON correction(target_type, target_id);
CREATE INDEX ON test_case(origin_version_id);
