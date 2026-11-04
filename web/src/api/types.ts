// Response shapes (the backend returns plain rows; request bodies come from schema.d.ts).
import type { components } from "./schema";

export type Schemas = components["schemas"];

export interface Person {
  id: string;
  name: string;
  title?: string | null;
  email?: string | null;
  active: boolean;
}
export interface Sut {
  id: string;
  code: string;
  name: string;
  description?: string | null;
}
export interface Environment {
  id: string;
  sut_id: string;
  name: string;
  base_url: string;
  credential_ref?: string | null;
  /** local command that starts the system under test (e.g. the procurement demo) */
  start_command?: string | null;
}
export interface EnvironmentCheck {
  reachable: boolean;
  started_by_platform: boolean;
  message: string;
}
export type AutomationStatus = "ok" | "needs_fix" | "env_unavailable" | "sut_mismatch";

/** batch 2: what happened (deterministic, from the platform) */
export type FailureKind =
  | "assertion"
  | "locator"
  | "timeout"
  | "script_error"
  | "http_error"
  | "env_unreachable"
  | "platform"
  | "agent_error"
  | "no_script"
  | "non_functional"
  | "unknown";
/** batch 2: whose problem it most likely is (a suggestion, a person confirms) */
export type SuspectedCause = "sut" | "script" | "environment" | "platform" | "unknown";
export type NextActionKey =
  | "create_defect"
  | "analyse"
  | "regenerate"
  | "edit_case"
  | "check_environment"
  | "rerun"
  | "fix_config"
  | "record_failed"
  | "bind_draft";
/** readable failure summary (expected / actual / requirement); raw text stays separate */
export interface FailureSummary {
  headline: string;
  kind: FailureKind;
  cause?: SuspectedCause | null;
  expected?: string;
  actual?: string;
  subject?: string;
  check?: string;
  step?: string;
  requirement_refs?: { code: string; id?: string | null; title?: string | null; rule?: string }[];
  agent_note?: string;
  next_actions?: NextActionKey[];
  /** raw pytest / executor text (self-check failures) */
  raw?: string;
}
export interface Module {
  id: string;
  sut_id: string;
  name: string;
  description?: string | null;
}
export type NodeKind = "entity" | "action" | "relation";
export interface AttrItem {
  text: string;
  expr?: string | null;
}
export interface Attributes {
  conditions?: AttrItem[];
  states?: AttrItem[];
  constraints?: AttrItem[];
}
/** One input or output of an action / API. */
export type IoLocation = "path" | "query" | "header" | "body" | "form" | "response" | "ui";
export interface IoParam {
  name: string;
  display_name?: string | null;
  data_type: DataType;
  required?: boolean;
  location?: IoLocation | null;
  format?: string | null;
  example?: string | null;
  enum_values?: string[];
  description?: string | null;
  /** "Entity.field" this parameter maps to */
  field?: string | null;
  attribute_id?: string | null;
}
export interface ModelNode {
  id: string;
  sut_id: string;
  module_id?: string | null;
  kind: NodeKind;
  name: string;
  /** for actions: what it does (purpose) */
  description?: string | null;
  data_schema?: Record<string, unknown> | null;
  attributes: Attributes;
  code_ref?: string | null;
  inputs?: IoParam[];
  outputs?: IoParam[];
  input_format?: string | null;
  output_format?: string | null;
  /** actions: structured preconditions / effects */
  preconditions?: Precondition[];
  effects?: Effect[];
}
export type PreconditionOp = "eq" | "ne" | "in" | "not_in" | "gt" | "gte" | "lt" | "lte" | "is_null" | "not_null";
export type Scalar = string | number | boolean;
/** PurchaseOrder.state == pending; text alone for conditions that are not about a field */
export interface Precondition {
  field?: string | null;
  attribute_id?: string | null;
  op?: PreconditionOp | null;
  value?: Scalar | Scalar[] | null;
  text?: string | null;
  message?: string | null;
}
export type EffectKind = "set_field" | "create_object" | "delete_object" | "create_link" | "delete_link";
/** PurchaseOrder.state → approved | rejected; create Payment; create link Payment pays PurchaseOrder */
export interface Effect {
  kind: EffectKind;
  field?: string | null;
  attribute_id?: string | null;
  values?: Scalar[];
  node_id?: string | null;
  entity?: string | null;
  link_id?: string | null;
  when?: string | null;
  text?: string | null;
}
export type Cardinality = "one_to_one" | "many_to_one" | "one_to_many" | "many_to_many";
/** Relation between two entities, read in both directions (Palantir link type). */
export interface Link {
  id: string;
  sut_id: string;
  from_node_id: string;
  to_node_id: string;
  from_name: string;
  to_name: string;
  forward_name: string;
  reverse_name: string;
  forward_api_name?: string | null;
  reverse_api_name?: string | null;
  cardinality: Cardinality;
  fk_attribute_id?: string | null;
  fk_field?: string | null;
  via_node_id?: string | null;
  via_name?: string | null;
  via_from_attribute_id?: string | null;
  via_to_attribute_id?: string | null;
  via_from_field?: string | null;
  via_to_field?: string | null;
  required: boolean;
  description?: string | null;
  references?: Reference[];
}
export interface Edge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  role: "source" | "target" | "actor" | "object" | "ref";
  source_name?: string;
  target_name?: string;
}
export interface ApiEndpoint {
  id: string;
  method: string;
  path: string;
  name?: string | null;
  description?: string | null;
  code_ref?: string | null;
  node_names?: string[];
  request_schema?: Record<string, unknown> | null;
  response_schema?: Record<string, unknown> | null;
  operation_id?: string | null;
  schema_source?: "manual" | "openapi" | null;
  request_content_type?: string | null;
  response_content_type?: string | null;
  /** readable tables derived from the stored schema */
  io?: { inputs: IoParam[]; outputs: IoParam[]; input_format?: string | null; output_format?: string | null };
}
export type DataType =
  | "string"
  | "integer"
  | "number"
  | "decimal"
  | "money"
  | "boolean"
  | "date"
  | "datetime"
  | "enum"
  | "reference"
  | "object"
  | "array";
