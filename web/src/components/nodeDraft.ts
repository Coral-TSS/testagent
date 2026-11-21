import type { ApiEndpoint, Attributes, Cardinality, DataType, Edge, Effect, EntityField, IoParam, Link, NodeDetail, Precondition } from "../api/types";
import { preconditionRows } from "./ActionRules";

export interface FieldDraft {
  key: string;
  id?: string;
  name: string;
  display_name: string;
  data_type: DataType;
  required: boolean;
  unit: string;
  position: string;
  format: string;
  example: string;
  storage_name: string;
  constraints_text: string;
  description: string;
  enum_values: string[];
  ref_node_id?: string;
}

export interface LinkDraft {
  key: string;
  id?: string;
  from_node_id: string;
  to_node_id: string;
  forward_name: string;
  reverse_name: string;
  forward_api_name: string;
  reverse_api_name: string;
  cardinality: Cardinality;
  required: boolean;
  fk_attribute_id?: string;
  description: string;
}

export interface EdgeDraft {
  key: string;
  id?: string;
  role: "actor" | "object" | "ref";
  target_id: string;
  /** existing edges keep their original ends so a role change can be recreated */
  source_id?: string;
  original_target?: string;
  original_role?: string;
}

export interface NodeDraft {
  name: string;
  description: string;
  module_id: string | null;
  code_ref: string;
  api_ids: string[];
  input_format: string;
  output_format: string;
  inputs: IoParam[];
  outputs: IoParam[];
  preconditions: ReturnType<typeof preconditionRows>;
  effects: Effect[];
  attributes: Attributes;
  fields: FieldDraft[];
  links: LinkDraft[];
  edges: EdgeDraft[];
}

const emptyAttributes = (): Attributes => ({ conditions: [], states: [], constraints: [] });

export function blankField(): FieldDraft {
  return {
    key: crypto.randomUUID(),
    name: "",
    display_name: "",
    data_type: "string",
    required: false,
    unit: "",
    position: "",
    format: "",
    example: "",
    storage_name: "",
    constraints_text: "",
    description: "",
    enum_values: [],
  };
}

export function blankLink(from = "", to = ""): LinkDraft {
  return {
    key: crypto.randomUUID(),
    from_node_id: from,
    to_node_id: to,
    forward_name: "",
    reverse_name: "",
    forward_api_name: "",
    reverse_api_name: "",
    cardinality: "many_to_one",
    required: false,
    description: "",
  };
}

export function blankEdge(target = "", role: EdgeDraft["role"] = "object"): EdgeDraft {
  return { key: crypto.randomUUID(), role, target_id: target };
}

function fieldFrom(f: EntityField): FieldDraft {
  return {
    key: f.id,
    id: f.id,
    name: f.name,
    display_name: f.display_name || "",
    data_type: f.data_type,
    required: Boolean(f.required),
    unit: f.unit || "",
    position: f.position === undefined || f.position === null ? "" : String(f.position),
    format: f.format || "",
    example: f.example || "",
    storage_name: f.storage_name || "",
    constraints_text: (f.constraints || []).map((c) => c.text).join("\n"),
    description: f.description || "",
    enum_values: f.enum_values || [],
    ref_node_id: f.ref_node_id || undefined,
  };
}

function linkFrom(l: Link): LinkDraft {
  return {
    key: l.id,
    id: l.id,
    from_node_id: l.from_node_id,
    to_node_id: l.to_node_id,
    forward_name: l.forward_name,
    reverse_name: l.reverse_name,
    forward_api_name: l.forward_api_name || "",
    reverse_api_name: l.reverse_api_name || "",
    cardinality: l.cardinality,
    required: Boolean(l.required),
    fk_attribute_id: l.fk_attribute_id || undefined,
    description: l.description || "",
  };
}

export function toDraft(node: NodeDetail, fields: EntityField[]): NodeDraft {
  const ownLinks = (node.links || []).filter((l) => l.from_node_id === node.id || l.to_node_id === node.id);
  return {
    name: node.name,
    description: node.description || "",
    module_id: node.module_id || null,
    code_ref: node.code_ref || "",
    api_ids: (node.apis || []).map((a) => a.id),
    input_format: node.input_format || "",
    output_format: node.output_format || "",
    inputs: node.inputs || [],
    outputs: node.outputs || [],
    preconditions: preconditionRows(node.preconditions),
    effects: node.effects || [],
    attributes: node.attributes || emptyAttributes(),
    fields: fields.map(fieldFrom),
    links: ownLinks.map(linkFrom),
    edges: (node.edges || [])
      .filter((e) => e.role === "actor" || e.role === "object" || e.role === "ref")
      .map((e) => edgeFrom(e, node.id)),
  };
}

