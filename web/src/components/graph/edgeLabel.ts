import type { Effect, ModelNode } from "../../api/types";

/** Role names shown when editing an action–entity edge. Stored values stay object / ref / actor. */
export const EDGE_ROLE_ZH = {
  object: "修改（作用对象）",
  ref: "读取（只读引用）",
  actor: "执行人",
} as const;

/** English wording for the same roles and the derived canvas verbs. */
export const EDGE_ROLE_EN = {
  object: "Modifies",
  create: "Creates",
  delete: "Deletes",
  ref: "Reads",
  actor: "Performed by",
} as const;

export const CANVAS_VERB = {
  modify: "修改",
  create: "新建",
  delete: "删除",
  read: "读取",
  actor: "执行人",
} as const;

export type ObjectVerb = typeof CANVAS_VERB.modify | typeof CANVAS_VERB.create | typeof CANVAS_VERB.delete;

function effectHitsEntity(effect: Effect, entity: { id: string; name: string }): boolean {
  if (effect.node_id) return effect.node_id === entity.id;
  return Boolean(effect.entity) && effect.entity === entity.name;
}

/**
 * What an object-role line should say. Only create_object / delete_object that
 * name this entity change the verb. Anything else, including a field update or
 * both create and delete at once, stays 「修改」.
 */
export function objectVerb(action: { effects?: Effect[] } | undefined, entity: { id: string; name: string } | undefined): ObjectVerb {
  if (!action || !entity) return CANVAS_VERB.modify;
  let creates = false;
  let deletes = false;
  for (const effect of action.effects || []) {
    if (!effectHitsEntity(effect, entity)) continue;
    if (effect.kind === "create_object") creates = true;
    else if (effect.kind === "delete_object") deletes = true;
  }
  if (creates && !deletes) return CANVAS_VERB.create;
  if (deletes && !creates) return CANVAS_VERB.delete;
  return CANVAS_VERB.modify;
}

export function actionEdgeLabel(role: string, action?: ModelNode, entity?: ModelNode): string {
  if (role === "object") return objectVerb(action, entity);
  if (role === "ref") return CANVAS_VERB.read;
  if (role === "actor") return CANVAS_VERB.actor;
  if (role === "source") return "起点";
  if (role === "target") return "终点";
  return role;
}
