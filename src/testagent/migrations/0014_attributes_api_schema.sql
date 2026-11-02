-- Entity fields as rows and API schemas.
-- 1) Entity attributes (fields) as first-class rows; requirements and cases can reference them.
CREATE TABLE entity_attribute (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id) ON DELETE CASCADE,
  node_id uuid NOT NULL REFERENCES model_node(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
  display_name text CHECK (display_name IS NULL OR length(display_name) <= 100),
  data_type text NOT NULL DEFAULT 'string' CHECK (data_type IN
    ('string','integer','number','decimal','money','boolean','date','datetime','enum','object','array')),
  unit text CHECK (unit IS NULL OR length(unit) <= 50),
  constraints jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(constraints) = 'array'),
  description text,
  position integer NOT NULL DEFAULT 0,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX entity_attribute_name_uq ON entity_attribute(node_id, lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX entity_attribute_sut_idx ON entity_attribute(sut_id);
CREATE TRIGGER entity_attribute_touch BEFORE UPDATE ON entity_attribute
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE requirement_attribute_link (
  requirement_id uuid NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
  attribute_id uuid NOT NULL REFERENCES entity_attribute(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('actor','condition','action','result','constraint')),
  PRIMARY KEY (requirement_id, attribute_id, role));
CREATE INDEX requirement_attribute_link_attr_idx ON requirement_attribute_link(attribute_id);

CREATE TABLE case_attribute_link (
  case_id uuid NOT NULL REFERENCES test_case(id) ON DELETE CASCADE,
  attribute_id uuid NOT NULL REFERENCES entity_attribute(id) ON DELETE CASCADE,
  PRIMARY KEY (case_id, attribute_id));

-- existing free-form data_schema {"field": "type"} becomes attribute rows (data_schema is kept)
INSERT INTO entity_attribute(sut_id, node_id, name, data_type, description, position)
SELECT n.sut_id, n.id, e.key,
       CASE lower(coalesce(e.value->>'type', e.value #>> '{}'))
         WHEN 'string' THEN 'string' WHEN 'str' THEN 'string' WHEN 'text' THEN 'string'
         WHEN 'integer' THEN 'integer' WHEN 'int' THEN 'integer'
         WHEN 'number' THEN 'number' WHEN 'float' THEN 'number' WHEN 'double' THEN 'number'
         WHEN 'decimal' THEN 'decimal' WHEN 'money' THEN 'money'
         WHEN 'boolean' THEN 'boolean' WHEN 'bool' THEN 'boolean'
         WHEN 'date' THEN 'date' WHEN 'datetime' THEN 'datetime' WHEN 'timestamp' THEN 'datetime'
         WHEN 'enum' THEN 'enum' WHEN 'object' THEN 'object' WHEN 'array' THEN 'array'
         ELSE 'string' END,
       'migrated from data_schema: ' || e.value::text,
       e.ord::int
FROM model_node n
CROSS JOIN LATERAL jsonb_each(n.data_schema) WITH ORDINALITY AS e(key, value, ord)
WHERE n.kind = 'entity' AND n.deleted_at IS NULL AND jsonb_typeof(n.data_schema) = 'object'
  AND length(btrim(e.key)) BETWEEN 1 AND 100;

-- 2) API registry: request/response schema (manual or imported from the SUT's OpenAPI)
ALTER TABLE api_endpoint ADD COLUMN request_schema jsonb;
ALTER TABLE api_endpoint ADD COLUMN response_schema jsonb;
ALTER TABLE api_endpoint ADD COLUMN operation_id text;
ALTER TABLE api_endpoint ADD COLUMN schema_source text CHECK (schema_source IS NULL OR schema_source IN ('manual','openapi'));

-- 3) Automation outcome on the case: a failed final self-check is never bound
ALTER TABLE test_case ADD COLUMN automation_status text CHECK (automation_status IS NULL OR automation_status IN ('ok','needs_fix'));
ALTER TABLE test_case ADD COLUMN automation_note text;
ALTER TABLE test_case ADD COLUMN automation_draft_path text;
ALTER TABLE test_case ADD COLUMN automation_draft_commit text;
UPDATE test_case SET automation_status = 'ok' WHERE mode = 'automated' AND code_path IS NOT NULL;

ALTER TABLE agent_config ADD COLUMN max_self_checks integer NOT NULL DEFAULT 5 CHECK (max_self_checks BETWEEN 1 AND 20);
ALTER TABLE agent_config ADD COLUMN auto_automate boolean NOT NULL DEFAULT true;

-- 4) HTTP executor for API-type cases
ALTER TABLE case_execution DROP CONSTRAINT case_execution_executor_check;
ALTER TABLE case_execution ADD CONSTRAINT case_execution_executor_check
  CHECK (executor IN ('agent_browser','agent_api','pytest','manual'));

-- field suggestions (missing entity fields, e.g. PurchaseOrder.currency)
ALTER TABLE model_suggestion DROP CONSTRAINT model_suggestion_kind_check;
ALTER TABLE model_suggestion ADD CONSTRAINT model_suggestion_kind_check
  CHECK (kind IN ('node', 'attribute', 'field'));
