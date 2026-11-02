-- actions and APIs describe what they do, their inputs
-- and outputs (with formats); entity fields carry a required type plus format/enum/reference.

-- 1) Action inputs / outputs: lists of typed parameters, optionally bound to an entity field.
--    description stays the purpose ("Purpose"); the formats are free text such as
--    "JSON request body (application/json)".
ALTER TABLE model_node ADD COLUMN inputs jsonb NOT NULL DEFAULT '[]'::jsonb
  CHECK (jsonb_typeof(inputs) = 'array');
ALTER TABLE model_node ADD COLUMN outputs jsonb NOT NULL DEFAULT '[]'::jsonb
  CHECK (jsonb_typeof(outputs) = 'array');
ALTER TABLE model_node ADD COLUMN input_format text CHECK (input_format IS NULL OR length(input_format) <= 500);
ALTER TABLE model_node ADD COLUMN output_format text CHECK (output_format IS NULL OR length(output_format) <= 500);

-- 2) Entity fields: required flag, format, example, enum values, reference to another entity.
ALTER TABLE entity_attribute ADD COLUMN required boolean NOT NULL DEFAULT false;
ALTER TABLE entity_attribute ADD COLUMN format text CHECK (format IS NULL OR length(format) <= 200);
ALTER TABLE entity_attribute ADD COLUMN example text CHECK (example IS NULL OR length(example) <= 500);
ALTER TABLE entity_attribute ADD COLUMN enum_values jsonb NOT NULL DEFAULT '[]'::jsonb
  CHECK (jsonb_typeof(enum_values) = 'array');
ALTER TABLE entity_attribute ADD COLUMN ref_node_id uuid REFERENCES model_node(id) ON DELETE SET NULL;
ALTER TABLE entity_attribute DROP CONSTRAINT entity_attribute_data_type_check;
ALTER TABLE entity_attribute ADD CONSTRAINT entity_attribute_data_type_check CHECK (data_type IN
  ('string','integer','number','decimal','money','boolean','date','datetime','enum','reference',
   'object','array'));
ALTER TABLE entity_attribute ALTER COLUMN data_type DROP DEFAULT;

-- 3) API registry: request / response content types (JSON, form, ...); description = purpose.
ALTER TABLE api_endpoint ADD COLUMN request_content_type text
  CHECK (request_content_type IS NULL OR length(request_content_type) <= 200);
ALTER TABLE api_endpoint ADD COLUMN response_content_type text
  CHECK (response_content_type IS NULL OR length(response_content_type) <= 200);
UPDATE api_endpoint SET request_content_type = 'application/json'
  WHERE request_content_type IS NULL AND request_schema ? 'body';
UPDATE api_endpoint SET response_content_type = 'application/json'
  WHERE response_content_type IS NULL AND response_schema IS NOT NULL;

-- 4) AI suggestion: inputs/outputs/purpose for an existing action
ALTER TABLE model_suggestion DROP CONSTRAINT model_suggestion_kind_check;
ALTER TABLE model_suggestion ADD CONSTRAINT model_suggestion_kind_check
  CHECK (kind IN ('node', 'attribute', 'field', 'io'));
