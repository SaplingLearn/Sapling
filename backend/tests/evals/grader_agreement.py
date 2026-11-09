"""
Grader validity check against human scorers (docs/research/learning-loop/
2026-11-07-direction-audit.md, rec. 4 — the Stage 0 measurement step).

The grader's eval fixture (tests/evals/grader.py) is a regression test written
by its developers; it cannot say how the grader behaves on real student
answers. This script runs the PRODUCTION grading path, agents.grader.grade(),
over answers that human experts scored independently, and reports:

  - agreement and Cohen's kappa of the grader against each human rater, and of
    the two raters against each other (the human ceiling to compare with)
  - signed bias: P(grader credits) − P(consensus credits); > 0 is lenient
  - false credit (grader yes where the human consensus says no) and false
    rejection (grader no where it says yes), the two errors that matter for
    evidence: false credit inflates mastery, false rejection hides it
  - the same per answer format, plus how many answers the grader refused or
    could not grade (never counted as a verdict)
  - the same per grader backend (`by_backend`): each verdict's provenance, the
    provider of the slot whose run it stands on (`gemini`, `gemini_second`,
    `claude`, `claude_second`; spec §13 A116), so a run on a flipped slot
    (A111's runbook) reports under its own name, and two runs over the same
    answers — one per provider, `--out` files concatenated, then `--no-grade` —
    compare side by side

Verdict = the answer is correct overall: every rubric item credited
(`GradeResult.all_yes`), the same rule the loop's evidence uses for a free or
teachback answer. A human verdict is the rater's overall correct/incorrect call.

Input: JSON Lines, one answer per line:

    {"id": "a1", "format": "free",            # free | teachback | mc_reason
     "prompt": "...", "reference_answer": "...",
     "rubric": [{"id": "r1", "text": "..."}, ...],
     "common_wrong": [{"key": "w1", "text": "..."}],   # optional
     "answer": "the student's words",
     "human_a": true, "human_b": false}       # human_b optional

Run from backend/ (real model mode and provider keys; every answer is one or
more grader calls). It lives beside the grader's replay eval (tests/evals/
grader.py) because it is an evaluation tool, never application code — the
SANCTIONED_GRADING_CALLERS scan keeps every application caller of the grader
gated:

    python tests/evals/grader_agreement.py answers.jsonl            # grade, then report
    python tests/evals/grader_agreement.py answers.jsonl --out r.json
    python tests/evals/grader_agreement.py scored.jsonl --no-grade  # lines carry "grader": bool

Not a dataset: run_all.py runs only its explicit DATASETS list.

`--no-grade` reads a previous run's per-answer verdicts (the `grader` field, and
`grader_backend` when the line has one) and only recomputes the statistics. A
REPORT <json> line is always printed.

Exit codes: 0 report printed; 2 bad input.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

FORMATS = ("free", "teachback", "mc_reason")


class InputError(ValueError):
    """A line the script cannot use (exit 2)."""


# ── statistics (pure) ────────────────────────────────────────────────────────


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """Cohen's kappa for two binary raters over the same items; None when there
    is nothing to judge or chance agreement is total (every label identical)."""
    if len(a) != len(b):
        raise ValueError("rater sequences differ in length")
    n = len(a)
    if not n:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def pair_stats(a: Sequence[bool], b: Sequence[bool]) -> dict:
    """Agreement and kappa of two raters; n = items both labelled."""
    n = len(a)
    return {
        "n": n,
        "agreement": _rate(sum(x == y for x, y in zip(a, b)), n),
        "kappa": cohen_kappa(a, b),
    }


def grader_vs_truth(grader: Sequence[bool], truth: Sequence[bool]) -> dict:
    """The grader against a reference labelling (the human consensus)."""
    n = len(grader)
    pos = sum(truth)
    neg = n - pos
    false_credit = sum(g and not t for g, t in zip(grader, truth))
    false_reject = sum(t and not g for g, t in zip(grader, truth))
    return {
        **pair_stats(grader, truth),
        "grader_credit_rate": _rate(sum(grader), n),
        "human_credit_rate": _rate(pos, n),
        "signed_bias": (sum(grader) - pos) / n if n else None,
        "false_credit_rate": _rate(false_credit, neg),
        "false_reject_rate": _rate(false_reject, pos),
    }


def consensus(record: dict) -> bool | None:
    """The human truth for one answer: rater A's call when there is one rater;
    the shared call when both agree; None (left out) when they disagree."""
    a, b = record.get("human_a"), record.get("human_b")
    if b is None:
        return a
    return a if a == b else None


def report(records: Iterable[dict]) -> dict:
    """The full report over records that carry `grader` (bool or None = no
    verdict: refused or unavailable) and the human labels."""
    records = list(records)
    graded = [r for r in records if isinstance(r.get("grader"), bool)]
    no_verdict = len(records) - len(graded)

    def block(rows: list[dict]) -> dict:
        with_truth = [r for r in rows if consensus(r) is not None]
        out = grader_vs_truth(
            [r["grader"] for r in with_truth], [consensus(r) for r in with_truth]
        )
        out["human_disagreements"] = sum(
            1 for r in rows if r.get("human_b") is not None and r["human_a"] != r["human_b"]
        )
        out["vs_human_a"] = pair_stats(
            [r["grader"] for r in rows], [r["human_a"] for r in rows]
        )
        two = [r for r in rows if r.get("human_b") is not None]
        out["vs_human_b"] = pair_stats([r["grader"] for r in two], [r["human_b"] for r in two])
        out["human_a_vs_b"] = pair_stats([r["human_a"] for r in two], [r["human_b"] for r in two])
        return out

    by_format: dict[str, list[dict]] = defaultdict(list)
    by_backend: dict[str, list[dict]] = defaultdict(list)
    for r in graded:
        by_format[r["format"]].append(r)
        if r.get("grader_backend"):  # a scored line from before A116 names none
            by_backend[r["grader_backend"]].append(r)
    return {
        "answers": len(records),
        "graded": len(graded),
        "no_verdict": no_verdict,
        "overall": block(graded),
        "by_format": {f: block(rows) for f, rows in sorted(by_format.items())},
        "by_backend": {b: block(rows) for b, rows in sorted(by_backend.items())},
    }


# ── input ────────────────────────────────────────────────────────────────────


def parse_line(raw: str, lineno: int, *, need_item: bool) -> dict:
    try:
        rec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"line {lineno}: not JSON ({exc.msg})") from exc
    if not isinstance(rec, dict):
        raise InputError(f"line {lineno}: not an object")
    if rec.get("format") not in FORMATS:
        raise InputError(f"line {lineno}: format must be one of {FORMATS}")
    if not isinstance(rec.get("human_a"), bool):
        raise InputError(f"line {lineno}: human_a must be true or false")
    if rec.get("human_b") is not None and not isinstance(rec["human_b"], bool):
        raise InputError(f"line {lineno}: human_b must be true, false or absent")
    if need_item:
        for key in ("prompt", "reference_answer", "answer"):
            if not isinstance(rec.get(key), str) or not rec[key].strip():
                raise InputError(f"line {lineno}: {key} must be a non-empty string")
        rubric = rec.get("rubric")
        if not isinstance(rubric, list) or not rubric:
            raise InputError(f"line {lineno}: rubric must be a non-empty list")
    elif "grader" not in rec or (rec["grader"] is not None and not isinstance(rec["grader"], bool)):
        raise InputError(f"line {lineno}: --no-grade needs grader: true, false or null")
    elif rec.get("grader_backend") is not None and not isinstance(rec["grader_backend"], str):
        raise InputError(f"line {lineno}: grader_backend must be a string, null or absent")
    rec.setdefault("id", f"line-{lineno}")
    return rec


def load(path: Path, *, need_item: bool) -> list[dict]:
    lines = path.read_text().splitlines()
    return [
        parse_line(raw, i, need_item=need_item)
        for i, raw in enumerate(lines, start=1)
        if raw.strip()
    ]


# ── grading (the production path) ────────────────────────────────────────────


def _item(rec: dict):
    from learning.checks import RubricItem, WrongReason

    return SimpleNamespace(
        id=rec["id"],
        prompt=rec["prompt"],
        reference_answer=rec["reference_answer"],
        rubric=[RubricItem(**r) for r in rec["rubric"]],
        common_wrong=[WrongReason(**w) for w in rec.get("common_wrong") or []],
    )


async def grade_all(records: list[dict], *, grade=None, deps=None) -> list[dict]:
    """Annotate each record with `grader` (bool, or None when refused or
    unavailable), `grader_refused` and `grader_backend` (GradeResult.backend: the
    provider of the run the verdict stands on, A116; None with no verdict).
    Sequential: one answer at a time keeps the provider's rate limit and the cost
    visible."""
    if grade is None:
        from agents.grader import grade
    if deps is None:
        from agents.deps import SaplingDeps

        deps = SaplingDeps(
            user_id="grader-agreement", course_id="grader-agreement",
            supabase=None, request_id="grader-agreement",
        )
    out = []
    for rec in records:
        result = await grade(_item(rec), format=rec["format"], student_answer=rec["answer"],
                             deps=deps)
        verdict = None if result.unavailable else bool(result.all_yes)
        refused = getattr(result, "refused", None)
        out.append({
            **rec,
            "grader": verdict,
            "grader_refused": str(refused) if refused else None,
            "grader_backend": None if verdict is None else getattr(result, "backend", None),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path", type=Path)
    ap.add_argument("--no-grade", action="store_true",
                    help="lines already carry `grader`; recompute the statistics only")
    ap.add_argument("--out", type=Path, help="write per-answer verdicts as JSON Lines here")
    args = ap.parse_args(argv)
    try:
        records = load(args.path, need_item=not args.no_grade)
    except (InputError, OSError) as exc:
        print(f"INPUT_FAIL {exc}", file=sys.stderr)
        return 2
    if not args.no_grade:
        # No database here either: the grader's budget check reads the eval
        # harness's empty store (tests/evals/_replay.py::hermetic_budget).
        from tests.evals._replay import hermetic_budget, usage_log

        with hermetic_budget(), usage_log("grader_agreement"):
            records = asyncio.run(grade_all(records))
    if args.out:
        args.out.write_text("".join(json.dumps(r) + "\n" for r in records))
    print("REPORT " + json.dumps(report(records), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
