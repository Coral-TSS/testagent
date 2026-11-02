-- 2026-11-01: an entity field is named after the code entity / API field
-- (e.g. amount_minor); the database column may be named differently, kept as storage_name.
ALTER TABLE entity_attribute ADD COLUMN storage_name text
  CHECK (storage_name IS NULL OR length(storage_name) <= 100);
