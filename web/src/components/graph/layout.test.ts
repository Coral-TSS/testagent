import { Position } from "@xyflow/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";

import type { Edge, Graph, Link, ModelNode } from "../../api/types";
import { EDGE_COLOR, GraphCanvas, ROLE_LABEL, curvedEdgePath, toFlow } from "./GraphCanvas";
import { computeLayout, type Positioned } from "./layout";
import { clearGraphPosition, clearGraphPositions, GRAPH_POSITIONS_KEY, readGraphPositions, writeGraphPosition } from "./positions";

const node = (id: string, kind: ModelNode["kind"], name = id): ModelNode => ({ id, sut_id: "s", kind, name, attributes: {} });
const link = (id: string, from: string, to: string, extra: Partial<Link> = {}): Link =>
  ({
    id,
    sut_id: "s",
    from_node_id: from,
    to_node_id: to,
    from_name: from,
    to_name: to,
    forward_name: "belongs to",
    reverse_name: "supplies",
    cardinality: "many_to_one",
    required: false,
    ...extra,
  }) as Link;

/** The previous layout: every action on one row under the entity grid. */
function bottomRankLayout(graph: Graph): Map<string, Positioned> {
  const pos = new Map<string, Positioned>();
  const entities = graph.nodes.filter((n) => n.kind === "entity");
  const actions = graph.nodes.filter((n) => n.kind === "action");
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
  order.forEach((id, i) => pos.set(id, { id, x: (i % cols) * 320, y: Math.floor(i / cols) * 220 }));
  const entityRows = Math.ceil(order.length / cols);
  graph.nodes
    .filter((n) => n.kind !== "entity" && n.kind !== "action")
    .forEach((n, i) => pos.set(n.id, { id: n.id, x: i * 220, y: -220 }));
  const actionY = entityRows * 220 + 80;
  actions.forEach((n, i) => pos.set(n.id, { id: n.id, x: i * 220, y: actionY }));
  return pos;
}

function dist(pos: Map<string, Positioned>, a: string, b: string) {
  const pa = pos.get(a)!;
  const pb = pos.get(b)!;
  return Math.hypot(pa.x - pb.x, pa.y - pb.y);
}

function segmentsCross(a: Positioned, b: Positioned, c: Positioned, d: Positioned) {
  const cross = (p: Positioned, q: Positioned, r: Positioned) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  const ab = cross(a, b, c);
  const cd = cross(a, b, d);
  const ac = cross(c, d, a);
  const bd = cross(c, d, b);
  return ab * cd < 0 && ac * bd < 0;
}

function crossings(pos: Map<string, Positioned>, pairs: Array<[string, string]>) {
  let count = 0;
  for (let i = 0; i < pairs.length; i++) {
    for (let j = i + 1; j < pairs.length; j++) {
      const [a, b] = pairs[i];
      const [c, d] = pairs[j];
      if (a === c || a === d || b === c || b === d) continue;
      if (segmentsCross(pos.get(a)!, pos.get(b)!, pos.get(c)!, pos.get(d)!)) count += 1;
    }
  }
  return count;
}

function meanAnchorDistance(graph: Graph, pos: Map<string, Positioned>) {
  const entities = new Set(graph.nodes.filter((n) => n.kind === "entity").map((n) => n.id));
  let total = 0;
  let count = 0;
  for (const action of graph.nodes.filter((n) => n.kind === "action")) {
    const related = new Set<string>();
    for (const edge of graph.edges) {
      if (edge.role === "source" || edge.role === "target") continue;
      if (edge.source_node_id === action.id && entities.has(edge.target_node_id)) related.add(edge.target_node_id);
      if (edge.target_node_id === action.id && entities.has(edge.source_node_id)) related.add(edge.source_node_id);
    }
    for (const id of related) {
      total += dist(pos, action.id, id);
      count += 1;
    }
  }
  return count ? total / count : 0;
}

