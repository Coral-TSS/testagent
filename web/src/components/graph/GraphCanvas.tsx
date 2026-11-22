import { Button } from "antd";
import {
  Background,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
  type NodeChange,
  type ReactFlowInstance,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  type Edge as FlowEdge,
  type Node as FlowNode,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Graph, ModelNode } from "../../api/types";
import { CARD_SHORT } from "../links";
import { KIND_COLOR } from "../StatusTags";
import { actionEdgeLabel } from "./edgeLabel";
import { computeLayout, type Positioned } from "./layout";
import { clearGraphPosition, clearGraphPositions, readGraphPositions, writeGraphPosition, type Point } from "./positions";

/** Solid curves. Relation orange vs action blue, dark enough to read on the white canvas. */
export const EDGE_COLOR = { action: "#0958d9", relation: "#d46b08" } as const;

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
        <Handle id={`${id}-t`} type="target" position={p} className="graph-handle" />
        <Handle id={`${id}-s`} type="source" position={p} className="graph-handle" />
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
        cursor: "grab",
      }}
      title="拖动以调整位置"
    >
      {handles}
      <div style={{ fontWeight: 600 }}>{node.name}</div>
      {attrCount > 0 && <div style={{ fontSize: 11, opacity: 0.75 }}>{attrCount} 个属性</div>}
    </div>
  );
}

type LinkData = { forward: string; reverse: string; card: string; via?: string | null; fk?: string | null; required?: boolean };

/** Both edge kinds use this cubic curve. Straight and stepped paths are not used. */
export function curvedEdgePath(points: Parameters<typeof getBezierPath>[0]) {
  return getBezierPath({ curvature: 0.25, ...points });
}

