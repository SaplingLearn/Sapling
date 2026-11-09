"""Eval-side hint-ladder rung judge (PKG-07 Task 9 follow-up).

`loop_tutor._infer_rung` is a marker classifier that scores any unmarked reply as
H3, so a compliant reply to an H1/H2-ceiling case can never pass
CeilingCompliance (HANDOFF-07 Known gaps). This module replaces it with an LLM
judge that reads the reply against the ladder's own rung definitions
(`learning.ladder.RUNG_INTENT`, embedded verbatim — the single source).

EVAL-ONLY. There is no production model slot (nothing in agents/_providers.py
`_DEFAULTS`) and no function-mode handler: the judge runs only when an eval is
recorded, and replays from cassettes otherwise.

API (for loop_tutor.py's evaluators):

    judge_rung(case_id, slot, served_text, item) -> RungJudgement        # sync
    await ajudge_rung(case_id, slot, served_text, item) -> RungJudgement  # async

`item` is a JudgeItem or the loop_tutor case metadata mapping (`item_prompt`,
`reference`, `final_answer`; optional `student_message`). Cassettes live at
`cassettes/loop_tutor_rung_judge/<slot>__<case_id>.json` as
{served_sha256, judge_model, judge_prompt_hash, output}. Replay RAISES
StaleJudgementError when the served text, the judge prompt (instructions, item,
or output schema) or the judge model differs from what was recorded, and
MissingJudgementError when no cassette exists — a stale judgement never scores.

Model: RUNG_JUDGE_MODEL (env override; default gemini-2.5-pro), low thinking
budget. Record with SAPLING_EVAL_MODE=record and SAPLING_MODEL_MODE unset.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel, Field  # noqa: E402

from _replay import CASSETTE_DIR, _is_transient, _safe_filename  # noqa: E402
from learning.ladder import RUNG_INTENT, Rung  # noqa: E402

JUDGE_DATASET = "loop_tutor_rung_judge"


def _model_name(raw: str) -> str:
    # Accept the pydantic-ai provider-string spelling too ("google-gla:gemini-2.5-pro").
    return raw.split(":", 1)[1] if ":" in raw else raw


RUNG_JUDGE_MODEL = _model_name(os.getenv("RUNG_JUDGE_MODEL", "gemini-2.5-pro"))
#: Pro cannot run with thinking off; keep it small — the task is classification.
RUNG_JUDGE_THINKING_BUDGET = 512
RUNG_JUDGE_MAX_TOKENS = RUNG_JUDGE_THINKING_BUDGET + 512
EVIDENCE_MAX_CHARS = 200


class RungJudgement(BaseModel):
    rung: int = Field(
        ge=0,
        le=6,
        description="The HIGHEST hint-ladder rung (0-6, i.e. H0-H6) whose content the tutor reply contains.",
    )
    reveals_final_answer: bool = Field(
        description="True if the reply states the item's final answer or gives it away trivially.",
    )
    evidence: str = Field(
        max_length=EVIDENCE_MAX_CHARS,
        description="The short phrase from the reply that decided the rung (at most 200 characters).",
    )


class JudgeItem(BaseModel):
    """What the judge sees about the check item. The judge MAY see the reference
    and the final answer (the tutor never does)."""

    prompt: str = ""
    reference_answer: str
    final_answer: str
    student_message: str = ""

    @classmethod
    def from_metadata(cls, meta: Mapping[str, Any], student_message: str = "") -> JudgeItem:
        return cls(
            prompt=meta.get("item_prompt") or meta.get("prompt") or "",
            reference_answer=meta.get("reference") or meta.get("reference_answer") or "",
            final_answer=meta.get("final_answer") or "",
            student_message=student_message or meta.get("student_message") or "",
        )


def _coerce_item(item: JudgeItem | Mapping[str, Any]) -> JudgeItem:
    return item if isinstance(item, JudgeItem) else JudgeItem.from_metadata(item)


# ── the judge prompt ──────────────────────────────────────────────────────────

# Short anchors per rung; RUNG_INTENT stays the definition, these only
# disambiguate the neighbours a reader confuses most.
_ANCHORS: dict[Rung, str] = {
    Rung.H0: "e.g. 'Yes, that's right.' Confirms what the student already said; adds nothing new.",
    Rung.H1: (
        "e.g. 'What do you need to figure out first?' A generic prompt to think or focus; "
        "names no concept, definition, rule or step of THIS problem."
    ),
    Rung.H2: (
        "e.g. 'Your notes define a base case as ...' / 'Recall the power rule: ...' Points to or quotes "
        "a concept, definition or course passage in general terms, without applying it to the item."
    ),
    Rung.H3: (
        "e.g. 'What should the function return when n is 0?' A question aimed at the specific next "
        "step of THIS item — it names the step, but the student still has to do it."
    ),
    Rung.H4: (
        "e.g. 'Take sum_to(n) instead: when n is 0 it returns 0 ...' Walks through a DIFFERENT "
        "problem with the same structure, showing its steps or its answer."
    ),
    Rung.H5: (
        "e.g. 'return n * factorial(n - 1) ... if n == 0: return ___' Shows THIS item's solution "
        "with the final step(s) left blank for the student to fill."
    ),
    Rung.H6: (
        "e.g. 'The answer is 3x^2 because ...' Gives THIS item's solution or its final answer, with "
        "or without the words 'the answer is'."
    ),
}


def _ladder_block() -> str:
    lines = []
    for rung in Rung:
        lines.append(f"H{int(rung)} — {RUNG_INTENT[rung]}\n    Anchor: {_ANCHORS[rung]}")
    return "\n".join(lines)


JUDGE_INSTRUCTIONS = f"""You grade one reply from an AI tutor against a hint ladder.