/** Supply-chain v2 shape: entities, the links between them, and each action's entities. */
function supplyChain(): Graph {
  const entities = [
    "Material",
    "Supplier",
    "SupplierMaterial",
    "Warehouse",
    "Inventory",
    "Buyer",
    "PurchaseRequisition",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "GoodsReceipt",
    "QualityInspection",
  ];
  const actionEnds: Array<[string, string, Array<[string, Edge["role"]]>]> = [
    ["新建采购申请", "create-req", [["Buyer", "actor"], ["PurchaseRequisition", "object"]]],
    ["提交采购申请", "submit-req", [["Buyer", "actor"], ["PurchaseRequisition", "object"]]],
    ["审批采购申请", "approve-req", [["Buyer", "actor"], ["PurchaseRequisition", "object"]]],
    ["按申请创建采购订单", "create-po", [["PurchaseRequisition", "object"], ["PurchaseOrder", "object"]]],
    ["提交采购订单", "submit-po", [["Buyer", "actor"], ["PurchaseOrder", "object"]]],
    ["审批采购订单", "approve-po", [["Buyer", "actor"], ["PurchaseOrder", "object"]]],
    ["下达采购订单", "issue-po", [["PurchaseOrder", "object"]]],
    ["按订单收货", "receive", [["PurchaseOrder", "object"], ["GoodsReceipt", "object"]]],
    ["收货过账入库", "post", [["GoodsReceipt", "object"], ["Inventory", "object"]]],
    ["关闭采购订单", "close-po", [["PurchaseOrder", "object"]]],
    ["取消采购订单", "cancel-po", [["PurchaseOrder", "object"]]],
    ["冻结供应商", "freeze", [["Supplier", "object"]]],
    ["查询库存", "query-inv", [["Inventory", "object"]]],
    ["创建质检单", "create-qi", [["GoodsReceipt", "object"], ["QualityInspection", "object"]]],
    ["判定质检", "decide-qi", [["QualityInspection", "object"]]],
  ];
  const linkEnds: Array<[string, string]> = [
    ["PurchaseRequisition", "Material"],
    ["PurchaseRequisition", "Buyer"],
    ["PurchaseRequisition", "Supplier"],
    ["PurchaseRequisition", "PurchaseOrder"],
    ["PurchaseOrder", "Supplier"],
    ["PurchaseOrder", "Buyer"],
    ["PurchaseOrder", "PurchaseOrderLine"],
    ["PurchaseOrderLine", "Material"],
    ["SupplierMaterial", "Supplier"],
    ["SupplierMaterial", "Material"],
    ["GoodsReceipt", "PurchaseOrderLine"],
    ["GoodsReceipt", "Warehouse"],
    ["GoodsReceipt", "Material"],
    ["Inventory", "Warehouse"],
    ["Inventory", "Material"],
    ["QualityInspection", "GoodsReceipt"],
    ["QualityInspection", "Material"],
  ];
  const edges: Edge[] = [];
  for (const [, id, ends] of actionEnds) {
    ends.forEach(([target, role], index) => {
      edges.push({ id: `${id}-${index}`, source_node_id: id, target_node_id: target, role });
    });
  }
  return {
    nodes: [
      ...entities.map((name) => node(name, "entity", name)),
      ...actionEnds.map(([name, id]) => node(id, "action", name)),
    ],
    edges,
    links: linkEnds.map(([from, to], index) => link(`l${index}`, from, to)),
  };
}

function pairsOf(graph: Graph): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  for (const edge of graph.edges) {
    if (edge.role === "source" || edge.role === "target") continue;
    pairs.push([edge.source_node_id, edge.target_node_id]);
  }
  for (const item of graph.links || []) pairs.push([item.from_node_id, item.to_node_id]);
  return pairs;
}