/** A relation drawn between two entities: "属于 →" / "← 供应" with the cardinality in the middle. */
function LinkEdge(props: EdgeProps<FlowEdge<LinkData>>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, selected } = props;
  const [path, labelX, labelY] = curvedEdgePath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const color = (typeof props.style?.stroke === "string" && props.style.stroke) || EDGE_COLOR.relation;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ stroke: color, strokeWidth: selected ? 3 : 2 }} />
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan"
          data-testid={`link-label-${id}`}
          title={[data?.fk ? `外键 ${data.fk}` : "", data?.via ? `中间实体 ${data.via}` : "", data?.required ? "必填" : ""]
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

const layoutCache = new WeakMap<Graph, Map<string, Positioned>>();

export function toFlow(graph: Graph, selectedId?: string | null, placed?: ReadonlyMap<string, Point>) {
  let layout = layoutCache.get(graph);
  if (!layout) {
    layout = computeLayout(graph);
    layoutCache.set(graph, layout);
  }
  const at = (id: string) => {
    const custom = placed?.get(id);
    if (custom && Number.isFinite(custom.x) && Number.isFinite(custom.y)) return custom;
    const point = layout.get(id);
    return point ? { x: point.x, y: point.y } : undefined;
  };
  const nodes: FlowNode<Data>[] = graph.nodes.map((n) => ({
    id: n.id,
    type: n.kind,
    position: { x: at(n.id)?.x ?? 0, y: at(n.id)?.y ?? 0 },
    draggable: true,
    data: { node: n, selected: n.id === selectedId },
  }));
  const ids = new Set(graph.nodes.map((n) => n.id));
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const edges: FlowEdge[] = graph.edges
    .filter((e) => e.role !== "source" && e.role !== "target" && ids.has(e.source_node_id) && ids.has(e.target_node_id))
    .map((e) => {
      const sourceNode = byId.get(e.source_node_id);
      const targetNode = byId.get(e.target_node_id);
      const swap = sourceNode?.kind !== "action" && targetNode?.kind === "action";
      const source = swap ? e.target_node_id : e.source_node_id;
      const target = swap ? e.source_node_id : e.target_node_id;
      const action = byId.get(source);
      const entity = byId.get(target);
      return {
        id: e.id,
        source,
        target,
        type: "default",
        ...sides(at(source), at(target)),
        label: actionEdgeLabel(e.role, action?.kind === "action" ? action : undefined, entity),
        markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR.action },
        style: { stroke: EDGE_COLOR.action, strokeWidth: 2 },
      };
    });
  for (const l of graph.links || []) {
    if (!ids.has(l.from_node_id) || !ids.has(l.to_node_id)) continue;
    edges.push({
      id: `link:${l.id}`,
      type: "link",
      source: l.from_node_id,
      target: l.to_node_id,
      ...sides(at(l.from_node_id), at(l.to_node_id)),
      markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR.relation },
      style: { stroke: EDGE_COLOR.relation, strokeWidth: 2 },
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
  onConnect,
  height = 600,
}: {
  graph: Graph;
  selectedId?: string | null;
  onSelect: (id: string) => void;
  onLinkClick?: (linkId: string) => void;
  /** Drag from one node to another. Entity to entity becomes a relation; anything else becomes an edge. */
  onConnect?: (source: string, target: string) => void;
  height?: number | "fill";
}) {
  const [dragged, setDragged] = useState<Map<string, Point>>(() => new Map());
  const [layoutPass, setLayoutPass] = useState(0);
  const placed = useMemo(() => {
    const merged = layoutPass < 0 ? new Map<string, Point>() : readGraphPositions();
    for (const [id, point] of dragged) merged.set(id, point);
    return merged;
  }, [dragged, layoutPass]);
  const { nodes, edges } = useMemo(() => toFlow(graph, selectedId, placed), [graph, selectedId, placed]);
  const flow = useRef<ReactFlowInstance<FlowNode<Data>, FlowEdge> | null>(null);
  const nodeKey = useMemo(() => graph.nodes.map((node) => node.id).sort().join("\0"), [graph]);
  useEffect(() => {
    const frame = requestAnimationFrame(() => flow.current?.fitView());
    return () => cancelAnimationFrame(frame);
  }, [nodeKey, layoutPass]);
  const relayout = () => {
    clearGraphPositions(graph.nodes.map((node) => node.id));
    setDragged(new Map());
    setLayoutPass((pass) => pass + 1);
  };
  const onNodesChange = (changes: NodeChange<FlowNode<Data>>[]) => {
    setDragged((prev) => {
      let changed = false;
      const next = new Map(prev);
      for (const change of changes) {
        if (change.type === "position" && change.position) {
          next.set(change.id, { x: change.position.x, y: change.position.y });
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  };
  const remember = (id: string, point: Point) => {
    const base = computeLayout(graph).get(id);
    if (base && Math.hypot(base.x - point.x, base.y - point.y) < 8) clearGraphPosition(id);
    else writeGraphPosition(id, point);
  };
  return (
    <div className={onConnect ? "graph-canvas connectable" : "graph-canvas"} style={{ height: height === "fill" ? "100%" : height, border: "1px solid #f0f0f0", borderRadius: 8 }} data-testid="graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesDraggable
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, node) => remember(node.id, node.position)}
        onNodeClick={(_, n) => onSelect(n.id)}
        onEdgeClick={(_, e) => {
          if (e.id.startsWith("link:")) onLinkClick?.(e.id.slice(5));
        }}
        nodesConnectable={Boolean(onConnect)}
        onConnect={(connection) => {
          if (connection.source && connection.target && connection.source !== connection.target) onConnect?.(connection.source, connection.target);
        }}
        onInit={(instance) => {
          flow.current = instance;
          instance.fitView();
        }}
        minZoom={0.2}
      >
        <Panel position="top-left">
          <Button size="small" autoInsertSpace={false} onClick={relayout} title="按当前关系重新排列，并丢掉已拖动的位置">
            重排
          </Button>
        </Panel>
        <Background />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={(n) => KIND_COLOR[(n.type as string) || "entity"]} />
      </ReactFlow>
    </div>
  );
}
