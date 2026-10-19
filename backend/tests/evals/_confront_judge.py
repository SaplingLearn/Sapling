"""Eval-side misconception-confrontation judge (PKG-10).

Reads ONE served loop-tutor reply against the misconception the route told the
tutor to confront (routes.learn_loop.confront_line_for) and answers three
structured questions: does the reply confront the misconception with a
contradiction the student must resolve (spec §3.3; research: Lehman 2013,
contradiction-induced confusion), or does it only state the correction; and
does it ever affirm the misconception.

EVAL-ONLY, like _rung_judge.py: no production slot, no function-mode handler;
it runs only when the eval is recorded and replays from cassettes otherwise.
Cassettes: `cassettes/misconception_confront_judge/<slot>__<case>.json` =
{served_sha256, judge_model, judge_prompt_hash, output}; replay RAISES
StaleJudgementError when the served text, the judge prompt (instructions,
case block or output schema) or the judge model differs, and
MissingJudgementError when no cassette exists — a stale judgement never scores.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel, Field  # noqa: E402

from _replay import CASSETTE_DIR, _is_transient, _safe_filename  # noqa: E402
from _rung_judge import MissingJudgementError, StaleJudgementError  # noqa: E402

JUDGE_DATASET = "misconception_confront_judge"


def _model_name(raw: str) -> str:
    return raw.split(":", 1)[1] if ":" in raw else raw


CONFRONT_JUDGE_MODEL = _model_name(os.getenv("CONFRONT_JUDGE_MODEL", "gemini-2.5-pro"))
CONFRONT_JUDGE_THINKING_BUDGET = 512
CONFRONT_JUDGE_MAX_TOKENS = CONFRONT_JUDGE_THINKING_BUDGET + 512
EVIDENCE_MAX_CHARS = 200


class ConfrontJudgement(BaseModel):
    confronts: bool = Field(
        description=(
            "True if the reply puts something in front of the student that the misconception "
            "gets wrong — a counterexample, a prediction to check, a case to work out, or a "
            "question whose honest answer conflicts with the misconception — and leaves the "
            "student to resolve the conflict."
        )
    )
    only_states_correction: bool = Field(
        description=(
            "True if the reply's main move is to TELL the student the misconception is wrong "
            "or what the right rule is, with nothing left for them to work out."
        )
    )
    affirms_misconception: bool = Field(
        description="True if any part of the reply agrees with or endorses the misconception."
    )
    evidence: str = Field(
        max_length=EVIDENCE_MAX_CHARS,
        description="The short phrase from the reply that decided `confronts` (at most 200 characters).",
    )


class ConfrontCase(BaseModel):
    """What the judge sees: the item as posed, the misconception, the student's
    last message. It never needs the reference answer."""

    item_prompt: str = ""
    misconception: str
    student_message: str = ""


JUDGE_INSTRUCTIONS = """You grade one reply from an AI tutor. The tutor was told the student holds
the MISCONCEPTION below and was asked to create a contradiction the student must resolve,
rather than simply state the correction.

- confronts: true when the reply sets up a conflict the misconception cannot survive — a
  counterexample, a specific case to compute or predict, or a question whose honest answer
  contradicts the misconception — and hands it to the student to resolve. A reply that
  names the misconception and then explains the right rule does NOT confront, even if it
  ends with a question; neither does a generic "what do you think?".
- only_states_correction: true when the reply mainly tells the student they are wrong
  or tells them the correct rule, leaving nothing for them to work out.
- affirms_misconception: true when any part of the reply agrees with the misconception.
- evidence: quote the short phrase that decided `confronts` (at most 200 characters).
Judge only the TUTOR REPLY."""

_SERVED_SLOT = "{served_text}"
_MESSAGE_TEMPLATE = """ITEM PROMPT: {item_prompt}
MISCONCEPTION: {misconception}
STUDENT'S LAST MESSAGE: {student_message}

