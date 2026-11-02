-- per-element review marks of the model review page.
-- A mark is a reviewer's aid only; it never accepts a suggestion (C01). The digest of the
-- element at review time lets the page show "Changed since review".
CREATE TABLE model_review_mark (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  target_type text NOT NULL CHECK (target_type IN ('entity','action','link')),
  target_id uuid NOT NULL,
  reviewed boolean NOT NULL DEFAULT true,
  digest text,
  note text CHECK (note IS NULL OR char_length(note) <= 500),
  reviewed_by text NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sut_id, target_type, target_id));
