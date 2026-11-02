import {
  Background,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge as FlowEdge,
  type Node as FlowNode,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";

import type { Graph, ModelNode } from "../../api/types";
import { CARD_SHORT } from "../links";
import { KIND_COLOR } from "../StatusTags";
import { computeLayout } from "./layout";

type Data = { node: ModelNode; selected: boolean };

const SIDES = [
  ["top", Position.Top],
  ["bottom", Position.Bottom],
  ["left", Position.Left],
  ["right", Position.Right],
] as const;
const handles = (
  <>
    {SIDES.map(([id, p]) => (
      <span key={id}>
        <Handle id={`${id}-t`} type="target" position={p} style={{ opacity: 0 }} />
        <Handle id={`${id}-s`} type="source" position={p} style={{ opacity: 0 }} />
      </span>
    ))}
  </>
);

function BoxNode({ data }: NodeProps<FlowNode<Data>>) {
  const { node, selected } = data;
  const color = KIND_COLOR[node.kind];
  const attrCount =
    (node.attributes.conditions?.length || 0) + (node.attributes.states?.length || 0) + (node.attributes.constraints?.length || 0);
  return (
    <div
      style={{
        padding: "8px 14px",
        borderRadius: node.kind === "action" ? 20 : 6,
        border: `2px solid ${color}`,
        background: selected ? color : "#fff",
        color: selected ? "#fff" : "#222",
        minWidth: 110,
        textAlign: "center",
        fontSize: 13,
      }}
    >
      {handles}
      <div style={{ fontWeight: 600 }}>{node.name}</div>
      {attrCount > 0 && <div style={{ fontSize: 11, opacity: 0.75 }}>{attrCount} attribute(s)</div>}
    </div>
  );
}

type LinkData = { forward: string; reverse: string; card: string; via?: string | null; fk?: string | null; required?: boolean };

/** A relation drawn between two entities: "belongs to →" / "← supplies" with the cardinality in the middle. */
function LinkEdge(props: EdgeProps<FlowEdge<LinkData>>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, selected } = props;
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const color = KIND_COLOR.relation;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ stroke: color, strokeWidth: selected ? 3 : 2 }} />
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan"
          data-testid={`link-label-${id}`}
          title={[data?.fk ? `foreign key ${data.fk}` : "", data?.via ? `junction entity ${data.via}` : "", data?.required ? "required" : ""]
            .filter(Boolean)
            .join(", ")}
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: "all",
            cursor: "pointer",
            background: "#fff",
            border: `1px solid ${color}`,
            borderRadius: 6,
            padding: "2px 6px",
            fontSize: 11,
            lineHeight: "16px",
            textAlign: "center",
            whiteSpace: "nowrap",
          }}
        >
          <div>{data?.forward} →</div>
          <div style={{ background: color, color: "#fff", borderRadius: 4, padding: "0 4px", margin: "1px 0", fontWeight: 600 }}>
            {data?.card}
            {data?.via ? ` · via ${data.via}` : ""}
          </div>
          <div>← {data?.reverse}</div>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { entity: BoxNode, action: BoxNode, relation: BoxNode };
const edgeTypes = { link: LinkEdge };

/** Choose the facing sides of two nodes so link edges do not cross the boxes. */
function sides(a?: { x: number; y: number }, b?: { x: number; y: number }) {
  if (!a || !b) return { sourceHandle: "right-s", targetHandle: "left-t" };
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (a === b || (dx === 0 && dy === 0)) return { sourceHandle: "right-s", targetHandle: "top-t" };
  if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? { sourceHandle: "right-s", targetHandle: "left-t" } : { sourceHandle: "left-s", targetHandle: "right-t" };
  return dy > 0 ? { sourceHandle: "bottom-s", targetHandle: "top-t" } : { sourceHandle: "top-s", targetHandle: "bottom-t" };
}
const ROLE_LABEL: Record<string, string> = { source: "Source", target: "Target", actor: "Actor", object: "object", ref: "References" };

export function toFlow(graph: Graph, selectedId?: string | null) {
  const layout = computeLayout(graph);
  const nodes: FlowNode<Data>[] = graph.nodes.map((n) => ({
    id: n.id,
    type: n.kind,
    position: { x: layout.get(n.id)?.x ?? 0, y: layout.get(n.id)?.y ?? 0 },
    data: { node: n, selected: n.id === selectedId },
  }));
  const ids = new Set(graph.nodes.map((n) => n.id));
  const edges: FlowEdge[] = graph.edges
    .filter((e) => e.role !== "source" && e.role !== "target" && ids.has(e.source_node_id) && ids.has(e.target_node_id))
    .map((e) => ({
      id: e.id,
      source: e.source_node_id,
      target: e.target_node_id,
      ...sides(layout.get(e.source_node_id), layout.get(e.target_node_id)),
      label: ROLE_LABEL[e.role] || e.role,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { strokeDasharray: "4 4", stroke: "#bbb" },
    }));
  for (const l of graph.links || []) {
    if (!ids.has(l.from_node_id) || !ids.has(l.to_node_id)) continue;
    edges.push({
      id: `link:${l.id}`,
      type: "link",
      source: l.from_node_id,
      target: l.to_node_id,
      ...sides(layout.get(l.from_node_id), layout.get(l.to_node_id)),
      markerEnd: { type: MarkerType.ArrowClosed, color: KIND_COLOR.relation },
      data: {
        forward: l.forward_name,
        reverse: l.reverse_name,
        card: CARD_SHORT[l.cardinality],
        via: l.via_name,
        fk: l.fk_field,
        required: l.required,
      } satisfies LinkData,
    });
  }
  return { nodes, edges };
}

export function GraphCanvas({
  graph,
  selectedId,
  onSelect,
  onLinkClick,
  height = 600,
}: {
  graph: Graph;
  selectedId?: string | null;
  onSelect: (id: string) => void;
  onLinkClick?: (linkId: string) => void;
  height?: number;
}) {
  const { nodes, edges } = useMemo(() => toFlow(graph, selectedId), [graph, selectedId]);
  return (
    <div style={{ height, border: "1px solid #f0f0f0", borderRadius: 8 }} data-testid="graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={(_, n) => onSelect(n.id)}
        onEdgeClick={(_, e) => {
          if (e.id.startsWith("link:")) onLinkClick?.(e.id.slice(5));
        }}
        nodesConnectable={false}
        fitView
        minZoom={0.2}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={(n) => KIND_COLOR[(n.type as string) || "entity"]} />
      </ReactFlow>
    </div>
  );
}