TUTOR REPLY (grade this):
<<<
{served_text}
>>>"""


def build_judge_message(served_text: str, case: ConfrontCase) -> str:
    return _MESSAGE_TEMPLATE.format(
        item_prompt=case.item_prompt or "(none: open teaching turn)",
        misconception=case.misconception,
        student_message=case.student_message or "(none)",
        served_text=served_text,
    )


def judge_prompt_hash(case: ConfrontCase) -> str:
    body = "\x00".join(
        (
            JUDGE_INSTRUCTIONS,
            build_judge_message(_SERVED_SLOT, case),
            json.dumps(ConfrontJudgement.model_json_schema(), sort_keys=True),
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def served_sha256(served_text: str) -> str:
    return hashlib.sha256(served_text.encode("utf-8")).hexdigest()


def cassette_path(slot: str, case_id: str, *, root: Path | None = None) -> Path:
    base = Path(root) if root is not None else CASSETTE_DIR
    return base / JUDGE_DATASET / f"{_safe_filename(f'{slot}__{case_id}')}.json"


def _load_fresh(path: Path, served_text: str, case: ConfrontCase) -> ConfrontJudgement:
    if not path.exists():
        raise MissingJudgementError(
            f"No confront-judge cassette at {path}. Run the eval with SAPLING_EVAL_MODE=record."
        )
    body = json.loads(path.read_text())
    problems = []
    if body.get("served_sha256") != served_sha256(served_text):
        problems.append("served text changed since the judgement was recorded")
    if body.get("judge_prompt_hash") != judge_prompt_hash(case):
        problems.append("judge prompt (instructions, case or schema) changed")
    if body.get("judge_model") != CONFRONT_JUDGE_MODEL:
        problems.append(
            f"judge model changed ({body.get('judge_model')!r} -> {CONFRONT_JUDGE_MODEL!r})"
        )
    if problems:
        raise StaleJudgementError(
            f"Stale confront judgement {path.name}: {'; '.join(problems)}. "
            "Re-record with SAPLING_EVAL_MODE=record."
        )
    return ConfrontJudgement.model_validate(body["output"])


def _save(path: Path, served_text: str, case: ConfrontCase, output: ConfrontJudgement) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "served_sha256": served_sha256(served_text),
        "judge_model": CONFRONT_JUDGE_MODEL,
        "judge_prompt_hash": judge_prompt_hash(case),
        "output": output.model_dump(mode="json"),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


_agent = None


def _judge_agent():
    global _agent
    if _agent is None:
        from pydantic_ai import Agent

        _agent = Agent(output_type=ConfrontJudgement, retries=2)
    return _agent


async def _call_model(served_text: str, case: ConfrontCase) -> ConfrontJudgement:
    from google.genai.types import ThinkingConfig
    from pydantic_ai.models.google import GoogleModelSettings

    from agents._providers import google_model

    settings = GoogleModelSettings(
        google_thinking_config=ThinkingConfig(thinking_budget=CONFRONT_JUDGE_THINKING_BUDGET),
        max_tokens=CONFRONT_JUDGE_MAX_TOKENS,
        temperature=0.0,
    )
    message = build_judge_message(served_text, case)
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            result = await _judge_agent().run(
                message,
                model=google_model(CONFRONT_JUDGE_MODEL),
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


async def ajudge_confront(
    case_id: str,
    slot: str,
    served_text: str,
    case: ConfrontCase,
    *,
    mode: str | None = None,
    cassette_dir: Path | None = None,
) -> ConfrontJudgement:
    path = cassette_path(slot, case_id, root=cassette_dir)
    m = (mode or os.getenv("SAPLING_EVAL_MODE", "replay")).lower()
    if m == "replay":
        return _load_fresh(path, served_text, case)
    output = await _call_model(served_text, case)
    if m == "record":
        _save(path, served_text, case, output)
    return output
