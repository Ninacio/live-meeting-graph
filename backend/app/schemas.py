"""Pydantic models shared across the pipeline.

Three layers:
  1. Transcript / chunk models (ingest)
  2. Extraction output models (what the LLM returns per chunk)
  3. Graph models (what the builder produces and the frontend renders)
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Transcript / chunks
# ---------------------------------------------------------------------------

class Utterance(BaseModel):
    t: Optional[float] = None  # seconds from meeting start, if known
    speaker: str
    text: str


class Transcript(BaseModel):
    title: str = "Untitled meeting"
    entries: list[Utterance]


class Chunk(BaseModel):
    chunk_id: str
    index: int
    start: Optional[float] = None
    end: Optional[float] = None
    speakers: list[str]
    utterances: list[Utterance]

    def as_text(self) -> str:
        return "\n".join(f"{u.speaker}: {u.text}" for u in self.utterances)


# ---------------------------------------------------------------------------
# 2. Extraction output (per chunk)
# ---------------------------------------------------------------------------

class TopicMention(BaseModel):
    name: str = Field(description="Short canonical topic name, 2-5 words. Reuse a known topic name verbatim if this is the same topic.")
    summary: str = Field(description="One sentence: what was said about this topic in this chunk.")
    related_to: list[str] = Field(
        default_factory=list,
        description="Names of topics (from the known-topics list or this chunk) that this topic follows from or elaborates on.",
    )


class Decision(BaseModel):
    statement: str = Field(description="The decision as a single declarative sentence.")
    topic: str = Field(description="Name of the topic this decision belongs to.")
    speakers: list[str] = Field(default_factory=list, description="Who made or endorsed the decision.")


class Disagreement(BaseModel):
    topic: str = Field(description="Name of the topic being disputed.")
    position_a: str
    speaker_a: str
    position_b: str
    speaker_b: str
    resolved: bool = Field(default=False, description="True if the disagreement was settled within this chunk.")
    resolution: Optional[str] = Field(default=None, description="How it was resolved, if resolved.")


class ChunkExtraction(BaseModel):
    topics: list[TopicMention] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. Graph
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    topic = "topic"
    decision = "decision"
    disagreement = "disagreement"


class EdgeType(str, Enum):
    leads_to = "leads_to"      # topic -> topic
    about = "about"            # decision -> topic
    contradicts = "contradicts"  # disagreement -> topic
    resolves = "resolves"      # decision -> disagreement


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    summary: str = ""
    speakers: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    first_seen: int = 0  # index of the chunk where the node first appeared


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: EdgeType
    chunk_id: str


class Graph(BaseModel):
    title: str = "Untitled meeting"
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    chunk_count: int = 0
