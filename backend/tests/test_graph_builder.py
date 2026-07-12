from app.graph_builder import GraphBuilder
from app.schemas import (
    Chunk,
    ChunkExtraction,
    Decision,
    Disagreement,
    TopicMention,
    Utterance,
)


def _chunk(index: int) -> Chunk:
    return Chunk(
        chunk_id=f"c{index}",
        index=index,
        speakers=["A", "B"],
        utterances=[Utterance(speaker="A", text="...")],
    )


def test_topic_dedup_exact_and_fuzzy():
    b = GraphBuilder()
    b.add_chunk(
        _chunk(0),
        ChunkExtraction(topics=[TopicMention(name="Pricing Tiers", summary="s1")]),
    )
    # Same topic, different casing/punctuation and a near-duplicate name.
    b.add_chunk(
        _chunk(1),
        ChunkExtraction(topics=[TopicMention(name="pricing tiers!", summary="s2")]),
    )
    b.add_chunk(
        _chunk(2),
        ChunkExtraction(topics=[TopicMention(name="The Pricing Tier", summary="s3")]),
    )
    topics = [n for n in b.graph.nodes if n.type.value == "topic"]
    assert len(topics) == 1
    assert set(topics[0].chunk_ids) == {"c0", "c1", "c2"}


def test_later_chunk_links_to_earlier_topic():
    b = GraphBuilder()
    b.add_chunk(
        _chunk(0),
        ChunkExtraction(topics=[TopicMention(name="Launch Timeline", summary="s")]),
    )
    b.add_chunk(
        _chunk(1),
        ChunkExtraction(
            topics=[
                TopicMention(
                    name="Payment Integration",
                    summary="s",
                    related_to=["Launch Timeline"],
                )
            ]
        ),
    )
    edges = b.graph.edges
    assert len(edges) == 1
    assert edges[0].type.value == "leads_to"
    topic_ids = {n.label: n.id for n in b.graph.nodes}
    assert edges[0].source == topic_ids["Launch Timeline"]
    assert edges[0].target == topic_ids["Payment Integration"]


def test_decision_attaches_to_existing_topic():
    b = GraphBuilder()
    b.add_chunk(
        _chunk(0),
        ChunkExtraction(topics=[TopicMention(name="Retry Policy", summary="s")]),
    )
    b.add_chunk(
        _chunk(1),
        ChunkExtraction(
            decisions=[Decision(statement="Use exponential backoff", topic="retry policy", speakers=["A"])]
        ),
    )
    topics = [n for n in b.graph.nodes if n.type.value == "topic"]
    decisions = [n for n in b.graph.nodes if n.type.value == "decision"]
    assert len(topics) == 1  # decision resolved to the existing node, no duplicate
    assert len(decisions) == 1
    about = [e for e in b.graph.edges if e.type.value == "about"]
    assert len(about) == 1
    assert about[0].source == decisions[0].id
    assert about[0].target == topics[0].id


def test_disagreement_and_resolving_decision():
    b = GraphBuilder()
    b.add_chunk(
        _chunk(0),
        ChunkExtraction(
            topics=[TopicMention(name="Rewrite Strategy", summary="s")],
            disagreements=[
                Disagreement(
                    topic="Rewrite Strategy",
                    position_a="Full rewrite",
                    speaker_a="A",
                    position_b="Incremental migration",
                    speaker_b="B",
                    resolved=True,
                    resolution="Timeboxed rewrite",
                )
            ],
            decisions=[Decision(statement="Timeboxed six-month rewrite", topic="Rewrite Strategy")],
        ),
    )
    edge_types = sorted(e.type.value for e in b.graph.edges)
    assert edge_types == ["about", "contradicts", "resolves"]
    resolves = next(e for e in b.graph.edges if e.type.value == "resolves")
    decision = next(n for n in b.graph.nodes if n.type.value == "decision")
    disagreement = next(n for n in b.graph.nodes if n.type.value == "disagreement")
    assert resolves.source == decision.id
    assert resolves.target == disagreement.id


def test_no_duplicate_edges():
    b = GraphBuilder()
    for i in range(2):
        b.add_chunk(
            _chunk(i),
            ChunkExtraction(
                topics=[
                    TopicMention(name="Launch Timeline", summary="s"),
                    TopicMention(name="Vendor Risk", summary="s", related_to=["Launch Timeline"]),
                ]
            ),
        )
    leads = [e for e in b.graph.edges if e.type.value == "leads_to"]
    assert len(leads) == 1