/** Typed field of an entity, e.g. PurchaseOrder.amount_minor. */
export interface EntityField {
  id: string;
  sut_id: string;
  node_id: string;
  node_name?: string;
  name: string;
  display_name?: string | null;
  data_type: DataType;
  unit?: string | null;
  constraints: AttrItem[];
  description?: string | null;
  position: number;
  required?: boolean;
  format?: string | null;
  example?: string | null;
  enum_values?: string[];
  ref_node_id?: string | null;
  ref_node_name?: string | null;
  /** database column when it differs from the API / code name */
  storage_name?: string | null;
}
export interface NodeDetail extends ModelNode {
  fields?: EntityField[];
  edges: Edge[];
  apis: ApiEndpoint[];
  source_node_id?: string | null;
  target_node_id?: string | null;
  /** entities: links where the entity is an end or the junction */
  links?: Link[];
}
export interface Graph {
  nodes: ModelNode[];
  edges: Edge[];
  links?: Link[];
}
export interface Reference {
  type: string;
  id: string;
  label: string;
  role?: string;
}
export interface Version {
  id: string;
  sut_id: string;
  name: string;
  status: "planning" | "requirements_frozen" | "testing" | "closed";
  frozen_at?: string | null;
  model_snapshot_id?: string | null;
  requirement_count?: number;
  sut_code?: string;
  sut_name?: string;
}
export type Part = "actor" | "condition" | "action" | "result" | "constraint";
export interface StructItem {
  text: string;
  node_id?: string | null;
  attribute_id?: string | null;
  link_id?: string | null;
  missing?: boolean;
}
export type Structure = Partial<Record<Part, StructItem[]>>;
export type Role = "owner" | "developer" | "tester";
export interface RequirementPerson {
  person_id: string;
  name: string;
  role: Role;
  active?: boolean;
}
export interface SuggestionPayload {
  node_kind?: string | null;
  node_id?: string | null;
  node_name?: string | null;
  name?: string | null;
  display_name?: string | null;
  data_type?: string | null;
  unit?: string | null;
  attr?: string | null;
  text?: string | null;
  expr?: string | null;
  description?: string | null;
  part?: string | null;
  source_text?: string | null;
  enum_values?: string[];
  /** field suggestion: rename this existing field to `name` (API name is canonical) */
  rename_from?: string | null;
  /** #4: action suggestion naming its API ("METHOD /path") */
  api?: string | null;
  /** #4: an existing node with a similar name (possible duplicate) */
  similar_to?: string | null;
  inputs?: IoParam[];
  outputs?: IoParam[];
  input_format?: string | null;
  output_format?: string | null;
  /** link suggestion */
  from_node_id?: string | null;
  to_node_id?: string | null;
  from_name?: string | null;
  to_name?: string | null;
  forward_name?: string | null;
  reverse_name?: string | null;
  forward_api_name?: string | null;
  reverse_api_name?: string | null;
  cardinality?: Cardinality | null;
  fk_field?: string | null;
  reason?: string | null;
  link_id?: string | null;
  /** rules suggestion */
  preconditions?: Precondition[];
  effects?: Effect[];
}
export interface Suggestion {
  id: string;
  kind: "node" | "attribute" | "field" | "io" | "link" | "rules";
  status: "pending" | "accepted" | "rejected";
  payload: SuggestionPayload;
  requirement_id?: string | null;
  requirement_code?: string | null;
  reason?: string | null;
  agent_run_id?: string | null;
  /** #6: where it comes from; AI inferences are not pre-selected and need a note to accept */
  source?: SuggestionSource;
  evidence?: string | null;
}
export type SuggestionSource = "requirement" | "openapi" | "model_rule" | "ai_inferred";
export interface CompletionOutcome extends AiOutcome {
  suggestions?: Suggestion[];
  skipped?: number;
  dropped?: Partial<Record<"duplicate_node" | "duplicate_api" | "duplicate_in_batch" | "previously_rejected" | "invalid", number>>;
  dropped_notes?: string[];
}
export interface AcceptBatchResult {
  accepted: string[];
  skipped: { id: string; reason: string; message: string }[];
}
export interface Requirement {
  id: string;
  version_id: string;
  code: string;
  title: string;
  raw_text?: string | null;
  priority: "P0" | "P1" | "P2";
  status: "draft" | "structured" | "confirmed";
  structured?: Structure | null;
  agent_run_id?: string | null;
  people: RequirementPerson[];
  nodes?: { part: Part; node_id: string; kind: NodeKind; name: string }[];
  fields?: { id: string; name: string; display_name?: string | null; node_id: string; node_name: string; role?: Part }[];
  links?: { part: Part; link_id: string; forward_name: string; reverse_name: string; cardinality: Cardinality; from_name: string; to_name: string }[];
  suggestions?: Suggestion[];
  cases?: { id: string; code: string; title: string; status: string; scenario?: string | null }[];
  /** per referenced element: which of this requirement's cases cover it */
  coverage?: Record<"actions" | "entities" | "fields" | "relations", CoveredItem[]>;
}
export interface AgentStep {
  seq?: number;
  type: string;
  tool?: string;
  args?: unknown;
  status?: string;
  result?: unknown;
  content?: string;
  tool_calls?: { name: string; args: unknown }[];
  errors?: { loc: string; msg: string }[];
  ms?: number;
}
/** A resolved reference: kind + "name (code)" + the page that shows it */
export interface RefLabel {
  id: string;
  kind: string;
  label: string;
  path: string;
}
export interface AgentRun {
  id: string;
  purpose: string;
  status: string;
  error_code?: string | null;
  error?: string | null;
  steps: AgentStep[];
  result?: unknown;
  /** uuid → readable "name (code)" for everything the run touched */
  labels?: Record<string, string>;
  /** what the run was about: case / requirement / run / version / SUT */
  subjects?: RefLabel[];
  injected?: {
    template?: { name: string; version: number } | null;
    entry_template?: { name: string; version: number } | null;
    memory_ids?: string[];
  };
  cancel_requested: boolean;
  started_at?: string | null;
  ended_at?: string | null;
}
export interface AiOutcome {
  agent_run_id: string;
  status: string;
  error_code?: string | null;
}
export interface AgentConfig {
  base_url?: string | null;
  model?: string | null;
  temperature: number;
  max_tokens?: number | null;
  timeout_s: number;
  max_steps: number;
  max_self_checks?: number;
  auto_automate?: boolean;
  api_key_masked?: string | null;
  configured: boolean;
}
export interface Strategy {
  id: string;
  version_id: string;
  scope?: string | null;
  test_types: string[];
  intensity?: string | null;
  notes?: string | null;
  status: "draft" | "confirmed";
  revision: number;
  source: string;
  agent_run_id?: string | null;
  tasks: { id: string; name: string; kind: TaskKind; executor: string; status: string; case_count: number; selector?: TaskSelector | null }[];
  /** requirements of the version without an executable case */
  gaps?: RequirementGap[];
}
export type CaseCategory = "requirement" | "quality" | "regression";
export type TaskKind = CaseCategory;
/** rule a task uses to pick executable cases; lists are AND-ed, values within a list OR-ed */
export interface TaskSelector {
  requirement_ids?: string[];
  categories?: CaseCategory[];
  type_tags?: string[];
  scenarios?: Scenario[];
  priorities?: ("P0" | "P1" | "P2")[];
  quality_tags?: string[];
}
export interface RequirementGap {
  requirement_id: string;
  code: string;
  title: string;
  ready_count: number;
  draft_count: number;
}
export interface CategorySuggestion {
  category: CaseCategory;
  quality_tags?: string[];
  reason?: string;
}
export interface Task {
  id: string;
  name: string;
  kind: TaskKind;
  selector?: TaskSelector | null;
  executor: string;
  status: string;
  environment_id?: string | null;
  schedule?: { type: "once" | "cron"; at?: string; expr?: string; tz?: string } | null;
  next_run_at?: string | null;
  case_count?: number;
  source?: string;
  /** automated tasks: ready cases without a script (#18) */
  script_gap_count?: number;
}
export interface ScriptGap {
  id: string;
  code: string;
  title: string;
  automation_status?: AutomationStatus | null;
}
export interface RunnableTask {
  id: string;
  name: string;
  kind: string;
  executor: string;
  status: string;
  environment_id?: string | null;
  environment_name?: string | null;
  ready_cases: number;
  case_count: number;
  active_run_id?: string | null;
  script_gaps: string[];
  script_gap_ids: string[];
  runnable: boolean;
  reason: "running" | "no_cases" | "not_ready" | "no_environment" | "no_ready_cases" | null;
}
export interface RunVersionResult {
  started: { task_id: string; name: string; run_id: string }[];
  skipped: { task_id: string; name: string | null; code: string; message: string; related?: string[] }[];
  version_testing: boolean;
}

