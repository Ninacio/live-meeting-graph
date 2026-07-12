"""Incremental graph construction from a sequence of chunk extractions.

The builder is stateful: feed it one ``ChunkExtraction`` at a time (in chunk
order) and it grows the graph, resolving topic mentions against nodes created
by earlier chunks so a later chunk links to or contradicts an existing node
instead of always creating a new one.

Topic resolution = exact match on the normalized name, falling back to fuzzy
match (SequenceMatcher ratio >= 0.85). A resolved mention merges into the
existing node (appends chunk_id, keeps the earliest summary).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .schemas import (
    Chunk,
    ChunkExtraction,
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeType,
)

FUZZY_THRESHOLD = 0.85


def normalize(name: str) -> str:
    norm = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    return re.sub(r"^(?:the|a|an)\s+", "", norm)


class GraphBuilder:
    def __init__(self, title: str = "Untitled meeting"):
        self.graph = Graph(title=title)
        self._topic_index: dict[str, str] = {}  # normalized name -> node id
        self._counters: dict[str, int] = {"t": 0, "d": 0, "x": 0, "e": 0}
        self._prev_chunk_topic: str | None = None  # node id of last topic seen

    # -- id helpers ---------------------------------------------------------

    def _next_id(self, kind: str) -> str:
        self._counters[kind] += 1
        return f"{kind}{self._counters[kind]}"

    # -- topic resolution ---------------------------------------------------

    def resolve_topic(self, name: str) -> str | None:
        """Return the node id of an existing topic matching ``name``, if any."""
        norm = normalize(name)
        if not norm:
            return None
        if norm in self._topic_index:
            return self._topic_index[norm]
        best_id, best_score = None, 0.0
        for existing_norm, node_id in self._topic_index.items():
            score = SequenceMatcher(None, norm, existing_norm).ratio()
            if score > best_score:
                best_id, best_score = node_id, score
        return best_id if best_score >= FUZZY_THRESHOLD else None

    def _get_or_create_topic(
        self, name: str, summary: str, chunk: Chunk, speakers: list[str] | None = None
    ) -> str:
        existing = self.resolve_topic(name)
        if existing:
            node = self._node(existing)
            if chunk.chunk_id not in node.chunk_ids:
                node.chunk_ids.append(chunk.chunk_id)
            for s in speakers or []:
                if s not in node.speakers:
                    node.speakers.append(s)
            return existing
        node_id = self._next_id("t")
        self.graph.nodes.append(
            GraphNode(
                id=node_id,
                type=NodeType.topic,
                label=name.strip(),
                summary=summary,
                speakers=speakers or list(chunk.speakers),
                chunk_ids=[chunk.chunk_id],
                first_seen=chunk.index,
            )
        )
        self._topic_index[normalize(name)] = node_id
        return node_id

    def _node(self, node_id: str) -> GraphNode:
        return next(n for n in self.graph.nodes if n.id == node_id)

    def _add_edge(self, source: str, target: str, etype: EdgeType, chunk: Chunk) -> None:
        if source == target:
            return
        if any(
            e.source == source and e.target == target and e.type == etype
            for e in self.graph.edges
        ):
            return
        self.graph.edges.append(
            GraphEdge(
                id=self._next_id("e"),
                source=source,
                target=target,
                type=etype,
                chunk_id=chunk.chunk_id,
            )
        )

    # -- main entry point ---------------------------------------------------

    def add_chunk(self, chunk: Chunk, extraction: ChunkExtraction) -> None:
        first_topic_this_chunk: str | None = None

        for mention in extraction.topics:
            was_known = self.resolve_topic(mention.name) is not None
            node_id = self._get_or_create_topic(mention.name, mention.summary, chunk)

            for rel in mention.related_to:
                rel_id = self.resolve_topic(rel)
                if rel_id and rel_id != node_id:
                    self._add_edge(rel_id, node_id, EdgeType.leads_to, chunk)

            # Conversational flow: link the previous chunk's topic to the first
            # genuinely new topic of this chunk if extraction gave no link.
            if (
                first_topic_this_chunk is None
                and not was_known
                and not mention.related_to
                and self._prev_chunk_topic
                and self._prev_chunk_topic != node_id
            ):
                self._add_edge(self._prev_chunk_topic, node_id, EdgeType.leads_to, chunk)
            if first_topic_this_chunk is None:
                first_topic_this_chunk = node_id
            self._prev_chunk_topic = node_id

        # Disagreements before decisions, so a decision in the same chunk can
        # resolve a disagreement raised moments earlier.
        disagreement_ids: list[tuple[str, str]] = []  # (node_id, topic_node_id)
        for dis in extraction.disagreements:
            topic_id = self._get_or_create_topic(
                dis.topic, f"Disputed: {dis.position_a[:80]}", chunk,
                speakers=[dis.speaker_a, dis.speaker_b],
            )
            node_id = self._next_id("x")
            label = f"{dis.speaker_a} vs {dis.speaker_b}"
            summary = f"{dis.speaker_a}: {dis.position_a} — {dis.speaker_b}: {dis.position_b}"
            if dis.resolved and dis.resolution:
                summary += f" (resolved: {dis.resolution})"
            self.graph.nodes.append(
                GraphNode(
                    id=node_id,
                    type=NodeType.disagreement,
                    label=label,
                    summary=summary,
                    speakers=[dis.speaker_a, dis.speaker_b],
                    chunk_ids=[chunk.chunk_id],
                    first_seen=chunk.index,
                )
            )
            self._add_edge(node_id, topic_id, EdgeType.contradicts, chunk)
            disagreement_ids.append((node_id, topic_id))

        for dec in extraction.decisions:
            topic_id = self._get_or_create_topic(
                dec.topic, dec.statement, chunk, speakers=dec.speakers
            )
            node_id = self._next_id("d")
            self.graph.nodes.append(
                GraphNode(
                    id=node_id,
                    type=NodeType.decision,
                    label=dec.statement[:80],
                    summary=dec.statement,
                    speakers=dec.speakers,
                    chunk_ids=[chunk.chunk_id],
                    first_seen=chunk.index,
                )
            )
            self._add_edge(node_id, topic_id, EdgeType.about, chunk)
            # A decision on a disputed topic resolves that topic's open disagreement.
            for dis_id, dis_topic_id in disagreement_ids:
                if dis_topic_id == topic_id:
                    self._add_edge(node_id, dis_id, EdgeType.resolves, chunk)

        self.graph.chunk_count = max(self.graph.chunk_count, chunk.index + 1)


def build_graph(chunks, extractions, title: str = "Untitled meeting") -> Graph:
    builder = GraphBuilder(title=title)
    for chunk, extraction in zip(chunks, extractions):
        builder.add_chunk(chunk, extraction)
    return builder.graph
