import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationNodeDatum,
} from "d3-force";
import type { EdgeType, GraphNode, MeetingGraph, NodeType } from "./types";

interface SimNode extends SimulationNodeDatum {
  id: string;
}

const NODE_STYLE: Record<NodeType, React.CSSProperties> = {
  topic: {
    background: "#dbeafe",
    border: "2px solid #3b82f6",
    color: "#1e3a8a",
    borderRadius: 12,
    fontWeight: 600,
  },
  decision: {
    background: "#dcfce7",
    border: "2px solid #16a34a",
    color: "#14532d",
    borderRadius: 4,
  },
  disagreement: {
    background: "#fef3c7",
    border: "2px dashed #d97706",
    color: "#78350f",
    borderRadius: 4,
  },
};

const NODE_PREFIX: Record<NodeType, string> = {
  topic: "",
  decision: "✓ ",
  disagreement: "⚡ ",
};

const EDGE_STYLE: Record<EdgeType, Partial<Edge>> = {
  leads_to: { style: { stroke: "#94a3b8", strokeWidth: 2 } },
  about: { style: { stroke: "#16a34a", strokeWidth: 2 } },
  contradicts: {
    style: { stroke: "#dc2626", strokeWidth: 2, strokeDasharray: "6 4" },
    animated: true,
    label: "contradicts",
  },
  resolves: {
    style: { stroke: "#2563eb", strokeWidth: 2, strokeDasharray: "2 4" },
    label: "resolves",
  },
};

function toRfNode(n: GraphNode, x: number, y: number): Node {
  return {
    id: n.id,
    position: { x, y },
    // Explicit dimensions + handle positions (SSR-style) so edges render
    // before client-side measurement completes.
    width: 190,
    height: 44,
    handles: [
      { type: "source", position: Position.Bottom, x: 95, y: 44, width: 6, height: 6 },
      { type: "target", position: Position.Top, x: 95, y: 0, width: 6, height: 6 },
    ],
    data: {
      label: (
        <div title={n.summary + (n.speakers.length ? `\n- ${n.speakers.join(", ")}` : "")}>
          {NODE_PREFIX[n.type]}
          {n.label.length > 46 ? n.label.slice(0, 44) + "…" : n.label}
        </div>
      ),
    },
    style: { ...NODE_STYLE[n.type], padding: 8, width: 190, fontSize: 12, transition: "transform 500ms ease" },
  };
}

function InnerGraphView({ graph, visibleChunk }: { graph: MeetingGraph; visibleChunk: number }) {
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());
  const { fitView } = useReactFlow();

  const chunkOf = (chunkId: string) => parseInt(chunkId.slice(1), 10);

  const visibleNodes = useMemo(
    () => graph.nodes.filter((n) => n.first_seen <= visibleChunk),
    [graph, visibleChunk],
  );
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () =>
      graph.edges.filter(
        (e) =>
          chunkOf(e.chunk_id) <= visibleChunk &&
          visibleIds.has(e.source) &&
          visibleIds.has(e.target),
      ),
    [graph, visibleChunk, visibleIds],
  );

  useEffect(() => {
    const simNodes = simNodesRef.current;

    // Drop nodes that are no longer visible (replay restarted).
    for (const id of Array.from(simNodes.keys())) {
      if (!visibleIds.has(id)) simNodes.delete(id);
    }

    // Add newly visible nodes, seeded near a neighbor when one exists.
    for (const n of visibleNodes) {
      if (simNodes.has(n.id)) continue;
      const neighborEdge = visibleEdges.find((e) => e.source === n.id || e.target === n.id);
      const neighborId =
        neighborEdge && (neighborEdge.source === n.id ? neighborEdge.target : neighborEdge.source);
      const anchor = neighborId ? simNodes.get(neighborId) : undefined;
      simNodes.set(n.id, {
        id: n.id,
        x: (anchor?.x ?? 0) + (Math.random() - 0.5) * 160,
        y: (anchor?.y ?? 0) + (Math.random() - 0.5) * 160,
      });
    }

    const nodes = Array.from(simNodes.values());
    const links = visibleEdges.map((e) => ({ source: e.source, target: e.target }));

    // Run the simulation synchronously: deterministic, cheap (one layout per
    // chunk), and independent of requestAnimationFrame throttling. Node
    // movement between layouts is animated via a CSS transition instead.
    const sim = forceSimulation<SimNode>(nodes)
      .force("charge", forceManyBody().strength(-420))
      .force("link", forceLink(links).id((d: any) => d.id).distance(150).strength(0.6))
      .force("center", forceCenter(0, 0))
      .force("collide", forceCollide(95))
      .stop();
    sim.tick(220);
    simRef.current = sim;

    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    setRfNodes(nodes.map((sn) => toRfNode(byId.get(sn.id)!, sn.x ?? 0, sn.y ?? 0)));

    const fitTimer = window.setTimeout(
      () => fitView({ padding: 0.15, duration: 300 }),
      60,
    );
    return () => window.clearTimeout(fitTimer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, visibleChunk]);

  const rfEdges: Edge[] = visibleEdges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    markerEnd: { type: MarkerType.ArrowClosed },
    labelStyle: { fontSize: 10, fill: "#475569" },
    ...EDGE_STYLE[e.type],
  }));

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      proOptions={{ hideAttribution: true }}
      minZoom={0.2}
    >
      <Background gap={24} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export default function GraphView(props: { graph: MeetingGraph; visibleChunk: number }) {
  return (
    <ReactFlowProvider>
      <InnerGraphView {...props} />
    </ReactFlowProvider>
  );
}
