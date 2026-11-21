import type { Edge, Graph, ModelNode } from "../../api/types";

export interface Positioned {
  id: string;
  x: number;
  y: number;
}

/** Box used for overlap. Wide enough for names such as PurchaseRequisition. */
const BOX_W = 200;
const BOX_H = 72;
const GAP_X = 56;
const GAP_Y = 40;
const MIN_X = BOX_W + GAP_X;
const MIN_Y = BOX_H + GAP_Y;
/** Preferred distance between two directly related entities. */
const ENTITY_IDEAL = 560;
const MARGIN = 48;

type Vec = { x: number; y: number };

/** Roles the canvas actually draws. source/target belong to legacy link-nodes and are hidden. */
const DRAWN_ROLES = new Set(["actor", "object", "ref"]);

function byName(a: ModelNode, b: ModelNode): number {
  if (a.name !== b.name) return a.name < b.name ? -1 : 1;
  if (a.id !== b.id) return a.id < b.id ? -1 : 1;
  return 0;
}

function hypot(dx: number, dy: number): number {
  return Math.hypot(dx, dy) || 0.001;
}

function shortestPaths(ids: string[], links: Array<[string, string]>): Map<string, Map<string, number>> {
  const adj = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const [a, b] of links) {
    if (!adj.has(a) || !adj.has(b) || a === b) continue;
    adj.get(a)!.push(b);
    adj.get(b)!.push(a);
  }
  const dist = new Map<string, Map<string, number>>();
  for (const src of ids) {
    const d = new Map<string, number>([[src, 0]]);
    const queue = [src];
    while (queue.length) {
      const cur = queue.shift()!;
      const base = d.get(cur)!;
      for (const next of adj.get(cur) || []) {
        if (d.has(next)) continue;
        d.set(next, base + 1);
        queue.push(next);
      }
    }
    dist.set(src, d);
  }
  return dist;
}

/**
 * Kamada-Kawai style placement: Euclidean distance tracks how many relationships
 * separate two entities, so a neighborhood stays a neighborhood.
 */
function layoutEntities(entities: ModelNode[], links: Array<[string, string]>): Map<string, Vec> {
  const nodes = [...entities].sort(byName);
  const pos = new Map<string, Vec>();
  const n = nodes.length;
  if (n === 0) return pos;
  const radius = Math.max(ENTITY_IDEAL, (n * ENTITY_IDEAL) / (2 * Math.PI));
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    pos.set(node.id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
  });
  if (n === 1) return pos;

  const ids = nodes.map((node) => node.id);
  const hops = shortestPaths(ids, links);
  const far = n;
  const iterations = 360;
  for (let iter = 0; iter < iterations; iter++) {
    const rate = 0.12 * (1 - iter / iterations) + 0.015;
    const next = new Map<string, Vec>();
    for (const id of ids) {
      const pi = pos.get(id)!;
      let gx = 0;
      let gy = 0;
      for (const other of ids) {
        if (other === id) continue;
        const pj = pos.get(other)!;
        const dx = pi.x - pj.x;
        const dy = pi.y - pj.y;
        const cur = hypot(dx, dy);
        const steps = hops.get(id)!.get(other) ?? far;
        const target = steps * ENTITY_IDEAL;
        const weight = 1 / (steps * steps);
        const mag = weight * (1 - target / cur);
        gx += mag * dx;
        gy += mag * dy;
      }
      let sx = rate * gx;
      let sy = rate * gy;
      const sl = Math.hypot(sx, sy);
      const cap = ENTITY_IDEAL * 0.45;
      if (sl > cap) {
        sx *= cap / sl;
        sy *= cap / sl;
      }
      next.set(id, { x: pi.x - sx, y: pi.y - sy });
    }
    for (const [id, p] of next) pos.set(id, p);
  }
  separate(pos, new Set());
  return pos;
}

function overlap(a: Vec, b: Vec): { dx: number; dy: number; ox: number; oy: number } | null {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const ox = MIN_X - Math.abs(dx);
  const oy = MIN_Y - Math.abs(dy);
  if (ox <= 0 || oy <= 0) return null;
  return { dx, dy, ox, oy };
}

/**
 * Push overlapping boxes apart. Pinned nodes stay put. A free node is not
 * walked farther than `maxDrift` from where it was first placed — otherwise
 * one crowded action gets shoved to the far side of the canvas.
 */
