-- TestAgent M1 initial schema (PostgreSQL 17). Objects are created in the current search_path schema.

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '% is immutable', TG_TABLE_NAME USING ERRCODE = 'restrict_violation'; END $$;

CREATE TABLE person (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(trim(name)) > 0),
  title text, email text, active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE sut (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE CHECK (code ~ '^[A-Za-z][A-Za-z0-9_-]{0,63}$'),
  name text NOT NULL, description text, test_repo_path text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE environment (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id) ON DELETE CASCADE,
  name text NOT NULL, base_url text NOT NULL CHECK (base_url ~ '^https?://'), credential_ref text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sut_id, name));
CREATE INDEX ON environment(sut_id);

CREATE TABLE module (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id) ON DELETE CASCADE,
  name text NOT NULL, description text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sut_id, name));
CREATE INDEX ON module(sut_id);

CREATE TABLE model_node (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  module_id uuid REFERENCES module(id) ON DELETE SET NULL,
  kind text NOT NULL CHECK (kind IN ('entity','action','relation')),
  name text NOT NULL, description text, data_schema jsonb,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb, code_ref text, deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX model_node_name_uq ON model_node(sut_id, kind, name) WHERE deleted_at IS NULL;
CREATE INDEX ON model_node(sut_id); CREATE INDEX ON model_node(module_id);
CREATE INDEX model_node_attr_gin ON model_node USING gin (attributes jsonb_path_ops);

CREATE TABLE model_edge (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  source_node_id uuid NOT NULL REFERENCES model_node(id),
  target_node_id uuid NOT NULL REFERENCES model_node(id),
  role text NOT NULL CHECK (role IN ('source','target','actor','object','ref')),
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON model_edge(source_node_id); CREATE INDEX ON model_edge(target_node_id); CREATE INDEX ON model_edge(sut_id);

CREATE TABLE api_endpoint (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  method text NOT NULL CHECK (method IN ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS')),
  path text NOT NULL, name text, description text, code_ref text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sut_id, method, path));

CREATE TABLE node_api_link (
  node_id uuid NOT NULL REFERENCES model_node(id),
  api_id uuid NOT NULL REFERENCES api_endpoint(id) ON DELETE CASCADE,
  PRIMARY KEY (node_id, api_id));
CREATE INDEX ON node_api_link(api_id);

CREATE TABLE version (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  name text NOT NULL,
  status text NOT NULL DEFAULT 'planning' CHECK (status IN ('planning','requirements_frozen','testing','closed')),
  frozen_at timestamptz, model_snapshot_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sut_id, name));
CREATE INDEX ON version(sut_id);

CREATE TABLE model_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  version_id uuid REFERENCES version(id),
  content jsonb NOT NULL, digest text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE version ADD CONSTRAINT version_snapshot_fk FOREIGN KEY (model_snapshot_id) REFERENCES model_snapshot(id);
CREATE INDEX ON model_snapshot(version_id);

CREATE TABLE requirement (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES version(id),
  code text NOT NULL, title text NOT NULL, raw_text text,
  structured jsonb, priority text NOT NULL DEFAULT 'P1' CHECK (priority IN ('P0','P1','P2')),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','structured','confirmed')),
  source text NOT NULL DEFAULT 'human' CHECK (source IN ('human','agent')), agent_run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (version_id, code));
CREATE INDEX ON requirement(version_id);

CREATE TABLE requirement_person (
  requirement_id uuid NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
  person_id uuid NOT NULL REFERENCES person(id),
  role text NOT NULL CHECK (role IN ('owner','developer','tester')),
  PRIMARY KEY (requirement_id, person_id, role));
CREATE INDEX ON requirement_person(person_id);

CREATE TABLE requirement_node_link (
  requirement_id uuid NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
  node_id uuid NOT NULL REFERENCES model_node(id),
  role text NOT NULL CHECK (role IN ('actor','condition','action','result','constraint')),
  PRIMARY KEY (requirement_id, node_id, role));
CREATE INDEX ON requirement_node_link(node_id);

CREATE TABLE agent_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  purpose text NOT NULL, input_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled','error')),
  steps jsonb NOT NULL DEFAULT '[]'::jsonb, token_usage jsonb, error text,
  cancel_requested boolean NOT NULL DEFAULT false,
  started_at timestamptz, ended_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE model_suggestion (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  requirement_id uuid REFERENCES requirement(id) ON DELETE SET NULL,
  agent_run_id uuid REFERENCES agent_run(id),
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON model_suggestion(sut_id); CREATE INDEX ON model_suggestion(requirement_id);

CREATE TABLE test_strategy (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL UNIQUE REFERENCES version(id),
  scope text, test_types jsonb NOT NULL DEFAULT '[]'::jsonb, intensity text, notes text,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','confirmed')),
  revision integer NOT NULL DEFAULT 1,
  source text NOT NULL DEFAULT 'human' CHECK (source IN ('human','agent')), agent_run_id uuid REFERENCES agent_run(id),
  snapshot_id uuid REFERENCES model_snapshot(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE test_task (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES version(id),
  strategy_id uuid REFERENCES test_strategy(id) ON DELETE SET NULL,
  name text NOT NULL,
  kind text NOT NULL DEFAULT 'requirement' CHECK (kind IN ('requirement','regression')),
  executor text NOT NULL DEFAULT 'agent' CHECK (executor IN ('agent','automation','human')),
  environment_id uuid REFERENCES environment(id),
  schedule jsonb, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','ready','running','done','cancelled','archived')),
  next_run_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON test_task(version_id); CREATE INDEX ON test_task(next_run_at) WHERE next_run_at IS NOT NULL;

CREATE TABLE test_case (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  origin_version_id uuid REFERENCES version(id),
  code text NOT NULL, title text NOT NULL, test_point text,
  priority text NOT NULL DEFAULT 'P1' CHECK (priority IN ('P0','P1','P2')),
  type_tag text NOT NULL DEFAULT 'functional',
  mode text NOT NULL DEFAULT 'manual' CHECK (mode IN ('manual','automated')),
  preconditions text, steps jsonb NOT NULL DEFAULT '[]'::jsonb, test_data jsonb, expected text,
  code_path text, code_commit text,
  source text NOT NULL DEFAULT 'human' CHECK (source IN ('human','agent')), agent_run_id uuid REFERENCES agent_run(id),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','ready','deprecated')),
  revision integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sut_id, code));
CREATE INDEX ON test_case(sut_id, status);

CREATE TABLE case_revision (
  case_id uuid NOT NULL REFERENCES test_case(id) ON DELETE CASCADE,
  revision integer NOT NULL, content jsonb NOT NULL, author text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (case_id, revision));

CREATE TABLE task_case (
  task_id uuid NOT NULL REFERENCES test_task(id) ON DELETE CASCADE,
  case_id uuid NOT NULL REFERENCES test_case(id),
  seq integer NOT NULL, PRIMARY KEY (task_id, case_id));
CREATE INDEX ON task_case(case_id);

CREATE TABLE case_requirement_link (
  case_id uuid NOT NULL REFERENCES test_case(id) ON DELETE CASCADE,
  requirement_id uuid NOT NULL REFERENCES requirement(id),
  PRIMARY KEY (case_id, requirement_id));
CREATE INDEX ON case_requirement_link(requirement_id);

CREATE TABLE case_node_link (
  case_id uuid NOT NULL REFERENCES test_case(id) ON DELETE CASCADE,
  node_id uuid NOT NULL REFERENCES model_node(id),
  PRIMARY KEY (case_id, node_id));
CREATE INDEX ON case_node_link(node_id);

CREATE TABLE coverage_report (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES version(id),
  content jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON coverage_report(version_id);

CREATE TABLE task_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL REFERENCES test_task(id),
  trigger text NOT NULL DEFAULT 'manual' CHECK (trigger IN ('manual','schedule')),
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','passed','failed','error','cancelled')),
  cancel_requested boolean NOT NULL DEFAULT false,
  started_at timestamptz, ended_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON task_run(task_id);

CREATE TABLE case_execution (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_run_id uuid REFERENCES task_run(id),
  case_id uuid NOT NULL REFERENCES test_case(id),
  executor text NOT NULL CHECK (executor IN ('agent_browser','pytest','manual')),
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','passed','failed','error','blocked','skipped')),
  result text, failed_assertion text, test_data jsonb,
  steps_recorded jsonb NOT NULL DEFAULT '[]'::jsonb, artifacts jsonb NOT NULL DEFAULT '[]'::jsonb,
  duration_ms integer, error text, started_at timestamptz, ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON case_execution(task_run_id); CREATE INDEX ON case_execution(case_id, ended_at);

CREATE TABLE defect (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sut_id uuid NOT NULL REFERENCES sut(id),
  version_id uuid REFERENCES version(id),
  execution_id uuid REFERENCES case_execution(id),
  case_id uuid REFERENCES test_case(id),
  title text NOT NULL, description text,
  severity text NOT NULL DEFAULT 'major' CHECK (severity IN ('critical','major','minor','trivial')),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','resolved','closed','rejected')),
  cause_category text NOT NULL DEFAULT 'unknown'
    CHECK (cause_category IN ('requirement','design','development','test','environment','unknown')),
  suggested_cause text CHECK (suggested_cause IS NULL OR suggested_cause IN ('requirement','design','development','test','environment','unknown')),
  created_by text NOT NULL DEFAULT 'human' CHECK (created_by IN ('human','agent')),
  analysis text, agent_run_id uuid REFERENCES agent_run(id), resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON defect(version_id); CREATE INDEX ON defect(execution_id); CREATE INDEX ON defect(case_id); CREATE INDEX ON defect(sut_id);

CREATE TABLE defect_requirement (
  defect_id uuid NOT NULL REFERENCES defect(id) ON DELETE CASCADE,
  requirement_id uuid NOT NULL REFERENCES requirement(id),
  inferred boolean NOT NULL DEFAULT true, PRIMARY KEY (defect_id, requirement_id));
CREATE INDEX ON defect_requirement(requirement_id);

CREATE TABLE defect_responsible (
  defect_id uuid NOT NULL REFERENCES defect(id) ON DELETE CASCADE,
  person_id uuid NOT NULL REFERENCES person(id),
  role text NOT NULL CHECK (role IN ('owner','developer','tester')),
  inferred boolean NOT NULL DEFAULT true, PRIMARY KEY (defect_id, person_id, role));
CREATE INDEX ON defect_responsible(person_id);

CREATE TABLE defect_link (
  defect_id uuid NOT NULL REFERENCES defect(id) ON DELETE CASCADE,
  target_type text NOT NULL CHECK (target_type IN ('node','api')),
  target_id uuid NOT NULL, PRIMARY KEY (defect_id, target_type, target_id));

CREATE TABLE severity_weight (
  severity text PRIMARY KEY CHECK (severity IN ('critical','major','minor','trivial')),
  weight numeric NOT NULL CHECK (weight >= 0));
INSERT INTO severity_weight VALUES ('critical',5),('major',3),('minor',1),('trivial',0.5);

CREATE TABLE report (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type text NOT NULL CHECK (scope_type IN ('task_run','version')),
  scope_id uuid NOT NULL, content jsonb NOT NULL, ai_summary text, weights_used jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON report(scope_type, scope_id);

CREATE TABLE correction (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_type text NOT NULL, target_id uuid NOT NULL, content text NOT NULL, author text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processed','failed')),
  created_at timestamptz NOT NULL DEFAULT now(), processed_at timestamptz);

CREATE TABLE agent_config (
  id text PRIMARY KEY DEFAULT 'default' CHECK (id = 'default'),
  base_url text, model text, temperature numeric NOT NULL DEFAULT 0.2,
  max_tokens integer, timeout_s integer NOT NULL DEFAULT 600, max_steps integer NOT NULL DEFAULT 30,
  updated_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE prompt_template (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL, version integer NOT NULL, content text NOT NULL,
  active boolean NOT NULL DEFAULT false, source_correction_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (name, version));
CREATE UNIQUE INDEX prompt_template_one_active ON prompt_template(name) WHERE active;

CREATE TABLE agent_memory (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope text NOT NULL CHECK (scope IN ('global','sut')), sut_id uuid REFERENCES sut(id),
  content text NOT NULL, tags jsonb NOT NULL DEFAULT '[]'::jsonb, enabled boolean NOT NULL DEFAULT true,
  source_correction_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((scope = 'sut') = (sut_id IS NOT NULL)));

CREATE TABLE skill (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL UNIQUE, description text,
  content text, enabled boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE mcp_server (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL UNIQUE,
  transport text NOT NULL DEFAULT 'stdio' CHECK (transport IN ('stdio','http')), command text,
  enabled boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE jobs (
  id bigserial PRIMARY KEY, kind text NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','error','cancelled')),
  run_after timestamptz NOT NULL DEFAULT now(), attempts integer NOT NULL DEFAULT 0, locked_by text,
  created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, ended_at timestamptz, error text);
CREATE INDEX jobs_queue ON jobs(status, run_after);

CREATE TABLE change_log (
  id bigserial PRIMARY KEY, entity text NOT NULL, entity_id text NOT NULL, action text NOT NULL,
  actor text NOT NULL, diff jsonb, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON change_log(entity, entity_id);

-- immutability
CREATE TRIGGER model_snapshot_immutable BEFORE UPDATE OR DELETE ON model_snapshot FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER report_immutable BEFORE UPDATE OR DELETE ON report FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- updated_at maintenance
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['person','sut','environment','module','model_node','api_endpoint','version',
    'requirement','model_suggestion','test_strategy','test_task','test_case','defect','agent_memory']
  LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_updated_at()',
                   t || '_touch', t);
  END LOOP;
END $$;
