"""Run the full pipeline on a transcript file and write graph JSON.

Usage (from backend/):
    python cli.py samples/product_meeting.txt
    python cli.py samples/podcast_roadmap.json --live -o ../frontend/public/graph.json

By default the output goes to ../frontend/public/graph.json so the frontend
picks it up without a running backend. Extraction uses the Claude API when
ANTHROPIC_API_KEY is set (or --live), otherwise the rule-based mock.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from app.db import save_graph
from app.extract import get_extractor
from app.graph_builder import GraphBuilder
from app.ingest import chunk_transcript, load_transcript

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "graph.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcript -> knowledge graph JSON")
    parser.add_argument("transcript", help="Path to a .txt or .json transcript")
    parser.add_argument("-o", "--out", default=str(DEFAULT_OUT), help="Output path for graph JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Force Claude API extraction")
    mode.add_argument("--mock", action="store_true", help="Force rule-based mock extraction")
    parser.add_argument("--no-db", action="store_true", help="Skip persisting to the database")
    args = parser.parse_args()

    transcript = load_transcript(args.transcript)
    chunks = chunk_transcript(transcript)
    extractor = get_extractor(mode="live" if args.live else "mock" if args.mock else "auto")
    extractor_name = type(extractor).__name__
    print(f"Parsed {len(transcript.entries)} utterances -> {len(chunks)} chunks ({extractor_name})")

    builder = GraphBuilder(title=transcript.title)
    t0 = time.time()
    for chunk in chunks:
        known = [n.label for n in builder.graph.nodes if n.type.value == "topic"]
        extraction = extractor.extract(chunk, known)
        builder.add_chunk(chunk, extraction)
        print(
            f"  {chunk.chunk_id}: +{len(extraction.topics)} topics, "
            f"+{len(extraction.decisions)} decisions, +{len(extraction.disagreements)} disagreements"
        )
    graph = builder.graph

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(graph.model_dump_json(indent=2), encoding="utf-8")

    if not args.no_db:
        meeting_id = save_graph(graph)
        print(f"Saved to DB as meeting #{meeting_id}")

    by_type: dict[str, int] = {}
    for n in graph.nodes:
        by_type[n.type.value] = by_type.get(n.type.value, 0) + 1
    print(
        f"Done in {time.time() - t0:.1f}s: {len(graph.nodes)} nodes {by_type}, "
        f"{len(graph.edges)} edges -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
