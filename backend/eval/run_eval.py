"""Evaluate extractor output against hand-labeled topics and decisions.

Usage (from backend/):
    python eval/run_eval.py            # auto: live if ANTHROPIC_API_KEY set, else mock
    python eval/run_eval.py --mock
    python eval/run_eval.py --live

Matching is greedy best-match with fuzzy string similarity:
  topics    >= 0.75 (normalized name similarity)
  decisions >= 0.60 (statement similarity)
Reports precision / recall / F1 per transcript and aggregate.
"""
from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extract import get_extractor  # noqa: E402
from app.graph_builder import GraphBuilder, normalize  # noqa: E402
from app.ingest import chunk_transcript, load_transcript  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
LABELS_DIR = BACKEND / "eval" / "labels"

TOPIC_THRESHOLD = 0.75
DECISION_THRESHOLD = 0.60


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def greedy_match(predicted: list[str], expected: list[str], threshold: float) -> int:
    """Number of matched pairs; each expected item matches at most one prediction."""
    remaining = list(expected)
    matched = 0
    for pred in predicted:
        best_i, best_score = -1, 0.0
        for i, exp in enumerate(remaining):
            score = similarity(pred, exp)
            if score > best_score:
                best_i, best_score = i, score
        if best_i >= 0 and best_score >= threshold:
            remaining.pop(best_i)
            matched += 1
    return matched


def prf(matched: int, n_pred: int, n_exp: int) -> tuple[float, float, float]:
    p = matched / n_pred if n_pred else 0.0
    r = matched / n_exp if n_exp else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def run_pipeline(transcript_path: Path, mode: str):
    transcript = load_transcript(transcript_path)
    chunks = chunk_transcript(transcript)
    extractor = get_extractor(mode=mode)
    builder = GraphBuilder(title=transcript.title)
    for chunk in chunks:
        known = [n.label for n in builder.graph.nodes if n.type.value == "topic"]
        builder.add_chunk(chunk, extractor.extract(chunk, known))
    graph = builder.graph
    topics = [n.label for n in graph.nodes if n.type.value == "topic"]
    decisions = [n.summary for n in graph.nodes if n.type.value == "decision"]
    return topics, decisions, type(extractor).__name__


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--mock", action="store_true")
    group.add_argument("--live", action="store_true")
    args = parser.parse_args()
    mode = "live" if args.live else "mock" if args.mock else "auto"

    label_files = sorted(LABELS_DIR.glob("*.json"))
    if not label_files:
        print("No label files found in eval/labels/")
        return 1

    totals = {"topics": [0, 0, 0], "decisions": [0, 0, 0]}  # matched, pred, exp
    extractor_name = "?"

    header = f"{'transcript':<22} {'kind':<10} {'P':>6} {'R':>6} {'F1':>6}   matched/pred/expected"
    print(header)
    print("-" * len(header))

    for label_file in label_files:
        labels = json.loads(label_file.read_text(encoding="utf-8"))
        transcript_path = BACKEND / labels["transcript"]
        pred_topics, pred_decisions, extractor_name = run_pipeline(transcript_path, mode)

        for kind, predicted, expected, threshold in (
            ("topics", pred_topics, labels["topics"], TOPIC_THRESHOLD),
            ("decisions", pred_decisions, labels["decisions"], DECISION_THRESHOLD),
        ):
            matched = greedy_match(predicted, expected, threshold)
            p, r, f = prf(matched, len(predicted), len(expected))
            totals[kind][0] += matched
            totals[kind][1] += len(predicted)
            totals[kind][2] += len(expected)
            print(
                f"{label_file.stem:<22} {kind:<10} {p:>6.2f} {r:>6.2f} {f:>6.2f}   "
                f"{matched}/{len(predicted)}/{len(expected)}"
            )

    print("-" * len(header))
    for kind, (matched, n_pred, n_exp) in totals.items():
        p, r, f = prf(matched, n_pred, n_exp)
        print(f"{'AGGREGATE':<22} {kind:<10} {p:>6.2f} {r:>6.2f} {f:>6.2f}   {matched}/{n_pred}/{n_exp}")
    print(f"\nExtractor: {extractor_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
