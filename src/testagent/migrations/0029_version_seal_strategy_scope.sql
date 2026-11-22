-- Sealed versions (demo v1.0) and fixed strategy scopes.
-- test_task gains browser_use; existing agent/automation/human rows are unchanged.

ALTER TABLE version ADD COLUMN sealed boolean NOT NULL DEFAULT false;

-- Free-text scope → the fixed options. Text that does not clearly match is left empty
-- so the next edit must choose again. Recognized pieces:
--   需求 / requirement          → 需求
--   缺陷 / 回归 / defect / regression → 缺陷回归
--   主要流程 / 主流程 / 冒烟 / smoke / main flow → 主要流程
--   性能 / performance          → 性能
CREATE OR REPLACE FUNCTION map_strategy_scope(raw text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  text_norm text := lower(coalesce(raw, ''));
  items jsonb := '[]'::jsonb;
BEGIN
  IF text_norm ~ '需求' OR text_norm ~ 'requirement' THEN
    items := items || '["需求"]'::jsonb;
  END IF;
  IF text_norm ~ '缺陷' OR text_norm ~ '回归' OR text_norm ~ 'defect' OR text_norm ~ 'regression' THEN
    items := items || '["缺陷回归"]'::jsonb;
  END IF;
  IF text_norm ~ '主要流程' OR text_norm ~ '主流程' OR text_norm ~ '冒烟'
     OR text_norm ~ 'smoke' OR text_norm ~ 'main flow' THEN
    items := items || '["主要流程"]'::jsonb;
  END IF;
  IF text_norm ~ '性能' OR text_norm ~ 'performance' THEN
    items := items || '["性能"]'::jsonb;
  END IF;
  RETURN items;
END;
$$;

ALTER TABLE test_strategy ALTER COLUMN scope DROP DEFAULT;
ALTER TABLE test_strategy ALTER COLUMN scope TYPE jsonb USING map_strategy_scope(scope);
ALTER TABLE test_strategy ALTER COLUMN scope SET DEFAULT '[]'::jsonb;
ALTER TABLE test_strategy ALTER COLUMN scope SET NOT NULL;
ALTER TABLE test_strategy DROP CONSTRAINT IF EXISTS test_strategy_scope_items;
ALTER TABLE test_strategy ADD CONSTRAINT test_strategy_scope_items CHECK (
  jsonb_typeof(scope) = 'array'
  AND scope <@ '["需求", "缺陷回归", "主要流程", "性能"]'::jsonb
);

DO $$
DECLARE
  cname text;
BEGIN
  SELECT con.conname INTO cname
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
  WHERE rel.relname = 'test_task' AND nsp.nspname = current_schema()
    AND con.contype = 'c' AND pg_get_constraintdef(con.oid) LIKE '%executor%';
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE test_task DROP CONSTRAINT %I', cname);
  END IF;
END $$;

ALTER TABLE test_task ADD CONSTRAINT test_task_executor_check
  CHECK (executor IN ('agent', 'automation', 'human', 'browser_use'));
