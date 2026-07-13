import { useEffect, useRef, useState } from "react";
import GraphView from "./GraphView";
import type { MeetingGraph } from "./types";

async function loadGraph(): Promise<MeetingGraph> {
  // Prefer the backend API; fall back to the static file the CLI writes.
  try {
    const api = await fetch("/api/graph");
    if (api.ok) return api.json();
  } catch {
    /* backend not running - fine */
  }
  const stat = await fetch("/graph.json");
  if (!stat.ok) {
    throw new Error(
      "No graph found. Run `python cli.py samples/product_meeting.txt` in backend/, or start the FastAPI server and POST /api/ingest.",
    );
  }
  return stat.json();
}

const LEGEND: Array<[string, string]> = [
  ["#3b82f6", "topic"],
  ["#16a34a", "✓ decision"],
  ["#d97706", "⚡ disagreement"],
];

export default function App() {
  const [graph, setGraph] = useState<MeetingGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visibleChunk, setVisibleChunk] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    loadGraph()
      .then((g) => {
        setGraph(g);
        setVisibleChunk(0);
        setPlaying(true); // replay the meeting on load - the graph grows in
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    if (!playing || !graph) return;
    if (visibleChunk >= graph.chunk_count - 1) {
      setPlaying(false);
      return;
    }
    timerRef.current = window.setTimeout(() => {
      setVisibleChunk((c) => c + 1);
    }, 1400 / speed);
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [playing, visibleChunk, graph, speed]);

  const replay = () => {
    setVisibleChunk(0);
    setPlaying(true);
  };
  const showAll = () => {
    if (graph) setVisibleChunk(graph.chunk_count - 1);
    setPlaying(false);
  };

  if (error) {
    return (
      <div style={{ padding: 40, maxWidth: 640, margin: "0 auto", color: "#334155" }}>
        <h2>Live Meeting Knowledge Graph</h2>
        <p style={{ background: "#fef2f2", border: "1px solid #fecaca", padding: 16, borderRadius: 8 }}>
          {error}
        </p>
      </div>
    );
  }
  if (!graph) return <div style={{ padding: 40 }}>Loading…</div>;

  const shownNodes = graph.nodes.filter((n) => n.first_seen <= visibleChunk).length;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "10px 16px",
          borderBottom: "1px solid #e2e8f0",
          background: "#f8fafc",
          flexWrap: "wrap",
        }}
      >
        <strong style={{ fontSize: 15 }}>{graph.title}</strong>
        <span style={{ color: "#64748b", fontSize: 13 }}>
          chunk {visibleChunk + 1}/{graph.chunk_count} · {shownNodes}/{graph.nodes.length} nodes ·{" "}
          {graph.edges.length} edges
        </span>
        <button onClick={replay} style={btnStyle}>
          ▶ Replay
        </button>
        <button onClick={() => setPlaying((p) => !p)} style={btnStyle} disabled={visibleChunk >= graph.chunk_count - 1}>
          {playing ? "⏸ Pause" : "⏵ Resume"}
        </button>
        <button onClick={showAll} style={btnStyle}>
          ⏭ Show all
        </button>
        <label style={{ fontSize: 13, color: "#475569" }}>
          speed{" "}
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            <option value={0.5}>0.5×</option>
            <option value={1}>1×</option>
            <option value={2}>2×</option>
            <option value={4}>4×</option>
          </select>
        </label>
        <span style={{ marginLeft: "auto", display: "flex", gap: 12, fontSize: 12, color: "#475569" }}>
          {LEGEND.map(([color, label]) => (
            <span key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 3,
                  background: color,
                  display: "inline-block",
                }}
              />
              {label}
            </span>
          ))}
        </span>
      </header>
      <div style={{ flex: 1 }}>
        <GraphView graph={graph} visibleChunk={visibleChunk} />
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: 6,
  border: "1px solid #cbd5e1",
  background: "white",
  cursor: "pointer",
  fontSize: 13,
};