export type Scenario = "normal" | "boundary" | "exception";
export interface CaseStep {
  action: string;
  data?: string | null;
  expected?: string | null;
}
export interface CaseRow {
  id: string;
  code: string;
  title: string;
  test_point?: string | null;
  priority: "P0" | "P1" | "P2";
  type_tag: string;
  scenario?: Scenario | null;
  /** requirement / quality / regression */
  category?: CaseCategory;
  quality_tags?: string[];
  /** uncertain classification waiting for a person */
  category_suggestion?: CategorySuggestion | null;
  mode: "manual" | "automated";
  status: "draft" | "ready" | "deprecated";
  source: "human" | "agent";
  revision: number;
  requirement_codes: string[];
  node_count: number;
  automation_status?: AutomationStatus | null;
  automation_note?: string | null;
  /** what this case covers, by name */
  coverage?: CaseCoverage;
}
export interface NamedRef {
  id: string;
  name: string;
  node_id?: string;
}
export interface CaseCoverage {
  actions: NamedRef[];
  entities: NamedRef[];
  fields: NamedRef[];
  relations: NamedRef[];
}
export interface CaseBrief {
  id: string;
  code: string;
  title: string;
}
export interface CoveredItem {
  id: string;
  name: string;
  node_id?: string;
  cases: CaseBrief[];
}
export interface AiProposal {
  agent_run_id: string;
  created_at: string;
  base_revision: number;
  rationale: string;
  fields: {
    test_point?: string | null;
    preconditions?: string | null;
    steps?: CaseStep[];
    test_data?: Record<string, unknown> | null;
    expected?: string | null;
    requirement_ids?: string[];
    node_ids?: string[];
    attribute_ids?: string[];
    category?: CaseCategory;
    quality_tags?: string[];
  };
  labels: Record<string, string>;
}
export interface BatchResult {
  action: string;
  ok: { id: string; code: string }[];
  skipped: { id: string; code: string; reason: string }[];
  failed: { id: string; code: string | null; error: string }[];
  queued: number;
}
export interface TestCase extends Omit<CaseRow, "requirement_codes" | "node_count" | "coverage"> {
  relations?: NamedRef[];
  /** AI completion proposal waiting for a human decision */
  ai_proposal?: AiProposal | null;
  sut_id: string;
  origin_version_id?: string | null;
  snapshot_id?: string | null;
  preconditions?: string | null;
  steps: CaseStep[];
  test_data?: Record<string, unknown> | null;
  expected?: string | null;
  code_path?: string | null;
  code_commit?: string | null;
  automation_status?: AutomationStatus | null;
  automation_note?: string | null;
  automation_draft_path?: string | null;
  automation_draft_commit?: string | null;
  automation_failure?: FailureSummary | null;
  repo_path?: string | null;
  code_abs_path?: string | null;
  draft_abs_path?: string | null;
  agent_run_id?: string | null;
  requirements: { id: string; code: string; title: string; version_id: string }[];
  fields?: { id: string; name: string; display_name?: string | null; node_id: string; node_name: string }[];
  nodes: { id: string; kind: NodeKind; name: string; deleted: boolean }[];
  tasks: { id: string; name: string; version_id: string; seq: number }[];
  updated_at: string;
}
export interface CaseRevision {
  revision: number;
  content: Record<string, unknown>;
  author: string;
  created_at: string;
}
export interface CoverageBlock {
  total: number;
  covered: number;
  uncovered: { id: string; code?: string; name?: string; title?: string }[];
  items: { id: string; code?: string; name?: string; title?: string; node_id?: string; cases: number; case_list?: CaseBrief[] }[];
}
export interface Coverage {
  version_id: string;
  sut_id?: string;
  snapshot_id?: string | null;
  cases: number;
  requirements: CoverageBlock;
  actions: CoverageBlock;
  fields?: CoverageBlock;
  relations?: CoverageBlock;
  by_priority: Record<string, number>;
  by_type: Record<string, number>;
  by_scenario: Record<string, number>;
}
export interface Correction {
  id: string;
  target_type: string;
  target_id: string;
  target_label?: string | null;
  content: string;
  author: string;
  kind: "correction" | "omission";
  status: "pending" | "processing" | "processed" | "failed";
  sut_id?: string | null;
  sut_code?: string | null;
  attempts: number;
  error?: string | null;
  agent_run_id?: string | null;
  outputs: { memory_ids?: string[]; prompt_versions?: { name: string; version: number; id: string }[] };
  created_at: string;
  processed_at?: string | null;
}
export interface PromptSummary {
  name: string;
  kind: "system" | "entry";
  versions: number;
  active_version: number | null;
  updated_at: string | null;
  content: string;
  is_default: boolean;
}
export interface PromptVersion {
  id: string;
  name: string;
  version: number;
  content: string;
  active: boolean;
  source_correction_ids: string[];
  created_by: string;
  note: string | null;
  agent_run_id: string | null;
  created_at: string;
}
export interface AgentMemory {
  id: string;
  scope: "global" | "sut";
  sut_id: string | null;
  sut_code: string | null;
  content: string;
  tags: string[];
  enabled: boolean;
  source_correction_ids: string[];
  created_by: string;
  agent_run_id: string | null;
  created_at: string;
}
export interface SkillItem {
  id: string;
  name: string;
  description: string | null;
  content: string | null;
  source: string | null;
  enabled: boolean;
  created_at: string;
}
export interface McpServer {
  id: string;
  name: string;
  transport: "stdio" | "http";
  command: string | null;
  url: string | null;
  description: string | null;
  enabled: boolean;
  created_at: string;
}