THE LADDER (H0 gives the least help, H6 the most):
{_ladder_block()}

TASK
- rung: the HIGHEST rung whose content the reply contains. A reply that mixes rungs is
  graded by its most helpful part (a pointer plus a leading question is H3; any worked
  isomorph is at least H4; any of THIS item's solution with blanks is at least H5; this
  item's full solution or final answer is H6). Judge the content, not wording or
  formatting: a reply needs no marker phrase ("the answer is", "worked example") to be
  at a rung, and a marker phrase alone does not put it there.
- Do not over-count: a reply that only asks the student what they need, or which idea
  applies, with no concept named, is H1, not H3. Naming a concept or quoting its
  definition without applying it to this item is H2, not H3.
- reveals_final_answer: true if the reply states the item's FINAL ANSWER (below), in any
  spelling or notation, or gives it away trivially (the only thing left is to copy or
  restate it). False if the student still has real work to do.
- evidence: quote the short phrase from the reply that decided the rung (at most
  {EVIDENCE_MAX_CHARS} characters).

You see the item's reference answer and final answer so you can tell whether they
leak; the tutor did not see them. Judge only the TUTOR REPLY."""


_SERVED_SLOT = "{served_text}"
_MESSAGE_TEMPLATE = """ITEM PROMPT: {prompt}
REFERENCE ANSWER: {reference_answer}
FINAL ANSWER: {final_answer}
STUDENT'S LAST MESSAGE: {student_message}

TUTOR REPLY (grade this):
<<<
{served_text}
>>>"""


def build_judge_message(served_text: str, item: JudgeItem | Mapping[str, Any]) -> str:
    it = _coerce_item(item)
    return _MESSAGE_TEMPLATE.format(
        prompt=it.prompt or "(none: open teaching turn)",
        reference_answer=it.reference_answer,
        final_answer=it.final_answer,
        student_message=it.student_message or "(none)",
        served_text=served_text,
    )


def judge_prompt_hash(item: JudgeItem | Mapping[str, Any]) -> str:
    """Hash of everything the judge is told EXCEPT the served text (which has its
    own sha): instructions, the item block of the message, and the output schema
    (a Pydantic field description is sent to Gemini)."""
    body = "\x00".join(
        (
            JUDGE_INSTRUCTIONS,
            build_judge_message(_SERVED_SLOT, item),
            json.dumps(RungJudgement.model_json_schema(), sort_keys=True),
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def served_sha256(served_text: str) -> str:
    return hashlib.sha256(served_text.encode("utf-8")).hexdigest()


# ── cassettes ─────────────────────────────────────────────────────────────────


class MissingJudgementError(RuntimeError):
    pass


class StaleJudgementError(RuntimeError):
    pass


def cassette_path(slot: str, case_id: str, *, root: Path | None = None) -> Path:
    base = Path(root) if root is not None else CASSETTE_DIR
    return base / JUDGE_DATASET / f"{_safe_filename(f'{slot}__{case_id}')}.json"


def _load_fresh(path: Path, served_text: str, item: JudgeItem) -> RungJudgement:
    if not path.exists():
        raise MissingJudgementError(
            f"No rung-judge cassette at {path}. Run the eval with SAPLING_EVAL_MODE=record."
        )
    body = json.loads(path.read_text())
    problems = []
    if body.get("served_sha256") != served_sha256(served_text):
        problems.append("served text changed since the judgement was recorded")
    if body.get("judge_prompt_hash") != judge_prompt_hash(item):
        problems.append("judge prompt (instructions, item or schema) changed")
    if body.get("judge_model") != RUNG_JUDGE_MODEL:
        problems.append(
            f"judge model changed ({body.get('judge_model')!r} -> {RUNG_JUDGE_MODEL!r})"
        )
    if problems:
        raise StaleJudgementError(
            f"Stale rung judgement {path.name}: {'; '.join(problems)}. "
            "Re-record with SAPLING_EVAL_MODE=record."
        )
    return RungJudgement.model_validate(body["output"])


def _save(path: Path, served_text: str, item: JudgeItem, output: RungJudgement) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "served_sha256": served_sha256(served_text),
        "judge_model": RUNG_JUDGE_MODEL,
        "judge_prompt_hash": judge_prompt_hash(item),
        "output": output.model_dump(mode="json"),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


# ── the model call (record / live only) ──────────────────────────────────────

_agent = None


def _judge_agent():
    """Built lazily so replay never constructs a model."""
    global _agent
    if _agent is None:
        from pydantic_ai import Agent

        _agent = Agent(output_type=RungJudgement, retries=2)
    return _agent


async def _call_model(served_text: str, item: JudgeItem) -> RungJudgement:
    from google.genai.types import ThinkingConfig
    from pydantic_ai.models.google import GoogleModelSettings

    from agents._providers import google_model  # the bare-name shim; no task slot

    settings = GoogleModelSettings(
        google_thinking_config=ThinkingConfig(thinking_budget=RUNG_JUDGE_THINKING_BUDGET),
        max_tokens=RUNG_JUDGE_MAX_TOKENS,
        temperature=0.0,
    )
    agent = _judge_agent()
    message = build_judge_message(served_text, item)
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            result = await agent.run(
                message,
                model=google_model(RUNG_JUDGE_MODEL),
                model_settings=settings,
                instructions=JUDGE_INSTRUCTIONS,
            )
            return result.output
        except Exception as exc:  # noqa: BLE001 - re-raised unless transient
            if not _is_transient(exc) or attempt == 4:
                raise
            last_exc = exc
            await asyncio.sleep(3.0 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _mode(mode: str | None) -> str:
    return (mode or os.getenv("SAPLING_EVAL_MODE", "replay")).lower()


async def ajudge_rung(
    case_id: str,
    slot: str,
    served_text: str,
    item: JudgeItem | Mapping[str, Any],
    *,
    mode: str | None = None,
    cassette_dir: Path | None = None,
) -> RungJudgement:
    it = _coerce_item(item)
    path = cassette_path(slot, case_id, root=cassette_dir)
    m = _mode(mode)
    if m == "replay":
        return _load_fresh(path, served_text, it)
    output = await _call_model(served_text, it)
    if m == "record":
        _save(path, served_text, it, output)
    return output


def judge_rung(
    case_id: str,
    slot: str,
    served_text: str,
    item: JudgeItem | Mapping[str, Any],
    *,
    mode: str | None = None,
    cassette_dir: Path | None = None,
) -> RungJudgement:
    """Sync form. Replay is a pure file read; record/live run the model on a
    fresh loop (a worker thread when called from inside a running loop, e.g. a
    sync pydantic-evals evaluator)."""
    coro_fn = lambda: ajudge_rung(  # noqa: E731
        case_id, slot, served_text, item, mode=mode, cassette_dir=cassette_dir
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_fn())
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["out"] = asyncio.run(coro_fn())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            box["exc"] = exc

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    if "exc" in box:
        raise box["exc"]
    return box["out"]
