"""FastAPI app: ingest a transcript, serve the resulting graph.

Run from backend/:  uvicorn app.main:app --reload --port 8000
The Vite dev server proxies /api to this port.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .extract import get_extractor
from .graph_builder import GraphBuilder
from .ingest import chunk_transcript, parse_json_transcript, parse_text_transcript
from .schemas import Graph

app = FastAPI(title="Live Meeting Knowledge Graph")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_current_graph: Graph | None = None


class IngestRequest(BaseModel):
    text: str
    format: str = "text"  # "text" | "json"
    title: str = "Untitled meeting"
    mode: str = "auto"  # "auto" | "live" | "mock"


def _run_pipeline(text: str, fmt: str, title: str, mode: str) -> Graph:
    transcript = (
        parse_json_transcript(text) if fmt == "json" else parse_text_transcript(text, title=title)
    )
    if not transcript.entries:
        raise HTTPException(status_code=400, detail="Transcript contained no parseable utterances")
    chunks = chunk_transcript(transcript)
    extractor = get_extractor(mode=mode)
    builder = GraphBuilder(title=transcript.title)
    for chunk in chunks:
        # Feed the topics known so far into each extraction call.
        known = [n.label for n in builder.graph.nodes if n.type.value == "topic"]
        extraction = extractor.extract(chunk, known)
        builder.add_chunk(chunk, extraction)
    return builder.graph


@app.post("/api/ingest")
def ingest(req: IngestRequest) -> Graph:
    global _current_graph
    graph = _run_pipeline(req.text, req.format, req.title, req.mode)
    _current_graph = graph
    db.save_graph(graph)
    return graph


@app.post("/api/ingest/file")
async def ingest_file(file: UploadFile, mode: str = "auto") -> Graph:
    global _current_graph
    raw = (await file.read()).decode("utf-8")
    fmt = "json" if (file.filename or "").endswith(".json") else "text"
    title = (file.filename or "meeting").rsplit(".", 1)[0].replace("_", " ")
    graph = _run_pipeline(raw, fmt, title, mode)
    _current_graph = graph
    db.save_graph(graph)
    return graph


@app.get("/api/graph")
def get_graph() -> Graph:
    if _current_graph is not None:
        return _current_graph
    stored = db.load_latest_graph()
    if stored is None:
        raise HTTPException(status_code=404, detail="No graph yet — POST /api/ingest first")
    return stored


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