export type ExecutionStatus = "queued" | "running" | "passed" | "failed" | "error" | "blocked" | "skipped";
export type Executor = "agent_browser" | "agent_api" | "pytest" | "manual";
export interface ExecutionArtifact {
  kind: string;
  name: string;
  sha256: string;
}
export interface ExecutionStep {
  seq: number;
  action: string;
  target?: Record<string, string> | string | null;
  value?: unknown;
  result?: unknown;
  status: string;
  screenshot_sha?: string | null;
  ms?: number | null;
}
export interface ExecutionRow {
  id: string;
  task_run_id?: string | null;
  executor: Executor;
  status: ExecutionStatus;
  failed_assertion?: string | null;
  error?: string | null;
  duration_ms?: number | null;
  executed_by?: string | null;
  created_at: string;
  ended_at?: string | null;
  environment_name?: string | null;
  failure_kind?: FailureKind | null;
  suspected_cause?: SuspectedCause | null;
  summary?: FailureSummary | null;
}
export interface CaseExecution extends ExecutionRow {
  defects?: { id: string; code: string; title: string; status: string; severity: string }[];
  case_id: string;
  case_code: string;
  case_title: string;
  sut_id: string;
  environment_id?: string | null;
  base_url?: string | null;
  agent_run_id?: string | null;
  code_commit?: string | null;
  blocked_reason?: string | null;
  result?: string | null;
  test_data?: Record<string, unknown> | null;
  steps_recorded: ExecutionStep[];
  artifacts: ExecutionArtifact[];
  started_at?: string | null;
  report?: RunReport | null;
}
/** readable pytest report written by the platform's pytest plugin */
export interface ReportEvent {
  type: "request" | "action" | "check" | "error";
  seq: number;
  line?: number | null;
  // request
  method?: string;
  url?: string;
  status?: number;
  ms?: number;
  request?: string | null;
  response?: string | null;
  params?: string | null;
  // action
  action?: string;
  target?: string | null;
  value?: string | null;
  ok?: boolean;
  error?: string | null;
  // check
  name?: string;
  op?: string;
  subject?: string;
  expected?: string | null;
  actual?: string | null;
  passed?: boolean;
  explain?: string | null;
  assert?: boolean;
  // error
  message?: string | null;
}
export interface ReportStep {
  name: string;
  status: "passed" | "failed";
  ms?: number | null;
  source?: "step" | "comment" | "single" | "implicit";
  checks?: number;
  events: ReportEvent[];
}
export interface ReportTest {
  name: string;
  title?: string | null;
  outcome: "passed" | "failed" | "error";
  duration_ms: number;
  steps: ReportStep[];
  checks: { total: number; failed: number };
  requests: number;
  data_keys: string[];
  data_used?: Record<string, unknown>;
  data_missing?: string[];
  failure?: { type: string; message?: string | null; explain?: string | null } | null;
  dropped_events?: number;
}
export interface RunReport {
  version: number;
  tests: ReportTest[];
}
export interface AutomateResult {
  agent_run_id: string;
  status: string;
  error_code?: string | null;
  self_checks: number;
  code_path?: string | null;
  code_commit?: string | null;
  reason?: string | null;
  draft_path?: string | null;
}
export interface CaseCode {
  path: string;
  abs_path: string;
  repo_path: string;
  commit?: string | null;
  content: string;
}
export interface AutomationJob {
  id: number;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  error?: string | null;
  case_id?: string | null;
  code?: string | null;
  title?: string | null;
  mode?: string | null;
  automation_status?: AutomationStatus | null;
  automation_note?: string | null;
  created_at: string;
  ended_at?: string | null;
}
export interface AutomationProgress {
  jobs: AutomationJob[];
  counts: Record<string, number>;
}

