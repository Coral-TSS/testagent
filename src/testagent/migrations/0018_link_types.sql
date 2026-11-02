-- relations become first-class link types between
-- entities (Palantir Ontology style) instead of relation nodes; actions get structured
-- preconditions and effects; requirements can reference links.

-- 1) Link types: two sides with display + API names, cardinality, foreign key field, optional
--    junction entity for many-to-many.
CREATE TABLE model_link (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  from_node_id uuid NOT NULL REFERENCES model_node(id),
  to_node_id uuid NOT NULL REFERENCES model_node(id),
  -- how the "from" entity reads the link to "to" (PurchaseOrder belongs to Supplier) and back (Supplier supplies PurchaseOrder)
  forward_name text NOT NULL CHECK (length(forward_name) BETWEEN 1 AND 50),
  reverse_name text NOT NULL CHECK (length(reverse_name) BETWEEN 1 AND 50),
  forward_api_name text CHECK (forward_api_name IS NULL OR forward_api_name ~ '^[a-z][A-Za-z0-9_]{0,99}$'),
  reverse_api_name text CHECK (reverse_api_name IS NULL OR reverse_api_name ~ '^[a-z][A-Za-z0-9_]{0,99}$'),
  cardinality text NOT NULL CHECK (cardinality IN ('one_to_one','many_to_one','one_to_many','many_to_many')),
  fk_attribute_id uuid REFERENCES entity_attribute(id),
  via_node_id uuid REFERENCES model_node(id),
  via_from_attribute_id uuid REFERENCES entity_attribute(id),
  via_to_attribute_id uuid REFERENCES entity_attribute(id),
  required boolean NOT NULL DEFAULT false,
  description text CHECK (description IS NULL OR length(description) <= 2000),
  legacy_node_id uuid REFERENCES model_node(id),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (via_node_id IS NULL OR cardinality = 'many_to_many'),
  CHECK (fk_attribute_id IS NULL OR cardinality <> 'many_to_many'));
CREATE INDEX ON model_link(sut_id);
CREATE INDEX ON model_link(from_node_id);
CREATE INDEX ON model_link(to_node_id);
CREATE INDEX ON model_link(fk_attribute_id);

-- 2) Requirements can point at a link (e.g. "Payment pays PurchaseOrder")
CREATE TABLE requirement_link_ref (
  requirement_id uuid NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
  link_id uuid NOT NULL REFERENCES model_link(id),
  role text NOT NULL,
  PRIMARY KEY (requirement_id, link_id, role));
CREATE INDEX ON requirement_link_ref(link_id);

-- 3) Actions: structured preconditions ("PurchaseOrder.state == pending") and effects
--    ("PurchaseOrder.state → approved | rejected", create Payment, create link Payment pays PurchaseOrder).
ALTER TABLE model_node ADD COLUMN preconditions jsonb NOT NULL DEFAULT '[]'::jsonb
  CHECK (jsonb_typeof(preconditions) = 'array');
ALTER TABLE model_node ADD COLUMN effects jsonb NOT NULL DEFAULT '[]'::jsonb
  CHECK (jsonb_typeof(effects) = 'array');

-- 4) Suggestions: links and action rules
ALTER TABLE model_suggestion DROP CONSTRAINT model_suggestion_kind_check;
ALTER TABLE model_suggestion ADD CONSTRAINT model_suggestion_kind_check
  CHECK (kind IN ('node', 'attribute', 'field', 'io', 'link', 'rules'));

CREATE TRIGGER model_link_touch BEFORE UPDATE ON model_link FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