function separate(pos: Map<string, Vec>, pinned: Set<string>, maxDrift = Infinity) {
  const home = new Map<string, Vec>();
  for (const [id, point] of pos) home.set(id, { x: point.x, y: point.y });
  const ids = [...pos.keys()].sort();
  const nudge = (id: string, dx: number, dy: number) => {
    if (pinned.has(id) || (dx === 0 && dy === 0)) return false;
    const point = pos.get(id)!;
    const origin = home.get(id)!;
    let x = point.x + dx;
    let y = point.y + dy;
    if (Number.isFinite(maxDrift)) {
      const drift = Math.hypot(x - origin.x, y - origin.y);
      if (drift > maxDrift) {
        const scale = maxDrift / drift;
        x = origin.x + (x - origin.x) * scale;
        y = origin.y + (y - origin.y) * scale;
      }
    }
    if (Math.hypot(x - point.x, y - point.y) < 0.5) return false;
    point.x = x;
    point.y = y;
    return true;
  };
  for (let iter = 0; iter < 80; iter++) {
    let moved = false;
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const ia = ids[i];
        const ib = ids[j];
        const hit = overlap(pos.get(ia)!, pos.get(ib)!);
        if (!hit) continue;
        const pinA = pinned.has(ia);
        const pinB = pinned.has(ib);
        if (pinA && pinB) continue;
        const useX = hit.ox <= hit.oy;
        const amount = (useX ? hit.ox : hit.oy) + 2;
        const raw = useX ? hit.dx : hit.dy;
        const sign = raw === 0 ? 1 : Math.sign(raw);
        const primary = useX ? { x: sign * amount, y: 0 } : { x: 0, y: sign * amount };
        const otherSign = useX ? (hit.dy === 0 ? 1 : Math.sign(hit.dy)) : hit.dx === 0 ? 1 : Math.sign(hit.dx);
        const secondary = useX
          ? { x: 0, y: otherSign * (hit.oy + 2) }
          : { x: otherSign * (hit.ox + 2), y: 0 };
        const apply = (delta: { x: number; y: number }) => {
          if (!pinA && !pinB) return nudge(ia, delta.x / 2, delta.y / 2) || nudge(ib, -delta.x / 2, -delta.y / 2);
          if (!pinA) return nudge(ia, delta.x, delta.y);
          return nudge(ib, -delta.x, -delta.y);
        };
        if (apply(primary) || apply(secondary)) moved = true;
      }
    }
    if (!moved) break;
  }
}

function relatedEntities(nodeId: string, entityIds: Set<string>, edges: Edge[]): string[] {
  const found = new Set<string>();
  for (const edge of edges) {
    if (!DRAWN_ROLES.has(edge.role)) continue;
    const other =
      edge.source_node_id === nodeId ? edge.target_node_id : edge.target_node_id === nodeId ? edge.source_node_id : "";
    if (other && entityIds.has(other)) found.add(other);
  }
  return [...found];
}

const CARDINALS: Vec[] = [
  { x: 1, y: 0 },
  { x: 0, y: 1 },
  { x: -1, y: 0 },
  { x: 0, y: -1 },
];

/** A short axis-aligned block just off `origin`, so a group stays a group. */
function gridCells(origin: Vec, dir: Vec, count: number, gap: number): Vec[] {
  const perp = { x: -dir.y, y: dir.x };
  const cols = count > 4 ? 2 : 1;
  const rows = Math.ceil(count / cols);
  const cells: Vec[] = [];
  for (let i = 0; i < count; i++) {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const spread = (row - (rows - 1) / 2) * MIN_Y;
    const side = gap + col * MIN_X;
    cells.push({
      x: origin.x + dir.x * side + perp.x * spread,
      y: origin.y + dir.y * side + perp.y * spread,
    });
  }
  return cells;
}

function clearance(cells: Vec[], occupied: Vec[]): number {
  let score = 0;
  for (const cell of cells) {
    let nearest = Infinity;
    for (const point of occupied) nearest = Math.min(nearest, Math.hypot(cell.x - point.x, cell.y - point.y));
    score += nearest;
  }
  return score;
}

function freestGrid(origin: Vec, count: number, occupied: Vec[], gap: number): Vec[] {
  let best = gridCells(origin, CARDINALS[0], count, gap);
  let bestScore = -Infinity;
  for (const dir of CARDINALS) {
    const cells = gridCells(origin, dir, count, gap);
    const score = clearance(cells, occupied);
    if (score > bestScore) {
      bestScore = score;
      best = cells;
    }
  }
  return best;
}

function placeGroup(actions: ModelNode[], anchors: Vec[], occupied: Vec[]): Vec[] {
  if (anchors.length === 1) return freestGrid(anchors[0], actions.length, occupied, MIN_X);
  const mid = {
    x: anchors.reduce((sum, point) => sum + point.x, 0) / anchors.length,
    y: anchors.reduce((sum, point) => sum + point.y, 0) / anchors.length,
  };
  let left = anchors[0];
  let right = anchors[1];
  let span = -1;
  for (let i = 0; i < anchors.length; i++) {
    for (let j = i + 1; j < anchors.length; j++) {
      const gap = Math.hypot(anchors[i].x - anchors[j].x, anchors[i].y - anchors[j].y);
      if (gap > span) {
        span = gap;
        left = anchors[i];
        right = anchors[j];
      }
    }
  }
  const len = hypot(right.x - left.x, right.y - left.y);
  const px = -(right.y - left.y) / len;
  const py = (right.x - left.x) / len;
  const cardinal = Math.abs(px) >= Math.abs(py) ? { x: Math.sign(px) || 1, y: 0 } : { x: 0, y: Math.sign(py) || 1 };
  const flip = { x: -cardinal.x, y: -cardinal.y };
  const beside = gridCells(mid, cardinal, actions.length, MIN_Y);
  const other = gridCells(mid, flip, actions.length, MIN_Y);
  return clearance(beside, occupied) >= clearance(other, occupied) ? beside : other;
}