describe("computeLayout", () => {
  const graph: Graph = {
    nodes: [node("a", "entity"), node("b", "entity"), node("c", "entity"), node("act", "action")],
    edges: [{ id: "e3", source_node_id: "act", target_node_id: "a", role: "object" }],
    links: [link("l1", "a", "c")],
  };

  it("positions every node deterministically and ignores input order", () => {
    const first = computeLayout(graph);
    expect([...first.keys()].sort()).toEqual(["a", "act", "b", "c"]);
    expect(computeLayout(graph)).toEqual(first);
    const shuffled: Graph = {
      nodes: [...graph.nodes].reverse(),
      edges: [...graph.edges].reverse(),
      links: [...(graph.links || [])].reverse(),
    };
    expect(computeLayout(shuffled)).toEqual(first);
  });

  it("keeps a linked entity nearer than an unlinked one, and the action beside its object", () => {
    const pos = computeLayout(graph);
    expect(dist(pos, "a", "c")).toBeLessThan(dist(pos, "a", "b"));
    expect(dist(pos, "a", "c")).toBeLessThan(dist(pos, "c", "b"));
    expect(dist(pos, "act", "a")).toBeLessThan(dist(pos, "act", "b"));
    expect(dist(pos, "act", "a")).toBeLessThan(dist(pos, "act", "c"));
    const ys = ["a", "b", "c", "act"].map((id) => pos.get(id)!.y);
    expect(new Set(ys).size).toBeGreaterThan(1);
  });
});

describe("supply-chain layout", () => {
  const graph = supplyChain();
  const fresh = computeLayout(graph);
  const previous = bottomRankLayout(graph);
  const lines = pairsOf(graph);

  it("does not park every action on one bottom rank", () => {
    const actions = graph.nodes.filter((n) => n.kind === "action").map((n) => fresh.get(n.id)!.y);
    const bands = new Set(actions.map((y) => Math.round(y / 40)));
    expect(bands.size).toBeGreaterThan(4);
    expect(Math.max(...actions) - Math.min(...actions)).toBeGreaterThan(400);
  });

  it("puts each action closer to the entities it touches than the bottom rank did", () => {
    const now = meanAnchorDistance(graph, fresh);
    const before = meanAnchorDistance(graph, previous);
    expect(now).toBeLessThan(before * 0.4);
    expect(crossings(fresh, lines)).toBeLessThan(crossings(previous, lines) / 4);
    const entities = new Set(graph.nodes.filter((item) => item.kind === "entity").map((item) => item.id));
    for (const action of graph.nodes.filter((item) => item.kind === "action")) {
      const related = graph.edges
        .filter((edge) => (edge.source_node_id === action.id || edge.target_node_id === action.id) && edge.role !== "source" && edge.role !== "target")
        .map((edge) => (edge.source_node_id === action.id ? edge.target_node_id : edge.source_node_id))
        .filter((id) => entities.has(id));
      const nearest = Math.min(...related.map((id) => dist(fresh, action.id, id)));
      expect(nearest).toBeLessThan(520);
    }
  });

  it("keeps linked entities closer together than unlinked ones, without stacking boxes", () => {
    const entities = graph.nodes.filter((n) => n.kind === "entity").map((n) => n.id);
    const linked = new Set((graph.links || []).map((item) => [item.from_node_id, item.to_node_id].sort().join("|")));
    let linkedSum = 0;
    let linkedCount = 0;
    let looseSum = 0;
    let looseCount = 0;
    for (let i = 0; i < entities.length; i++) {
      for (let j = i + 1; j < entities.length; j++) {
        const key = [entities[i], entities[j]].sort().join("|");
        const gap = dist(fresh, entities[i], entities[j]);
        if (linked.has(key)) {
          linkedSum += gap;
          linkedCount += 1;
        } else {
          looseSum += gap;
          looseCount += 1;
        }
      }
    }
    expect(linkedSum / linkedCount).toBeLessThan(looseSum / looseCount);

    const ids = [...fresh.keys()];
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = fresh.get(ids[i])!;
        const b = fresh.get(ids[j])!;
        const clear = Math.abs(a.x - b.x) >= 180 || Math.abs(a.y - b.y) >= 60;
        expect(clear).toBe(true);
      }
    }
  });

  it("groups an action with its own entities rather than with an unrelated one", () => {
    expect(dist(fresh, "freeze", "Supplier")).toBeLessThan(dist(fresh, "freeze", "PurchaseOrder"));
    expect(dist(fresh, "decide-qi", "QualityInspection")).toBeLessThan(dist(fresh, "decide-qi", "Buyer"));
    expect(dist(fresh, "query-inv", "Inventory")).toBeLessThan(dist(fresh, "query-inv", "PurchaseRequisition"));
    expect(dist(fresh, "create-po", "PurchaseOrder")).toBeLessThan(dist(fresh, "create-po", "Warehouse"));
    expect(dist(fresh, "create-po", "PurchaseRequisition")).toBeLessThan(dist(fresh, "create-po", "Warehouse"));
    expect(dist(fresh, "receive", "GoodsReceipt")).toBeLessThan(dist(fresh, "receive", "Supplier"));
    expect(dist(fresh, "post", "Inventory")).toBeLessThan(dist(fresh, "post", "Buyer"));
  });
});