export type RunStatus = "queued" | "running" | "passed" | "failed" | "error" | "cancelled";
export interface RunCounts {
  total: number;
  done: number;
  passed: number;
  failed: number;
  error: number;
  blocked: number;
  skipped: number;
}
export interface TaskRunRow {
  id: string;
  task_id: string;
  task_name?: string;
  version_id?: string;
  version_name?: string;
  sut_code?: string;
  trigger: "manual" | "schedule";
  status: RunStatus;
  cancel_requested: boolean;
  error?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  created_at: string;
  counts: RunCounts;
}
export interface RunExecution extends ExecutionRow {
  case_id: string;
  case_code: string;
  case_title: string;
  blocked_reason?: string | null;
}
export interface TaskRun extends TaskRunRow {
  task_name: string;
  version_id: string;
  sut_id: string;
  executor: string;
  environment_id?: string | null;
  executions: RunExecution[];
  not_ready: { id: string; code: string; title: string; status: string }[];
  /** cases of an automated task that were skipped because they have no script (#18) */
  no_script?: { case_id: string; code: string; title: string }[];
  report_id?: string | null;
}
export interface TaskDetail extends Task {
  version_id: string;
  version_name?: string | null;
  sut_id: string;
  description?: string | null;
  cases: TaskCaseRow[];
  exclusions?: { case_id: string; code: string; title: string; removed_by: string; created_at: string }[];
  rule_stats?: { rule: number; manual: number; excluded: number };
  script_gaps?: ScriptGap[];
}
export interface TaskCaseRow {
  seq: number;
  id: string;
  code: string;
  title: string;
  status: string;
  mode: string;
  type_tag: string;
  priority?: string;
  category?: CaseCategory;
  /** rule = matched by the rule / added automatically; manual = added by hand */
  source?: "rule" | "manual";
  reason?: string | null;
  added_at?: string;
}