function placeOrphans(nodes: ModelNode[], pos: Map<string, Vec>) {
  let maxX = 0;
  for (const point of pos.values()) maxX = Math.max(maxX, point.x);
  nodes.forEach((node, i) => {
    const col = Math.floor(i / 8);
    const row = i % 8;
    pos.set(node.id, { x: maxX + MIN_X * (col + 1), y: row * MIN_Y });
  });
}

/**
 * Deterministic layout. Linked entities stay near each other, and each action
 * sits with the entities it is connected to. Actions are not lined up on one
 * rank below the entities — that rank made every action edge cross the canvas.
 */
export function computeLayout(graph: Graph): Map<string, Positioned> {
  const entities = graph.nodes.filter((node) => node.kind === "entity");
  const rest = graph.nodes.filter((node) => node.kind !== "entity").sort(byName);
  const entityIds = new Set(entities.map((node) => node.id));
  const names = new Map(graph.nodes.map((node) => [node.id, node.name]));
  const edges = graph.edges || [];

  const links: Array<[string, string]> = [];
  const seen = new Set<string>();
  const addLink = (a: string, b: string) => {
    if (!entityIds.has(a) || !entityIds.has(b) || a === b) return;
    const key = a < b ? `${a}|${b}` : `${b}|${a}`;
    if (seen.has(key)) return;
    seen.add(key);
    links.push(a < b ? [a, b] : [b, a]);
  };
  for (const link of graph.links || []) addLink(link.from_node_id, link.to_node_id);
  for (const edge of edges) {
    if (DRAWN_ROLES.has(edge.role)) addLink(edge.source_node_id, edge.target_node_id);
  }
  for (const node of rest) {
    const related = relatedEntities(node.id, entityIds, edges).sort((a, b) => {
      const na = names.get(a) || a;
      const nb = names.get(b) || b;
      return na < nb ? -1 : na > nb ? 1 : a < b ? -1 : 1;
    });
    for (let i = 0; i < related.length; i++) {
      for (let j = i + 1; j < related.length; j++) addLink(related[i], related[j]);
    }
  }

  const pos = layoutEntities(entities, links);
  const groups = new Map<string, { ids: string[]; actions: ModelNode[] }>();
  const orphans: ModelNode[] = [];
  for (const node of rest) {
    const related = relatedEntities(node.id, entityIds, edges);
    if (related.length === 0) {
      orphans.push(node);
      continue;
    }
    related.sort((a, b) => {
      const na = names.get(a) || a;
      const nb = names.get(b) || b;
      return na < nb ? -1 : na > nb ? 1 : a < b ? -1 : 1;
    });
    const key = related.join("|");
    const group = groups.get(key) ?? { ids: related, actions: [] };
    group.actions.push(node);
    groups.set(key, group);
  }
  const orderedGroups = [...groups.values()].sort((a, b) => {
    if (a.ids.length !== b.ids.length) return b.ids.length - a.ids.length;
    const ka = a.ids.join("|");
    const kb = b.ids.join("|");
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  });
  const occupied = [...pos.values()];
  for (const group of orderedGroups) {
    const anchors = group.ids.map((id) => pos.get(id)!).filter(Boolean);
    if (anchors.length === 0) {
      orphans.push(...group.actions);
      continue;
    }
    const placed = placeGroup(group.actions, anchors, occupied);
    group.actions.forEach((node, i) => {
      pos.set(node.id, placed[i]);
      occupied.push(placed[i]);
    });
  }
  placeOrphans(orphans, pos);
  separate(pos, entityIds, MIN_X * 1.5);

  let minX = Infinity;
  let minY = Infinity;
  for (const point of pos.values()) {
    minX = Math.min(minX, point.x - BOX_W / 2);
    minY = Math.min(minY, point.y - BOX_H / 2);
  }
  if (!Number.isFinite(minX)) minX = 0;
  if (!Number.isFinite(minY)) minY = 0;
  const out = new Map<string, Positioned>();
  for (const [id, point] of pos) {
    out.set(id, { id, x: point.x - BOX_W / 2 - minX + MARGIN, y: point.y - BOX_H / 2 - minY + MARGIN });
  }
  return out;
}