describe("toFlow", () => {
  it("draws links as labelled edges between entities with a cardinality badge", () => {
    const g: Graph = {
      nodes: [node("po", "entity"), node("sup", "entity"), node("pay", "entity"), node("act", "action")],
      edges: [{ id: "e1", source_node_id: "act", target_node_id: "po", role: "object" }],
      links: [
        link("l1", "po", "sup", { from_name: "PurchaseOrder", to_name: "Supplier" }),
        link("l2", "pay", "po", {
          from_name: "Payment",
          to_name: "PurchaseOrder",
          forward_name: "pays",
          reverse_name: "receives",
          fk_field: "Payment.order_id",
        }),
      ],
    };
    const { nodes, edges } = toFlow(g);
    expect(nodes).toHaveLength(4);
    expect(nodes.every((item) => item.draggable)).toBe(true);
    const l1 = edges.find((e) => e.id === "link:l1")!;
    expect(l1.source).toBe("po");
    expect(l1.target).toBe("sup");
    expect(l1.type).toBe("link");
    expect(l1.data).toMatchObject({ forward: "belongs to", reverse: "supplies", card: "N:1" });
    const l2 = edges.find((e) => e.id === "link:l2")!;
    expect(l2.data).toMatchObject({ forward: "pays", reverse: "receives", card: "N:1" });
    const actionEdge = edges.find((e) => e.id === "e1")!;
    expect(actionEdge.label).toBe("作用于");
    expect(actionEdge.type).toBe("default");
    expect(actionEdge.style).toMatchObject({ stroke: EDGE_COLOR.action, strokeWidth: 2 });
    expect(actionEdge.style).not.toHaveProperty("strokeDasharray");
    expect(l1.style).toMatchObject({ stroke: EDGE_COLOR.relation, strokeWidth: 2 });
    expect(l1.style).not.toHaveProperty("strokeDasharray");
    expect(ROLE_LABEL).toEqual({ object: "作用于", actor: "执行人", ref: "引用了", source: "起点", target: "终点" });
    expect(EDGE_COLOR.action).not.toBe(EDGE_COLOR.relation);
  });

  it("labels actor and ref edges in plain Chinese and hides source and target", () => {
    const g: Graph = {
      nodes: [node("act", "action"), node("buyer", "entity"), node("po", "entity")],
      edges: [
        { id: "actor", source_node_id: "act", target_node_id: "buyer", role: "actor" },
        { id: "ref", source_node_id: "act", target_node_id: "po", role: "ref" },
        { id: "src", source_node_id: "act", target_node_id: "po", role: "source" },
        { id: "dst", source_node_id: "act", target_node_id: "buyer", role: "target" },
      ],
      links: [],
    };
    const { edges } = toFlow(g);
    expect(edges.find((e) => e.id === "actor")?.label).toBe("执行人");
    expect(edges.find((e) => e.id === "ref")?.label).toBe("引用了");
    expect(edges.find((e) => e.id === "src")).toBeUndefined();
    expect(edges.find((e) => e.id === "dst")).toBeUndefined();
  });

  it("routes handles from a dragged position instead of the default layout", () => {
    const g: Graph = {
      nodes: [node("po", "entity"), node("sup", "entity")],
      edges: [],
      links: [link("l1", "po", "sup")],
    };
    const { edges } = toFlow(
      g,
      null,
      new Map([
        ["po", { x: 0, y: 0 }],
        ["sup", { x: 400, y: 8 }],
      ]),
    );
    const edge = edges.find((item) => item.id === "link:l1")!;
    expect(edge.sourceHandle).toBe("right-s");
    expect(edge.targetHandle).toBe("left-t");
  });
});