export type Severity = "critical" | "major" | "minor" | "trivial";
export type Cause = "requirement" | "design" | "development" | "test" | "environment" | "unknown";
export type DefectStatus = "open" | "in_progress" | "resolved" | "closed" | "rejected";
export interface DefectRow {
  id: string;
  code: string;
  sut_id: string;
  version_id?: string | null;
  title: string;
  severity: Severity;
  status: DefectStatus;
  cause_category: Cause;
  suggested_cause?: Cause | null;
  created_by: "human" | "agent";
  case_id?: string | null;
  execution_id?: string | null;
  created_at: string;
  requirement_codes: string[];
  responsible_names: string[];
}
export interface Defect extends Omit<DefectRow, "requirement_codes" | "responsible_names"> {
  description?: string | null;
  analysis?: string | null;
  agent_run_id?: string | null;
  resolved_at?: string | null;
  responsible_manual: boolean;
  requirements: { id: string; code: string; title: string; version_id: string; inferred: boolean }[];
  responsible: { person_id: string; person_name: string; role: Role; inferred: boolean }[];
  links: { target_type: "node" | "api"; target_id: string; name: string; code_ref?: string | null }[];
  case?: { id: string; code: string; title: string } | null;
  execution?: { id: string; status: string; executor: string; failed_assertion?: string | null; task_run_id?: string | null } | null;
}
export interface AnalyzeResult {
  agent_run_id: string;
  status: string;
  error_code?: string | null;
  suggested_cause?: Cause | null;
  analysis?: string | null;
  defect?: { id: string; code: string } | null;
}

