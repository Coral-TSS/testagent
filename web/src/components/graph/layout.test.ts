import type { Graph, Link, ModelNode } from "../../api/types";
import { computeLayout } from "./layout";
import { toFlow } from "./GraphCanvas";

const node = (id: string, kind: ModelNode["kind"]): ModelNode => ({ id, sut_id: "s", kind, name: id, attributes: {} });
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

describe("computeLayout", () => {
  const graph: Graph = {
    nodes: [node("a", "entity"), node("b", "entity"), node("c", "entity"), node("act", "action")],
    edges: [{ id: "e3", source_node_id: "act", target_node_id: "a", role: "object" }],
    links: [link("l1", "a", "c")],
  };

  it("positions every node deterministically", () => {
    const first = computeLayout(graph);
    expect([...first.keys()].sort()).toEqual(["a", "act", "b", "c"]);
    expect(computeLayout(graph)).toEqual(first);
  });

  it("places linked entities next to each other and actions below entities", () => {
    const pos = computeLayout(graph);
    const [a, b, c, act] = ["a", "b", "c", "act"].map((id) => pos.get(id)!);
    expect(c.y).toBe(a.y);
    expect(c.x).toBeLessThan(b.x + (b.y > a.y ? 1000 : 0));
    expect(act.y).toBeGreaterThan(Math.max(a.y, b.y, c.y));
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
    const l1 = edges.find((e) => e.id === "link:l1")!;
    expect(l1.source).toBe("po");
    expect(l1.target).toBe("sup");
    expect(l1.type).toBe("link");
    expect(l1.data).toMatchObject({ forward: "belongs to", reverse: "supplies", card: "N:1" });
    const l2 = edges.find((e) => e.id === "link:l2")!;
    expect(l2.data).toMatchObject({ forward: "pays", reverse: "receives", card: "N:1" });
    expect(edges.find((e) => e.id === "e1")?.label).toBe("object");
  });
});
