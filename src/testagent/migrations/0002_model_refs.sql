-- M1-03: edges/links pointing at a soft-deleted node are kept but marked invalid (BR-01).
ALTER TABLE model_edge ADD COLUMN invalid_at timestamptz;
ALTER TABLE model_edge ADD CONSTRAINT model_edge_no_self_loop CHECK (source_node_id <> target_node_id);
CREATE UNIQUE INDEX model_edge_active_uq ON model_edge(source_node_id, target_node_id, role)
  WHERE invalid_at IS NULL;
-- a relation node has at most one active source and one active target edge
CREATE UNIQUE INDEX model_edge_relation_end_uq ON model_edge(source_node_id, role)
  WHERE invalid_at IS NULL AND role IN ('source', 'target');
ALTER TABLE node_api_link ADD COLUMN invalid_at timestamptz;
