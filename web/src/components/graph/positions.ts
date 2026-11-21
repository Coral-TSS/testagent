/** Browser memory for nodes a person has dragged. Same pattern as the drawer width. */
export const GRAPH_POSITIONS_KEY = "testagent:graph-node-positions";

export interface Point {
  x: number;
  y: number;
}

type PositionStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function storeOf(storage?: PositionStore): PositionStore | null {
  if (storage) return storage;
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function readObject(storage: PositionStore): Record<string, Point> {
  try {
    const raw = storage.getItem(GRAPH_POSITIONS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, Point> = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!value || typeof value !== "object") continue;
      const point = value as { x?: unknown; y?: unknown };
      if (typeof point.x === "number" && typeof point.y === "number" && Number.isFinite(point.x) && Number.isFinite(point.y)) {
        out[id] = { x: point.x, y: point.y };
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function readGraphPositions(storage?: PositionStore): Map<string, Point> {
  const store = storeOf(storage);
  if (!store) return new Map();
  return new Map(Object.entries(readObject(store)));
}

function writeAll(store: PositionStore, positions: Record<string, Point>) {
  if (Object.keys(positions).length === 0) store.removeItem(GRAPH_POSITIONS_KEY);
  else store.setItem(GRAPH_POSITIONS_KEY, JSON.stringify(positions));
}

export function writeGraphPosition(id: string, point: Point, storage?: PositionStore) {
  const store = storeOf(storage);
  if (!store || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
  try {
    const all = readObject(store);
    all[id] = { x: point.x, y: point.y };
    writeAll(store, all);
  } catch {
    /* Dragging still works when the browser refuses storage. */
  }
}

export function clearGraphPosition(id: string, storage?: PositionStore) {
  const store = storeOf(storage);
  if (!store) return;
  try {
    const all = readObject(store);
    delete all[id];
    writeAll(store, all);
  } catch {
    /* Dragging still works when the browser refuses storage. */
  }
}
