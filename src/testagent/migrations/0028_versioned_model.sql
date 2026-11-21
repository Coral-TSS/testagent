-- Each version has its own editable model. API endpoints stay on the system;
-- node_api_link rows are copied so each version binds the same system APIs.

ALTER TABLE model_node ADD COLUMN version_id uuid REFERENCES version(id);
ALTER TABLE model_edge ADD COLUMN version_id uuid REFERENCES version(id);
ALTER TABLE model_link ADD COLUMN version_id uuid REFERENCES version(id);
ALTER TABLE model_suggestion ADD COLUMN version_id uuid REFERENCES version(id);

DROP INDEX model_node_name_uq;
CREATE UNIQUE INDEX model_node_name_uq
  ON model_node (sut_id, version_id, kind, name) NULLS NOT DISTINCT
  WHERE deleted_at IS NULL;
CREATE INDEX model_node_version_idx ON model_node(version_id);
CREATE INDEX model_edge_version_idx ON model_edge(version_id);
CREATE INDEX model_link_version_idx ON model_link(version_id);
CREATE INDEX model_suggestion_version_idx ON model_suggestion(version_id);

DROP INDEX model_suggestion_pending_uq;
CREATE UNIQUE INDEX model_suggestion_pending_uq
  ON model_suggestion (sut_id, version_id, dedup_key) NULLS NOT DISTINCT
  WHERE status = 'pending';