// ---- M1-11 stats & reports ----
export type SeverityWeights = Record<string, number>;
export interface RequirementStat {
  requirement_id: string;
  version_id: string;
  code: string;
  title: string;
  owner: string[];
  developers: string[];
  testers: string[];
  defect_count: number;
  weighted_score: number;
  executed_cases: number;
  density: number | null;
  by_severity: Record<string, number>;
}
export interface RoleStat {
  count: number;
  score: number;
}
export interface PersonStat {
  person_id: string;
  name: string;
  active: boolean;
  attributed_count: number;
  attributed_score: number;
  attributed_by_role: Record<string, RoleStat>;
  related_count: number;
  requirements: { code: string; title: string; count: number }[];
}
export interface ReportSummary {
  total: number;
  passed: number;
  failed: number;
  error: number;
  blocked: number;
  skipped: number;
  not_executed: number;
  /** passed + failed + error */
  executed?: number;
  pass_rate: number | null;
  /** batch 2: skipped split into "no script" and non-functional */
  skipped_no_script?: number;
  skipped_non_functional?: number;
  by_cause?: Record<SuspectedCause, number>;
  by_kind?: Partial<Record<FailureKind, number>>;
}
export interface ReportRow {
  id: string;
  scope_type: "task_run" | "version";
  scope_id: string;
  created_at: string;
  created_by: string;
  summary: ReportSummary;
  has_ai_summary: boolean;
  version_id: string | null;
  version_name: string | null;
  task_name: string | null;
}
export interface ReportContent {
  scope: {
    type: "task_run" | "version";
    task_run_id?: string;
    task_name?: string;
    version_id: string;
    version_name: string;
    status?: string;
    version_status?: string;
  };
  summary: ReportSummary;
  /** pass rate per case category */
  by_category?: (ReportSummary & { category: CaseCategory; label: string })[];
  failures: {
    case: { id: string; code: string; title: string };
    requirement_codes: string[];
    status: string;
    failed_assertion: string | null;
    error: string | null;
    failure_kind?: FailureKind | null;
    suspected_cause?: SuspectedCause | null;
    headline?: string | null;
    execution_id: string;
    defect_ids: string[];
  }[];
  /** cases skipped because they have no automation script (#18) */
  no_script?: { case: { id: string; code: string; title: string }; execution_id: string }[];
  by_requirement: RequirementStat[];
  by_person: (Omit<PersonStat, "active" | "requirements"> & { top_requirements: string[] })[];
  defects: {
    id: string;
    code: string;
    title: string;
    severity: string;
    cause_category: string;
    status: string;
    requirements: string[];
    responsible: { name: string; role: string }[];
  }[];
  code_links: {
    requirement_code: string;
    nodes: { name: string; code_ref: string | null }[];
    apis: { method: string; path: string; code_ref: string | null }[];
  }[];
  weights_used: SeverityWeights;
  snapshot_id: string | null;
  generated_at: string;
}
export interface Report {
  id: string;
  scope_type: "task_run" | "version";
  scope_id: string;
  content: ReportContent;
  ai_summary: string | null;
  agent_run_id: string | null;
  created_by: string;
  created_at: string;
}