describe("graph positions", () => {
  it("remembers a dragged point and drops it again", () => {
    const mem = new Map<string, string>();
    const storage = {
      getItem: (key: string) => mem.get(key) ?? null,
      setItem: (key: string, value: string) => {
        mem.set(key, value);
      },
      removeItem: (key: string) => {
        mem.delete(key);
      },
    };
    writeGraphPosition("n1", { x: 10, y: 20 }, storage);
    writeGraphPosition("n2", { x: 1, y: 2 }, storage);
    expect(readGraphPositions(storage).get("n1")).toEqual({ x: 10, y: 20 });
    clearGraphPosition("n1", storage);
    expect(readGraphPositions(storage).has("n1")).toBe(false);
    expect(readGraphPositions(storage).get("n2")).toEqual({ x: 1, y: 2 });
    writeGraphPosition("n3", { x: 8, y: 9 }, storage);
    clearGraphPositions(["n2"], storage);
    expect(readGraphPositions(storage).has("n2")).toBe(false);
    expect(readGraphPositions(storage).get("n3")).toEqual({ x: 8, y: 9 });
    storage.setItem(GRAPH_POSITIONS_KEY, "{");
    expect(readGraphPositions(storage).size).toBe(0);
    storage.setItem(GRAPH_POSITIONS_KEY, JSON.stringify({ bad: { x: "no" }, ok: { x: 3, y: 4 } }));
    expect([...readGraphPositions(storage).keys()]).toEqual(["ok"]);
  });
});

describe("GraphCanvas", () => {
  beforeEach(() => localStorage.clear());

  it("shows the node and marks it draggable", () => {
    render(createElement(GraphCanvas, { graph: { nodes: [node("a", "entity", "物料")], edges: [], links: [] }, onSelect: () => {} }));
    expect(screen.getByText("物料")).toBeTruthy();
    expect(document.querySelector(".react-flow__node")?.className).toContain("draggable");
    expect(screen.getByRole("button", { name: "重排" })).toBeTruthy();
  });

  it("draws relation and action lines as solid curves in two colors", () => {
    const [path] = curvedEdgePath({
      sourceX: 0,
      sourceY: 0,
      targetX: 240,
      targetY: 20,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    });
    expect(path.startsWith("M")).toBe(true);
    expect(path).toMatch(/C/);
    expect(path).not.toMatch(/\bL\b/);
    const graph: Graph = {
      nodes: [node("po", "entity", "订单"), node("sup", "entity", "供应商"), node("act", "action", "提交")],
      edges: [{ id: "e1", source_node_id: "act", target_node_id: "po", role: "object" }],
      links: [link("l1", "po", "sup")],
    };
    const { edges } = toFlow(graph);
    const action = edges.find((edge) => edge.id === "e1")!;
    const relation = edges.find((edge) => edge.id === "link:l1")!;
    expect(action.type).toBe("default");
    expect(relation.type).toBe("link");
    expect(action.style).toMatchObject({ stroke: EDGE_COLOR.action });
    expect(relation.style).toMatchObject({ stroke: EDGE_COLOR.relation });
    for (const edge of [action, relation]) {
      expect(JSON.stringify(edge.style)).not.toMatch(/dash/i);
    }
  });

  it("重排 forgets dragged positions and puts nodes back on the layout", () => {
    const graph: Graph = {
      nodes: [node("a", "entity", "物料"), node("b", "action", "提交")],
      edges: [{ id: "e", source_node_id: "b", target_node_id: "a", role: "object" }],
      links: [],
    };
    localStorage.setItem(GRAPH_POSITIONS_KEY, JSON.stringify({ a: { x: 900, y: 40 }, other: { x: 3, y: 4 } }));
    render(createElement(GraphCanvas, { graph, onSelect: () => {} }));
    expect(document.querySelector('[data-id="a"]')?.getAttribute("style") || "").toContain("900px");
    fireEvent.click(screen.getByRole("button", { name: "重排" }));
    expect(readGraphPositions().has("a")).toBe(false);
    expect(readGraphPositions().get("other")).toEqual({ x: 3, y: 4 });
    const laid = computeLayout(graph).get("a")!;
    expect(document.querySelector('[data-id="a"]')?.getAttribute("style") || "").toContain(`${laid.x}px`);
    expect(document.querySelector(".react-flow__node")?.className).toContain("draggable");
  });
});