-- Rewrite attribute_id / node_id / link_id inside a JSON array using the copy maps.
CREATE OR REPLACE FUNCTION remap_rule_ids(items jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  result jsonb := '[]'::jsonb;
  item jsonb;
  raw text;
  mapped text;
  key text;
BEGIN
  IF items IS NULL OR jsonb_typeof(items) <> 'array' THEN
    RETURN COALESCE(items, '[]'::jsonb);
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(items) LOOP
    IF jsonb_typeof(item) = 'object' THEN
      FOREACH key IN ARRAY ARRAY['attribute_id', 'node_id', 'link_id', 'from_node_id', 'to_node_id'] LOOP
        raw := item->>key;
        IF raw IS NULL OR raw !~ '^[0-9a-fA-F-]{36}$' THEN
          CONTINUE;
        END IF;
        mapped := NULL;
        IF key IN ('attribute_id') THEN
          SELECT new_id::text INTO mapped FROM _attr_map WHERE old_id = raw::uuid;
        ELSIF key IN ('link_id') THEN
          SELECT new_id::text INTO mapped FROM _link_map WHERE old_id = raw::uuid;
        ELSE
          SELECT new_id::text INTO mapped FROM _node_map WHERE old_id = raw::uuid;
        END IF;
        IF mapped IS NOT NULL THEN
          item := jsonb_set(item, ARRAY[key], to_jsonb(mapped));
        END IF;
      END LOOP;
    END IF;
    result := result || jsonb_build_array(item);
  END LOOP;
  RETURN result;
END $$;

CREATE OR REPLACE FUNCTION remap_payload_ids(payload jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  result jsonb;
  key text;
  raw text;
  mapped text;
  child jsonb;
BEGIN
  IF payload IS NULL THEN
    RETURN NULL;
  END IF;
  IF jsonb_typeof(payload) = 'array' THEN
    RETURN remap_rule_ids(payload);
  END IF;
  IF jsonb_typeof(payload) <> 'object' THEN
    RETURN payload;
  END IF;
  result := payload;
  FOR key, child IN SELECT e.key, e.value FROM jsonb_each(payload) AS e LOOP
    IF jsonb_typeof(child) = 'object' OR jsonb_typeof(child) = 'array' THEN
      result := jsonb_set(result, ARRAY[key], remap_payload_ids(child));
      CONTINUE;
    END IF;
    raw := payload->>key;
    IF raw IS NULL OR raw !~ '^[0-9a-fA-F-]{36}$' THEN
      CONTINUE;
    END IF;
    IF key NOT IN ('attribute_id', 'node_id', 'link_id', 'from_node_id', 'to_node_id',
                   'via_node_id', 'fk_attribute_id', 'rename_attribute_id', 'resolved_node_id') THEN
      CONTINUE;
    END IF;
    mapped := NULL;
    IF key IN ('attribute_id', 'fk_attribute_id', 'rename_attribute_id') THEN
      SELECT new_id::text INTO mapped FROM _attr_map WHERE old_id = raw::uuid;
    ELSIF key = 'link_id' THEN
      SELECT new_id::text INTO mapped FROM _link_map WHERE old_id = raw::uuid;
    ELSE
      SELECT new_id::text INTO mapped FROM _node_map WHERE old_id = raw::uuid;
    END IF;
    IF mapped IS NOT NULL THEN
      result := jsonb_set(result, ARRAY[key], to_jsonb(mapped));
    END IF;
  END LOOP;
  RETURN result;
END $$;

CREATE OR REPLACE FUNCTION copy_version_model(source_version uuid, dest_version uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  sut uuid;
BEGIN
  SELECT v.sut_id INTO sut FROM version v WHERE v.id = source_version;
  IF sut IS NULL THEN
    RAISE EXCEPTION 'source version % not found', source_version;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM version WHERE id = dest_version AND sut_id = sut) THEN
    RAISE EXCEPTION 'destination version does not belong to the same system';
  END IF;
  IF EXISTS (SELECT 1 FROM model_node WHERE version_id = dest_version AND deleted_at IS NULL) THEN
    RETURN;
  END IF;

  CREATE TEMP TABLE IF NOT EXISTS _node_map (old_id uuid PRIMARY KEY, new_id uuid NOT NULL) ON COMMIT DROP;
  CREATE TEMP TABLE IF NOT EXISTS _attr_map (old_id uuid PRIMARY KEY, new_id uuid NOT NULL) ON COMMIT DROP;
  CREATE TEMP TABLE IF NOT EXISTS _link_map (old_id uuid PRIMARY KEY, new_id uuid NOT NULL) ON COMMIT DROP;
  TRUNCATE _node_map, _attr_map, _link_map;

  INSERT INTO _node_map(old_id, new_id)
  SELECT id, gen_random_uuid() FROM model_node
  WHERE version_id = source_version AND deleted_at IS NULL;

  INSERT INTO model_node(
    id, sut_id, version_id, module_id, kind, name, description, data_schema, attributes, code_ref,
    inputs, outputs, input_format, output_format, preconditions, effects)
  SELECT m.new_id, n.sut_id, dest_version, n.module_id, n.kind, n.name, n.description, n.data_schema,
    n.attributes, n.code_ref, n.inputs, n.outputs, n.input_format, n.output_format,
    n.preconditions, n.effects
  FROM model_node n JOIN _node_map m ON m.old_id = n.id;

  INSERT INTO _attr_map(old_id, new_id)
  SELECT a.id, gen_random_uuid() FROM entity_attribute a
  JOIN _node_map m ON m.old_id = a.node_id
  WHERE a.deleted_at IS NULL;

  INSERT INTO entity_attribute(
    id, sut_id, node_id, name, display_name, data_type, unit, constraints, description, position,
    required, format, example, enum_values, ref_node_id, storage_name)
  SELECT am.new_id, a.sut_id, nm.new_id, a.name, a.display_name, a.data_type, a.unit, a.constraints,
    a.description, a.position, a.required, a.format, a.example, a.enum_values, rnm.new_id, a.storage_name
  FROM entity_attribute a
  JOIN _attr_map am ON am.old_id = a.id
  JOIN _node_map nm ON nm.old_id = a.node_id
  LEFT JOIN _node_map rnm ON rnm.old_id = a.ref_node_id;

  INSERT INTO _link_map(old_id, new_id)
  SELECT l.id, gen_random_uuid() FROM model_link l
  WHERE l.version_id = source_version AND l.deleted_at IS NULL;

  INSERT INTO model_link(
    id, sut_id, version_id, from_node_id, to_node_id, forward_name, reverse_name,
    forward_api_name, reverse_api_name, cardinality, fk_attribute_id, via_node_id,
    via_from_attribute_id, via_to_attribute_id, required, description, legacy_node_id)
  SELECT lm.new_id, l.sut_id, dest_version, fn.new_id, tn.new_id, l.forward_name, l.reverse_name,
    l.forward_api_name, l.reverse_api_name, l.cardinality, fk.new_id, vn.new_id,
    vf.new_id, vt.new_id, l.required, l.description, leg.new_id
  FROM model_link l
  JOIN _link_map lm ON lm.old_id = l.id
  JOIN _node_map fn ON fn.old_id = l.from_node_id
  JOIN _node_map tn ON tn.old_id = l.to_node_id
  LEFT JOIN _attr_map fk ON fk.old_id = l.fk_attribute_id
  LEFT JOIN _node_map vn ON vn.old_id = l.via_node_id
  LEFT JOIN _attr_map vf ON vf.old_id = l.via_from_attribute_id
  LEFT JOIN _attr_map vt ON vt.old_id = l.via_to_attribute_id
  LEFT JOIN _node_map leg ON leg.old_id = l.legacy_node_id;

  INSERT INTO model_edge(sut_id, version_id, source_node_id, target_node_id, role)
  SELECT e.sut_id, dest_version, s.new_id, t.new_id, e.role
  FROM model_edge e
  JOIN _node_map s ON s.old_id = e.source_node_id
  JOIN _node_map t ON t.old_id = e.target_node_id
  WHERE e.invalid_at IS NULL AND e.version_id = source_version;

  INSERT INTO node_api_link(node_id, api_id)
  SELECT m.new_id, l.api_id FROM node_api_link l
  JOIN _node_map m ON m.old_id = l.node_id
  WHERE l.invalid_at IS NULL;

  UPDATE model_node n
  SET preconditions = remap_rule_ids(n.preconditions),
      effects = remap_rule_ids(n.effects),
      inputs = remap_rule_ids(n.inputs),
      outputs = remap_rule_ids(n.outputs)
  WHERE n.version_id = dest_version;

  INSERT INTO model_review_mark(sut_id, target_type, target_id, reviewed, digest, note, reviewed_by, reviewed_at)
  SELECT mk.sut_id, mk.target_type,
    CASE WHEN mk.target_type = 'link' THEN lm.new_id ELSE nm.new_id END,
    mk.reviewed, mk.digest, mk.note, mk.reviewed_by, mk.reviewed_at
  FROM model_review_mark mk
  LEFT JOIN _node_map nm ON nm.old_id = mk.target_id AND mk.target_type IN ('entity', 'action')
  LEFT JOIN _link_map lm ON lm.old_id = mk.target_id AND mk.target_type = 'link'
  WHERE mk.sut_id = sut
    AND ((mk.target_type IN ('entity', 'action') AND nm.new_id IS NOT NULL)
      OR (mk.target_type = 'link' AND lm.new_id IS NOT NULL));
END $$;

CREATE OR REPLACE FUNCTION remap_version_refs(dest_version uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE requirement_node_link l SET node_id = m.new_id
  FROM requirement r, _node_map m
  WHERE l.requirement_id = r.id AND r.version_id = dest_version AND l.node_id = m.old_id;

  UPDATE requirement_attribute_link l SET attribute_id = m.new_id
  FROM requirement r, _attr_map m
  WHERE l.requirement_id = r.id AND r.version_id = dest_version AND l.attribute_id = m.old_id;

  UPDATE requirement_link_ref l SET link_id = m.new_id
  FROM requirement r, _link_map m
  WHERE l.requirement_id = r.id AND r.version_id = dest_version AND l.link_id = m.old_id;

  UPDATE case_node_link cl SET node_id = m.new_id
  FROM _node_map m
  WHERE cl.node_id = m.old_id AND (
    EXISTS (SELECT 1 FROM test_case c WHERE c.id = cl.case_id AND c.origin_version_id = dest_version)
    OR EXISTS (
      SELECT 1 FROM case_requirement_link cr JOIN requirement r ON r.id = cr.requirement_id
      WHERE cr.case_id = cl.case_id AND r.version_id = dest_version
    )
  );

  UPDATE case_attribute_link cl SET attribute_id = m.new_id
  FROM _attr_map m
  WHERE cl.attribute_id = m.old_id AND (
    EXISTS (SELECT 1 FROM test_case c WHERE c.id = cl.case_id AND c.origin_version_id = dest_version)
    OR EXISTS (
      SELECT 1 FROM case_requirement_link cr JOIN requirement r ON r.id = cr.requirement_id
      WHERE cr.case_id = cl.case_id AND r.version_id = dest_version
    )
  );

  UPDATE model_suggestion s
  SET resolved_node_id = m.new_id, payload = remap_payload_ids(s.payload)
  FROM _node_map m
  WHERE s.version_id = dest_version AND s.resolved_node_id = m.old_id;

  UPDATE model_suggestion s
  SET payload = remap_payload_ids(s.payload)
  WHERE s.version_id = dest_version AND s.resolved_node_id IS NULL;
END $$;

-- Existing rows were one live model per system. Keep those ids on the latest version
-- and give every older version its own copy, with that version's references moved over.
DO $$
DECLARE
  sut_row record;
  ver record;
  primary_id uuid;
BEGIN
  FOR sut_row IN SELECT id FROM sut LOOP
    SELECT id INTO primary_id FROM version WHERE sut_id = sut_row.id ORDER BY created_at DESC LIMIT 1;
    IF primary_id IS NULL THEN
      CONTINUE;
    END IF;
    UPDATE model_node SET version_id = primary_id WHERE sut_id = sut_row.id AND version_id IS NULL;
    UPDATE model_edge e SET version_id = n.version_id
    FROM model_node n
    WHERE n.id = e.source_node_id AND e.sut_id = sut_row.id AND e.version_id IS NULL;
    UPDATE model_link l SET version_id = n.version_id
    FROM model_node n
    WHERE n.id = l.from_node_id AND l.sut_id = sut_row.id AND l.version_id IS NULL;
    UPDATE model_suggestion s SET version_id = r.version_id
    FROM requirement r
    WHERE s.requirement_id = r.id AND s.sut_id = sut_row.id AND s.version_id IS NULL;
    UPDATE model_suggestion SET version_id = primary_id
    WHERE sut_id = sut_row.id AND version_id IS NULL;
    FOR ver IN
      SELECT id FROM version WHERE sut_id = sut_row.id AND id <> primary_id ORDER BY created_at
    LOOP
      PERFORM copy_version_model(primary_id, ver.id);
      PERFORM remap_version_refs(ver.id);
    END LOOP;
  END LOOP;
END $$;
