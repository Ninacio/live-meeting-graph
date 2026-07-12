from app.ingest import chunk_transcript, parse_json_transcript, parse_text_transcript


SAMPLE_TEXT = """
[00:05] Maya: Let's start with the launch timeline.
[00:18] Dev: Tracking toward late July.
Dev continues on a wrapped line without a speaker prefix.
[00:34] Priya: Migration is ready.
"""


def test_parse_text_with_timestamps():
    t = parse_text_transcript(SAMPLE_TEXT, title="test")
    assert len(t.entries) == 3
    assert t.entries[0].speaker == "Maya"
    assert t.entries[0].t == 5
    assert t.entries[1].t == 18
    # Wrapped line folds into the previous utterance.
    assert "wrapped line" in t.entries[1].text


def test_parse_text_without_timestamps():
    t = parse_text_transcript("Alice: hello\nBob: hi there")
    assert len(t.entries) == 2
    assert t.entries[0].t is None
    assert t.entries[1].speaker == "Bob"


def test_parse_json_transcript():
    raw = '{"title": "m", "entries": [{"t": 1.5, "speaker": "A", "text": "x"}]}'
    t = parse_json_transcript(raw)
    assert t.title == "m"
    assert t.entries[0].t == 1.5


def _mk(n, speakers=("A", "B"), spacing=10.0):
    lines = []
    for i in range(n):
        lines.append(f"[{int(i * spacing) // 60:02d}:{int(i * spacing) % 60:02d}] {speakers[i % len(speakers)]}: utterance {i}")
    return parse_text_transcript("\n".join(lines))


def test_chunk_closes_on_turn_count():
    t = _mk(14, spacing=1.0)  # time never exceeds the window
    chunks = chunk_transcript(t, max_turns=6, max_seconds=600)
    assert len(chunks) == 3
    assert [c.index for c in chunks] == [0, 1, 2]
    assert sum(len(c.utterances) for c in chunks) == 14
    # Chunks close on speaker-turn boundaries.
    for c in chunks[:-1]:
        assert len(c.utterances) >= 6


def test_chunk_closes_on_time_window():
    t = _mk(10, spacing=45.0)  # 45s apart -> exceeds 60s window every 2 utterances
    chunks = chunk_transcript(t, max_turns=50, max_seconds=60)
    assert len(chunks) > 1
    for c in chunks:
        assert c.speakers  # speakers recorded
        assert c.chunk_id.startswith("c")


def test_chunk_never_splits_same_speaker_run():
    # 8 consecutive utterances by the same speaker must stay together.
    lines = [f"A: line {i}" for i in range(8)] + ["B: reply"]
    t = parse_text_transcript("\n".join(lines))
    chunks = chunk_transcript(t, max_turns=4, max_seconds=60)
    assert len(chunks[0].utterances) == 8
    assert chunks[0].speakers == ["A"]
