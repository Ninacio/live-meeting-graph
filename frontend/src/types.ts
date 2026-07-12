// Mirrors backend/app/schemas.py (Graph / GraphNode / GraphEdge).

export type NodeType = "topic" | "decision" | "disagreement";
export type EdgeType = "leads_to" | "about" | "contradicts" | "resolves";

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  summary: string;
  speakers: string[];
  chunk_ids: string[];
  first_seen: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  chunk_id: string;
}

export interface MeetingGraph {
  title: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  chunk_count: number;
}
