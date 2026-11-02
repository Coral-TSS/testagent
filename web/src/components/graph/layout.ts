import type { Graph } from "../../api/types";

export interface Positioned {
  id: string;
  x: number;
  y: number;
}

const ENTITY_GAP_X = 320;
const ENTITY_GAP_Y = 220;
const ACTION_GAP_X = 220;

/**
 * Deterministic layout: entities on a grid (linked entities placed next to each other),
 * actions on a row below. Relations are edges between entities, not nodes.
 * Pure function so graph and list stay consistent and testable.
 */
export function computeLayout(graph: Graph): Map<string, Positioned> {
  const pos = new Map<string, Positioned>();
  const entities = graph.nodes.filter((n) => n.kind === "entity");
  const actions = graph.nodes.filter((n) => n.kind === "action");

  // Breadth-first over links so that related entities end up adjacent on the grid.
  const neighbours = new Map<string, string[]>();
  for (const l of graph.links || []) {
    neighbours.set(l.from_node_id, [...(neighbours.get(l.from_node_id) || []), l.to_node_id]);
    neighbours.set(l.to_node_id, [...(neighbours.get(l.to_node_id) || []), l.from_node_id]);
  }
  const ids = new Set(entities.map((e) => e.id));
  const order: string[] = [];
  for (const start of entities) {
    if (order.includes(start.id)) continue;
    const queue = [start.id];
    while (queue.length) {
      const id = queue.shift()!;
      if (order.includes(id) || !ids.has(id)) continue;
      order.push(id);
      queue.push(...(neighbours.get(id) || []));
    }
  }

  const cols = Math.max(1, Math.ceil(Math.sqrt(order.length)));
  order.forEach((id, i) => {
    pos.set(id, { id, x: (i % cols) * ENTITY_GAP_X, y: Math.floor(i / cols) * ENTITY_GAP_Y });
  });
  const entityRows = Math.ceil(order.length / cols);

  // Anything else (e.g. a legacy node kind) goes on a row above.
  graph.nodes
    .filter((n) => n.kind !== "entity" && n.kind !== "action")
    .forEach((n, i) => pos.set(n.id, { id: n.id, x: i * ACTION_GAP_X, y: -ENTITY_GAP_Y }));

  const actionY = entityRows * ENTITY_GAP_Y + 80;
  actions.forEach((n, i) => pos.set(n.id, { id: n.id, x: i * ACTION_GAP_X, y: actionY }));
  return pos;
}
