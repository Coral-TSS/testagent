import type { Cardinality, Effect, Link, Precondition, PreconditionOp } from "../api/types";

/** Relation (link type) helpers shared by the graph, the editors and the suggestion list. */
export const CARD_SHORT: Record<Cardinality, string> = {
  one_to_one: "1:1",
  many_to_one: "N:1",
  one_to_many: "1:N",
  many_to_many: "M:N",
};
export const CARD_LABEL: Record<Cardinality, string> = {
  one_to_one: "一对一（1:1）",
  many_to_one: "多对一（N:1，外键在源上）",
  one_to_many: "一对多（1:N，外键在目标上）",
  many_to_many: "多对多（M:N，中间实体可选）",
};

type Sides = Pick<Link, "from_name" | "to_name" | "forward_name" | "reverse_name">;
export const forwardText = (l: Sides) => `${l.from_name} ${l.forward_name} ${l.to_name}`;
export const reverseText = (l: Sides) => `${l.to_name} ${l.reverse_name} ${l.from_name}`;

/** "PurchaseOrder belongs to Supplier (N:1, foreign key PurchaseOrder.supplier_id)" */
export function linkText(l: Link): string {
  const extra = [CARD_SHORT[l.cardinality]];
  if (l.fk_field) extra.push(`外键 ${l.fk_field}`);
  if (l.via_name) extra.push(`中间实体 ${l.via_name}`);
  return `${forwardText(l)} (${extra.join(", ")})`;
}

export const OP_TEXT: Record<PreconditionOp, string> = {
  eq: "==",
  ne: "!=",
  in: "∈",
  not_in: "∉",
  gt: ">",
  gte: ">=",
  lt: "<",
  lte: "<=",
  is_null: "为空",
  not_null: "不为空",
};
export const EFFECT_LABEL: Record<Effect["kind"], string> = {
  set_field: "设置字段",
  create_object: "创建对象",
  delete_object: "删除对象",
  create_link: "创建关系",
  delete_link: "移除关系",
};

export function preconditionText(p: Precondition): string {
  if (!p.field) return p.text || "";
  const op = p.op || "eq";
  if (op === "is_null" || op === "not_null") return `${p.field} ${OP_TEXT[op]}`;
  const shown = Array.isArray(p.value) ? p.value.join(" | ") : String(p.value ?? "");
  return `${p.field} ${OP_TEXT[op]} ${shown}`;
}

export function effectText(e: Effect, linkNames?: Map<string, string>): string {
  let text: string;
  if (e.kind === "set_field") text = `${e.field} → ${(e.values || []).join(" | ") || "?"}`;
  else if (e.kind === "create_object" || e.kind === "delete_object") text = `${EFFECT_LABEL[e.kind]} ${e.entity || ""}`;
  else text = `${EFFECT_LABEL[e.kind]} ${(e.link_id && linkNames?.get(e.link_id)) || ""}`;
  return e.when ? `${text} (${e.when})` : text;
}
