"""Transcript ingestion: parse raw transcripts and chunk them for extraction.

Supported input formats:
  * Plain text — one utterance per line: ``[HH:MM:SS] Speaker: text``
    (the ``[timestamp]`` prefix is optional).
  * JSON — ``{"title": str, "entries": [{"t": seconds, "speaker": str, "text": str}]}``

Chunking closes a chunk on a speaker-turn boundary once it exceeds either
``max_turns`` utterances or ``max_seconds`` of meeting time, so each chunk is a
coherent slice of conversation sized for a single extraction call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .schemas import Chunk, Transcript, Utterance

_LINE_RE = re.compile(
    r"^(?:\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s*)?(?P<speaker>[^:]{1,40}):\s*(?P<text>.+)$"
)


def _parse_ts(ts: str) -> float:
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    h, m, s = parts
    return h * 3600 + m * 60 + s


def parse_text_transcript(text: str, title: str = "Untitled meeting") -> Transcript:
    entries: list[Utterance] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            # Continuation of the previous utterance (wrapped line).
            if entries:
                entries[-1].text += " " + line
            continue
        ts = m.group("ts")
        entries.append(
            Utterance(
                t=_parse_ts(ts) if ts else None,
                speaker=m.group("speaker").strip(),
                text=m.group("text").strip(),
            )
        )
    return Transcript(title=title, entries=entries)


def parse_json_transcript(text: str) -> Transcript:
    return Transcript.model_validate(json.loads(text))


def load_transcript(path: str | Path) -> Transcript:
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return parse_json_transcript(raw)
    return parse_text_transcript(raw, title=path.stem.replace("_", " "))


def chunk_transcript(
    transcript: Transcript,
    max_turns: int = 6,
    max_seconds: float = 60.0,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: list[Utterance] = []

    def close() -> None:
        if not current:
            return
        idx = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=f"c{idx}",
                index=idx,
                start=current[0].t,
                end=current[-1].t,
                speakers=sorted({u.speaker for u in current}),
                utterances=list(current),
            )
        )
        current.clear()

    for utt in transcript.entries:
        # Close on a speaker-turn boundary once the chunk is "full".
        if current:
            over_turns = len(current) >= max_turns
            over_time = (
                utt.t is not None
                and current[0].t is not None
                and utt.t - current[0].t > max_seconds
            )
            turn_boundary = utt.speaker != current[-1].speaker
            if (over_turns or over_time) and turn_boundary:
                close()
        current.append(utt)
    close()
    return chunks
