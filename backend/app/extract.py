"""Per-chunk extraction of topics, decisions, and disagreements.

Two extractors share one interface (``chunk, known_topics -> ChunkExtraction``):

  * ``LLMExtractor`` — calls the Claude API with structured outputs
    (``client.messages.parse`` validated against the ``ChunkExtraction``
    Pydantic schema). The prompt includes the topic names already in the
    graph so the model reuses existing names instead of minting
    near-duplicates — this is what lets later chunks link to or contradict
    earlier nodes.
  * ``MockExtractor`` — deterministic cue-phrase rules, so the whole
    pipeline (and the frontend demo) runs without an API key. Expect far
    lower recall than the LLM path.

``get_extractor()`` picks the LLM path when ANTHROPIC_API_KEY is set,
otherwise the mock. Override with mode="mock" / mode="live".
"""
from __future__ import annotations

import os
import re

from .schemas import Chunk, ChunkExtraction, Decision, Disagreement, TopicMention

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are an expert meeting analyst. You receive one chunk of a meeting \
transcript at a time and extract structured knowledge from it.

Extract:
- topics: the subjects actually discussed in this chunk. Use short canonical names \
(2-5 words). If a topic in this chunk is the same as one in the known-topics list, \
reuse that exact name — never invent a near-duplicate. Use related_to to link a topic \
to the earlier topic(s) it follows from.
- decisions: only concrete commitments the group made ("we agreed to X", "let's go \
with Y", "decided to Z"). Not proposals, not open questions.
- disagreements: cases where two speakers take contradictory positions on the same \
topic, in this chunk or contradicting something from the known-topics context. Mark \
resolved=true only if the chunk itself settles it.