function edgeFrom(e: Edge, nodeId: string): EdgeDraft {
  const outgoing = e.source_node_id === nodeId;
  return {
    key: e.id,
    id: e.id,
    role: e.role as EdgeDraft["role"],
    target_id: outgoing ? e.target_node_id : e.source_node_id,
    source_id: e.source_node_id,
    original_target: outgoing ? e.target_node_id : e.source_node_id,
    original_role: e.role,
  };
}

export function fieldBody(row: FieldDraft): Record<string, unknown> | null {
  if (!row.name.trim()) return null;
  const position = row.position.trim() === "" ? undefined : Number(row.position);
  return {
    name: row.name.trim(),
    display_name: row.display_name.trim() || null,
    data_type: row.data_type,
    unit: row.unit.trim() || null,
    description: row.description.trim() || null,
    constraints: row.constraints_text
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean)
      .map((text) => ({ text })),
    ...(position !== undefined && Number.isFinite(position) ? { position } : {}),
    required: Boolean(row.required),
    format: row.format.trim() || null,
    example: row.example.trim() || null,
    enum_values: row.data_type === "enum" ? row.enum_values : [],
    ref_node_id: row.data_type === "reference" ? row.ref_node_id || null : null,
    storage_name: row.storage_name.trim() || null,
  };
}

export function linkBody(row: LinkDraft): Record<string, unknown> | null {
  if (!row.forward_name.trim() && !row.reverse_name.trim() && !row.id) return null;
  return {
    from_node_id: row.from_node_id,
    to_node_id: row.to_node_id,
    forward_name: row.forward_name.trim(),
    reverse_name: row.reverse_name.trim(),
    forward_api_name: row.forward_api_name.trim() || null,
    reverse_api_name: row.reverse_api_name.trim() || null,
    cardinality: row.cardinality,
    required: Boolean(row.required),
    fk_attribute_id: row.cardinality === "many_to_many" ? null : row.fk_attribute_id || null,
    description: row.description.trim() || null,
  };
}

function mergeParams(base: IoParam[], extra: IoParam[], replace: boolean): IoParam[] {
  if (replace) return extra.map((p) => ({ ...p }));
  const names = new Set(base.map((p) => p.name));
  return [...base, ...extra.filter((p) => p.name && !names.has(p.name)).map((p) => ({ ...p }))];
}

/** Copy bound API fields into the draft. Nothing is written until the panel is saved. */
export function fillFromApis(draft: NodeDraft, apis: ApiEndpoint[], replace: boolean): { draft: NodeDraft; addedIn: number; addedOut: number } {
  const bound = apis.filter((a) => draft.api_ids.includes(a.id));
  const beforeIn = replace ? 0 : draft.inputs.length;
  const beforeOut = replace ? 0 : draft.outputs.length;
  const inputs = mergeParams(draft.inputs, bound.flatMap((a) => a.io?.inputs || []), replace);
  const outputs = mergeParams(draft.outputs, bound.flatMap((a) => a.io?.outputs || []), replace);
  const many = bound.length > 1;
  const join = (values: (string | null | undefined)[], prefix: (api: ApiEndpoint) => string) =>
    bound
      .map((api, i) => {
        const value = values[i];
        return value ? (many ? `${prefix(api)}: ${value}` : value) : "";
      })
      .filter(Boolean)
      .join("; ")
      .slice(0, 500);
  const inputFormat = join(bound.map((a) => a.io?.input_format), (a) => `${a.method} ${a.path}`);
  const outputFormat = join(bound.map((a) => a.io?.output_format), (a) => `${a.method} ${a.path}`);
  const purpose = bound.map((a) => a.description || a.name).filter((x): x is string => Boolean(x));
  return {
    addedIn: Math.max(0, inputs.length - beforeIn),
    addedOut: Math.max(0, outputs.length - beforeOut),
    draft: {
      ...draft,
      inputs,
      outputs,
      input_format: replace || !draft.input_format.trim() ? inputFormat || draft.input_format : draft.input_format,
      output_format: replace || !draft.output_format.trim() ? outputFormat || draft.output_format : draft.output_format,
      description: !draft.description.trim() && purpose.length ? [...new Set(purpose)].join("; ") : draft.description,
    },
  };
}

export function sameIds(a: string[], b: string[]): boolean {
  return a.length === b.length && [...a].sort().join() === [...b].sort().join();
}

export type PreconditionDraft = Precondition & { value_list?: string[] };
