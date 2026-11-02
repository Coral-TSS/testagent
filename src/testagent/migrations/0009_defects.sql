-- M1-10: defects get a readable per-system code and remember manual responsibility edits.
ALTER TABLE defect
  ADD COLUMN code text,
  ADD COLUMN responsible_manual boolean NOT NULL DEFAULT false,
  ADD COLUMN created_by_actor text;
CREATE UNIQUE INDEX defect_code_uq ON defect(sut_id, code);
CREATE INDEX ON defect(status);
CREATE INDEX ON defect(created_at);
CREATE INDEX ON defect_link(target_type, target_id);
