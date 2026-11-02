-- Tasks only reference cases. Cases get a category (requirement / quality / regression) and
-- optional quality tags; uncertain classifications wait as a suggestion for a human.
ALTER TABLE test_case
  ADD COLUMN category text NOT NULL DEFAULT 'requirement'
    CHECK (category IN ('requirement', 'quality', 'regression')),
  ADD COLUMN quality_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN category_suggestion jsonb;
-- task kinds line up with case categories; a task may carry a selection rule
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'test_task'::regclass
      AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%kind%' LOOP
    EXECUTE format('ALTER TABLE test_task DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
ALTER TABLE test_task ADD CONSTRAINT test_task_kind_check
  CHECK (kind IN ('requirement', 'quality', 'regression'));
ALTER TABLE test_task ADD COLUMN selector jsonb;
-- every membership says where it came from; existing rows were put there by hand
ALTER TABLE task_case
  ADD COLUMN source text NOT NULL DEFAULT 'manual' CHECK (source IN ('rule', 'manual')),
  ADD COLUMN reason text,
  ADD COLUMN added_at timestamptz NOT NULL DEFAULT now();
-- cases a person took out of a task; rules never put them back
CREATE TABLE task_case_exclusion (
  task_id uuid NOT NULL REFERENCES test_task(id) ON DELETE CASCADE,
  case_id uuid NOT NULL REFERENCES test_case(id),
  removed_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, case_id));
CREATE INDEX ON test_case(sut_id, status);