/* ---------------------------------------------------------------- navigation & review */
export type NavKind = "sut" | "version" | "requirement" | "task" | "run" | "case" | "execution" | "defect" | "report";
export interface NavCrumb {
  kind: string;
  id?: string | null;
  label: string;
  path: string;
}
export interface NavContext {
  sut?: { id: string; code: string; name: string } | null;
  version?: { id: string; name: string; status: string } | null;
  crumbs: NavCrumb[];
}
export type StepStatus = "done" | "doing" | "todo";
export interface FlowStep {
  key: "sut" | "model" | "requirements" | "strategy" | "tasks" | "cases" | "runs" | "results";
  title: string;
  status: StepStatus;
  summary: string;
  path: string;
  action?: { label: string; path: string; kind?: "run_tasks"; version_id?: string } | null;
}
export interface SutProgress {
  sut: { id: string; code: string; name: string };
  version?: { id: string; name: string; status: string } | null;
  versions: { id: string; name: string; status: string }[];
  steps: FlowStep[];
  next?: { key: string; title: string; label: string; path: string; kind?: "run_tasks"; version_id?: string } | null;
  repo_path?: string | null;
}
export interface ReviewRef {
  id: string;
  code: string;
  title: string;
  version_id?: string;
  version_name?: string;
  status?: string;
}
export interface ReviewCoverage {
  requirements: ReviewRef[];
  cases: ReviewRef[];
}
export interface ReviewMark {
  reviewed: boolean;
  stale: boolean;
  note?: string | null;
  reviewed_by?: string;
  reviewed_at?: string;
}
interface ReviewElement {
  id: string;
  coverage: ReviewCoverage;
  uncovered: boolean;
  digest: string;
  mark?: ReviewMark | null;
}
export interface ReviewField {
  id: string;
  name: string;
  display_name?: string | null;
  data_type: string;
  required: boolean;
  enum_values?: string[];
  unit?: string | null;
  format?: string | null;
  storage_name?: string | null;
  description?: string | null;
  ref_node_name?: string | null;
  coverage: ReviewCoverage;
  uncovered: boolean;
}
export interface ReviewEntity extends ReviewElement {
  name: string;
  description?: string | null;
  fields: ReviewField[];
  relations: string[];
}
export interface ReviewLink extends ReviewElement {
  forward: string;
  reverse: string;
  text: string;
  cardinality: string;
  fk_field?: string | null;
  via_name?: string | null;
  required: boolean;
  api_names: string[];
  description?: string | null;
}
export interface ReviewAction extends ReviewElement {
  name: string;
  description?: string | null;
  inputs: string[];
  outputs: string[];
  input_format?: string | null;
  output_format?: string | null;
  preconditions: string[];
  effects: string[];
  apis: { id: string; method: string; path: string; name?: string | null }[];
}
export interface ModelReview {
  sut: { id: string; code: string; name: string; description?: string | null };
  generated_at: string;
  summary: {
    entities: number;
    fields: number;
    links: number;
    actions: number;
    total: number;
    reviewed: number;
    stale: number;
    uncovered: number;
    pending_suggestions: number;
  };
  pending_by_kind: Record<string, number>;
  /** #6: pending suggestions by source (requirement / openapi / model_rule / ai_inferred) */
  pending_by_source?: Partial<Record<SuggestionSource, number>>;
  entities: ReviewEntity[];
  links: ReviewLink[];
  actions: ReviewAction[];
}
