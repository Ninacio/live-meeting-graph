# Live Meeting Knowledge Graph

Turn a meeting transcript into a **branching knowledge graph** — topics,
decisions, and disagreements as nodes; *leads-to / about / contradicts /
resolves* as edges — rendered as an animated force-directed canvas that replays
the meeting chunk by chunk.

Phase 1 is offline/batch: feed in a transcript file, watch the graph grow in
the browser. (Streaming ingestion and multiplayer viewing are later phases —
see [CLAUDE.md](CLAUDE.md) for the data model and roadmap.)

## Quick start (no API key needed)

```bash
# 1. Backend: install deps and generate a graph from a sample transcript
cd backend
pip install -r requirements.txt
python cli.py samples/product_meeting.txt        # writes ../frontend/public/graph.json

# 2. Frontend: render it
cd ../frontend
npm install
npm run dev                                       # open http://localhost:5173
```

The page replays the meeting: nodes appear in the order the conversation
produced them. Blue rounded nodes are **topics**, green **✓ decisions**, amber
**⚡ disagreements** (dashed red edges mark contradictions, dotted blue edges
mark resolutions). Hover a node for its summary and speakers.

Without an `ANTHROPIC_API_KEY`, extraction uses a deterministic rule-based
mock (cue phrases like "let's talk about…", "we agreed to…", "I disagree").
With a key set, extraction uses the Claude API automatically:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python cli.py samples/product_meeting.txt --live
```

## Optional: run the API server

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

- `POST /api/ingest` — `{"text": "...", "format": "text|json", "title": "...", "mode": "auto|live|mock"}` → graph JSON
- `POST /api/ingest/file` — multipart upload of a `.txt`/`.json` transcript
- `GET /api/graph` — latest graph (the Vite dev server proxies `/api` here; the
  frontend falls back to the static `graph.json` when the server isn't running)

Graphs are persisted to SQLite (`meeting_graph.db`) by default; set
`DATABASE_URL=postgresql://user:pass@host/db` to use Postgres with the same
schema (tables: `meetings`, `nodes`, `edges`).

## Transcript formats

Plain text (timestamps optional):

```
[00:05] Maya: Let's start with the Q3 launch timeline.
[00:18] Dev: Engineering is tracking toward late July.
```

JSON:

```json
{"title": "Roadmap sync", "entries": [{"t": 4, "speaker": "Jo", "text": "..."}]}
```

## Extraction: cost vs. accuracy

Extraction is one Claude API call per chunk (~6 speaker turns / ~60s of
meeting). Model is `claude-opus-4-8` by default, override with
`MEETING_GRAPH_MODEL`:

| Extractor | Cost (per 1M tokens in/out) | Quality | When to use |
|---|---|---|---|
| `claude-opus-4-8` (default) | $5 / $25 | Best — reliably catches implicit decisions and subtle disagreements | Default; a 1-hour meeting (~60 chunks) costs roughly $0.30–0.80 |
| `claude-sonnet-5` | $3 / $15 (intro $2 / $10) | Near-Opus on structured extraction | High-volume use |
| `claude-haiku-4-5` | $1 / $5 | Noticeably weaker on disagreements/implicit decisions | Cheap iteration on pipeline mechanics |
| Rule-based mock | free | Cue phrases only — misses anything unstated | Demos, tests, CI |

A local model (spaCy NER + heuristics) was considered and deferred: topics are
somewhat tractable locally, but decision and disagreement detection are
discourse-level tasks where small local models do poorly. Revisit only if API
cost or latency becomes a real constraint (Phase 2 streaming may justify a
cheap local pre-filter that skips chunks with no decision-like content).

## Eval

```bash
cd backend
python eval/run_eval.py --mock    # or --live with an API key
```

Compares extracted topics/decisions against hand labels in `eval/labels/`
(greedy fuzzy match: topics ≥ 0.75, decisions ≥ 0.60 similarity) and prints
precision/recall/F1 per transcript and aggregate.

Current scores on the three bundled samples: mock extractor **1.00 / 1.00 /
1.00** (topics and decisions). Take that number with salt — the samples were
authored alongside the mock's cue list, so it's a ceiling, not an estimate.
The eval exists to measure the **live** extractor and future, unseen
transcripts; add real-world transcripts to `samples/` + `eval/labels/` to make
it meaningful.

## Tests

```bash
cd backend
python -m pytest
```

Covers transcript parsing, chunking boundaries, topic dedup/fuzzy merging,
cross-chunk linking, and disagreement→resolution edge construction.

## Repo layout

```
backend/
  app/            ingest → extract → graph_builder → db → FastAPI
  cli.py          transcript file → frontend/public/graph.json
  samples/        3 sample transcripts (2 .txt meetings, 1 .json)
  eval/           labels + precision/recall script
  tests/          pytest suite
frontend/         Vite + React + TS, @xyflow/react + d3-force renderer
CLAUDE.md         extraction schema, graph model, phase roadmap
```