Be conservative: an empty list is better than a fabricated item."""


class LLMExtractor:
    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("MEETING_GRAPH_MODEL", DEFAULT_MODEL)

    def extract(self, chunk: Chunk, known_topics: list[str]) -> ChunkExtraction:
        known = "\n".join(f"- {t}" for t in known_topics) if known_topics else "(none yet)"
        prompt = (
            f"Topics already identified earlier in this meeting:\n{known}\n\n"
            f"Transcript chunk {chunk.index + 1}:\n{chunk.as_text()}"
        )
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=ChunkExtraction,
        )
        return response.parsed_output


# ---------------------------------------------------------------------------
# Mock extractor — cue-phrase rules
# ---------------------------------------------------------------------------

_TOPIC_CUES = [
    re.compile(r"\blet'?s (?:talk about|discuss|start with|move (?:on )?to)\s+(?P<topic>[^.,;!?]+)", re.I),
    re.compile(r"\bmoving on to\s+(?P<topic>[^.,;!?]+)", re.I),
    re.compile(r"\bnext (?:up|topic|item)(?: is)?[,:]?\s+(?P<topic>[^.,;!?]+)", re.I),
    re.compile(r"\bfirst (?:up|item|topic)(?: is)?[,:]?\s+(?P<topic>[^.,;!?]+)", re.I),
    re.compile(r"\bon the (?:topic|subject) of\s+(?P<topic>[^.,;!?]+)", re.I),
]

_DECISION_CUES = [
    re.compile(r"\bwe(?:'ve| have)? agreed(?: to| that| on)?\s+(?P<what>[^.;!?]+)", re.I),
    re.compile(r"\blet'?s go with\s+(?P<what>[^.;!?]+)", re.I),
    re.compile(r"\bwe(?:'ll| will) go with\s+(?P<what>[^.;!?]+)", re.I),
    re.compile(r"\b(?:we |it's )?decided(?: to| that| on)?\s+(?P<what>[^.;!?]+)", re.I),
    re.compile(r"\bfinal (?:call|decision)(?: is)?[,:]?\s+(?P<what>[^.;!?]+)", re.I),
]

_DISAGREEMENT_CUES = [
    re.compile(r"\bi (?:have to |respectfully )?disagree\b", re.I),
    re.compile(r"\bi don'?t think\b", re.I),
    re.compile(r"\bi'?m not (?:sure|convinced)\b", re.I),
    re.compile(r"\bpushback\b", re.I),
    re.compile(r"\bthat won'?t work\b", re.I),
]

_RESOLUTION_CUES = [
    re.compile(r"\bfair enough\b", re.I),
    re.compile(r"\byou'?ve convinced me\b", re.I),
    re.compile(r"\bok(?:ay)?,? (?:i'?m|we're) on board\b", re.I),
    re.compile(r"\bworks for me\b", re.I),
]


def _clean_topic(raw: str) -> str:
    raw = re.sub(r"^(the|our|a|an)\s+", "", raw.strip(), flags=re.I)
    words = raw.split()
    return " ".join(words[:5]).strip().title()


class MockExtractor:
    """Rule-based extractor: cheap, deterministic, key-free — and much dumber
    than the LLM. It only sees explicit cue phrases."""

    def __init__(self):
        # Tail of the previous chunk, so a disagreement that opens a chunk can
        # still find the position it is pushing back against.
        self._prev_tail: list = []

    def extract(self, chunk: Chunk, known_topics: list[str]) -> ChunkExtraction:
        topics: list[TopicMention] = []
        decisions: list[Decision] = []
        disagreements: list[Disagreement] = []
        last_topic: str | None = known_topics[-1] if known_topics else None

        for utt in chunk.utterances:
            for cue in _TOPIC_CUES:
                m = cue.search(utt.text)
                if m:
                    name = _clean_topic(m.group("topic"))
                    if name and not any(t.name == name for t in topics):
                        topics.append(
                            TopicMention(
                                name=name,
                                summary=utt.text[:160],
                                related_to=[last_topic] if last_topic else [],
                            )
                        )
                        last_topic = name

            for cue in _DECISION_CUES:
                m = cue.search(utt.text)
                if m:
                    what = m.group("what").strip()
                    decisions.append(
                        Decision(
                            statement=f"Agreed to {what}" if not what.lower().startswith("to ") else f"Agreed {what}",
                            topic=last_topic or "General",
                            speakers=[utt.speaker],
                        )
                    )
                    break

            if any(cue.search(utt.text) for cue in _DISAGREEMENT_CUES):
                prev = _previous_other_speaker(chunk, utt, self._prev_tail)
                resolved = _resolved_later(chunk, utt)
                disagreements.append(
                    Disagreement(
                        topic=last_topic or "General",
                        position_a=prev.text[:160] if prev else "(earlier position)",
                        speaker_a=prev.speaker if prev else "Unknown",
                        position_b=utt.text[:160],
                        speaker_b=utt.speaker,
                        resolved=resolved is not None,
                        resolution=resolved,
                    )
                )

        self._prev_tail = chunk.utterances[-3:]
        return ChunkExtraction(topics=topics, decisions=decisions, disagreements=disagreements)


def _previous_other_speaker(chunk: Chunk, utt, prev_tail: list | None = None) -> object | None:
    idx = chunk.utterances.index(utt)
    candidates = list(prev_tail or []) + chunk.utterances[:idx]
    for prev in reversed(candidates):
        if prev.speaker != utt.speaker:
            return prev
    return None


def _resolved_later(chunk: Chunk, utt) -> str | None:
    idx = chunk.utterances.index(utt)
    for later in chunk.utterances[idx + 1:]:
        if any(cue.search(later.text) for cue in _RESOLUTION_CUES):
            return f"{later.speaker}: {later.text[:120]}"
    return None


def get_extractor(mode: str = "auto", model: str | None = None):
    """mode: "auto" | "live" | "mock"."""
    if mode == "mock":
        return MockExtractor()
    if mode == "live":
        return LLMExtractor(model=model)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMExtractor(model=model)
    return MockExtractor()
