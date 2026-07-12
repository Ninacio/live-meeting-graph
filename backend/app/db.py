"""Persistence: SQLAlchemy schema for topics, decisions, disagreements, edges.

SQLite by default (zero setup); set DATABASE_URL=postgresql://... to run the
identical schema on Postgres. If graph queries outgrow SQL (multi-hop
traversals, pathfinding across meetings), Neo4j is the planned swap — see
CLAUDE.md.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base

from .schemas import Graph

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///meeting_graph.db")

Base = declarative_base()


class MeetingRow(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True)
    title = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    chunk_count = Column(Integer, default=0)


class NodeRow(Base):
    __tablename__ = "nodes"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False, index=True)
    node_id = Column(String(32), nullable=False)  # graph-local id, e.g. "t1"
    type = Column(String(16), nullable=False)     # topic | decision | disagreement
    label = Column(String(256), nullable=False)
    summary = Column(Text, default="")
    speakers = Column(Text, default="[]")         # JSON array
    chunk_ids = Column(Text, default="[]")        # JSON array
    first_seen = Column(Integer, default=0)


class EdgeRow(Base):
    __tablename__ = "edges"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False, index=True)
    edge_id = Column(String(32), nullable=False)
    source = Column(String(32), nullable=False)
    target = Column(String(32), nullable=False)
    type = Column(String(16), nullable=False)     # leads_to | about | contradicts | resolves
    chunk_id = Column(String(32), nullable=False)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL)
        Base.metadata.create_all(_engine)
    return _engine


def save_graph(graph: Graph) -> int:
    """Persist a graph; returns the meeting id."""
    with Session(get_engine()) as session:
        meeting = MeetingRow(title=graph.title, chunk_count=graph.chunk_count)
        session.add(meeting)
        session.flush()
        for n in graph.nodes:
            session.add(
                NodeRow(
                    meeting_id=meeting.id,
                    node_id=n.id,
                    type=n.type.value,
                    label=n.label,
                    summary=n.summary,
                    speakers=json.dumps(n.speakers),
                    chunk_ids=json.dumps(n.chunk_ids),
                    first_seen=n.first_seen,
                )
            )
        for e in graph.edges:
            session.add(
                EdgeRow(
                    meeting_id=meeting.id,
                    edge_id=e.id,
                    source=e.source,
                    target=e.target,
                    type=e.type.value,
                    chunk_id=e.chunk_id,
                )
            )
        session.commit()
        return meeting.id


def load_latest_graph() -> Graph | None:
    with Session(get_engine()) as session:
        meeting = (
            session.query(MeetingRow).order_by(MeetingRow.id.desc()).first()
        )
        if meeting is None:
            return None
        nodes = session.query(NodeRow).filter_by(meeting_id=meeting.id).all()
        edges = session.query(EdgeRow).filter_by(meeting_id=meeting.id).all()
        return Graph(
            title=meeting.title,
            chunk_count=meeting.chunk_count,
            nodes=[
                {
                    "id": n.node_id,
                    "type": n.type,
                    "label": n.label,
                    "summary": n.summary,
                    "speakers": json.loads(n.speakers),
                    "chunk_ids": json.loads(n.chunk_ids),
                    "first_seen": n.first_seen,
                }
                for n in nodes
            ],
            edges=[
                {
                    "id": e.edge_id,
                    "source": e.source,
                    "target": e.target,
                    "type": e.type,
                    "chunk_id": e.chunk_id,
                }
                for e in edges
            ],
        )
