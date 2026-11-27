"""Shape-faithful fakes for the rubric grader's two kinds of run (PKG-05; spec §13 A33).

`agents.grader.grade()` makes two kinds of `grader_agent` run. A grading run
(output `GraderOutput`: the first slot, and the second opinion) sees the whole
message and gives, for every rubric item it credits, a `support` quote from the
answer. A span check (output `SpanVerdicts`, on the grader_second slot) runs
whenever anything is credited and sees only the credited rubric items, each with
its quote — never the rest of the answer (grader-guard round a33, the series
coordinator's ruling). One FunctionModel handler serves both and tells them
apart by the output tool's schema, as the function-mode E2E handler does.

A scripted grading payload names rubric items by id (`"r1:yes"`); the fake
answers under the labels the message shows, as a model does (every grading call
labels the items afresh). For each item it credits it quotes the whole student
answer as its support, unless the payload scripts `support` (`"r1: <quote>"`).
The span check agrees with every span unless a `judge(item_text, span)` says no,
and reports every span asserted unless an `asserted(item_text, span)` says no.
The context check (A33 finish) finds no span withdrawn unless a
`withdrawn(span, whole_answer)` says so.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

_RUBRIC_LINE = re.compile(r"^RUBRIC ITEM (\S+):[ \t]?(.*)$", re.M)

Judge = Callable[[str, str], bool]


def message_text(messages) -> str:
    """The run's user message: the last user-prompt part (a validation retry
    appends a retry part after it)."""
    for message in reversed(messages):
        for part in reversed(getattr(message, "parts", [])):
            if getattr(part, "part_kind", "") == "user-prompt" and isinstance(part.content, str):
                return part.content
    return ""


def labels_of(text: str) -> list[str]:
    """The labels a message shows its rubric items under, in order."""
    return [m.group(1) for m in _RUBRIC_LINE.finditer(text)]


def quoted_answer(text: str) -> str:
    """The student answer a grading message quotes ("> " on every line)."""
    return "\n".join(line[2:] for line in text.splitlines() if line.startswith("> "))


def _properties(info) -> dict:
    return (info.output_tools[0].parameters_json_schema or {}).get("properties", {})


def is_context_check(info) -> bool:
    """A context check's output (`Withdrawals`, A33 finish) is `withdrawn` alone."""
    return "withdrawn" in _properties(info)


def is_span_check(info) -> bool:
    """A span check's output (`SpanVerdicts`) has `asserted` and no report fields."""
    return "asserted" in _properties(info)


_CONTEXT_SPAN = re.compile(r"^SPAN (\S+):$", re.M)


def context_spans(text: str) -> list[tuple[str, str]]:
    """A context check's (label, span) pairs, in order."""
    out: list[tuple[str, str]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _CONTEXT_SPAN.match(line)
        if not m:
            continue
        span = []
        for nxt in lines[i + 1 :]:
            if not nxt.startswith("> "):
                break
            span.append(nxt[2:])
        out.append((m.group(1), "\n".join(span)))
    return out


def _by_label(rid: str, labels: list[str]) -> str:
    n = int(rid[1:]) if re.fullmatch(r"r\d+", rid) else 0
    return labels[n - 1] if 0 < n <= len(labels) else rid


def labelled(payload: dict, messages) -> dict:
    """`payload` with its "r<n>" verdicts and support moved to the n-th label the
    message shows, and a support quote (the whole answer) for every credited item
    it scripts none for."""
    text = message_text(messages)
    labels = labels_of(text)
    results = []
    for entry in payload.get("item_results", []):
        rid, _, verdict = str(entry).partition(":")
        results.append(f"{_by_label(rid.strip(), labels)}:{verdict}")
    if "support" in payload:
        support = []
        for entry in payload["support"]:
            rid, _, quote = str(entry).partition(":")
            support.append(f"{_by_label(rid.strip(), labels)}:{quote}")
    else:
        answer = quoted_answer(text)
        support = [
            f"{label}: {answer}"
            for label, _, verdict in (r.partition(":") for r in results)
            if verdict.strip().lower() == "yes"
        ]
    return {**payload, "item_results": results, "support": support}


def spans_of(text: str) -> list[tuple[str, str, str]]:
    """A span check's (label, item text, span) triples, in order."""
    out: list[tuple[str, str, str]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _RUBRIC_LINE.match(line)
        if not m:
            continue
        span = []
        for nxt in lines[i + 1 :]:
            if not nxt.startswith("> "):
                break
            span.append(nxt[2:])
        out.append((m.group(1), m.group(2), "\n".join(span)))
    return out


def span_verdicts(messages, judge: Judge | None = None, asserted: Judge | None = None) -> dict:
    """The span check's output: yes for every span `judge` accepts (default: all),
    and `asserted` yes for every span `asserted` accepts (default: all)."""
    judge = judge or (lambda item, span: True)
    asserted = asserted or (lambda item, span: True)
    spans = spans_of(message_text(messages))
    return {
        "asserted": [
            f"{label}:{'yes' if asserted(item, span) else 'no'}" for label, item, span in spans
        ],
        "item_results": [
            f"{label}:{'yes' if judge(item, span) else 'no'}"
            for label, item, span in spans_of(message_text(messages))
        ],
    }


def reply(info, args: dict) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)])


def context_verdicts(messages, withdrawn: Judge | None = None) -> dict:
    """The context check's output: no span withdrawn unless `withdrawn(span,
    whole_answer)` says so."""
    withdrawn = withdrawn or (lambda span, answer: False)
    text = message_text(messages)
    answer = quoted_answer(text.split("END OF ANSWER.")[0])
    return {
        "withdrawn": [
            f"{label}:{'yes' if withdrawn(span, answer) else 'no'}"
            for label, span in context_spans(text)
        ]
    }


def check_reply(messages, info, *, judge=None, asserted=None, withdrawn=None):
    """The reply to a span check or a context check, or None for a grading run."""
    if is_context_check(info):
        return reply(info, context_verdicts(messages, withdrawn))
    if is_span_check(info):
        return reply(info, span_verdicts(messages, judge, asserted))
    return None


def scripted_grader(
    outputs: list[dict],
    *,
    judge: Judge | None = None,
    asserted: Judge | None = None,
    withdrawn: Judge | None = None,
):
    """A FunctionModel emitting each grading payload in turn (the last one again
    once they run out) and answering every span check with `judge`. `calls["n"]`
    counts grading runs, `calls["spans"]` span checks, and `calls["span_messages"]`
    holds each span check's message."""
    calls: dict = {"n": 0, "spans": 0, "span_messages": [], "contexts": 0, "context_messages": []}
    withdrawn = withdrawn or (lambda span, answer: False)

    def handler(messages, info):
        if is_context_check(info):
            calls["contexts"] += 1
            calls["context_messages"].append(message_text(messages))
            return reply(info, context_verdicts(messages, withdrawn))
        if is_span_check(info):
            calls["spans"] += 1
            calls["span_messages"].append(message_text(messages))
            return reply(info, span_verdicts(messages, judge, asserted))
        payload = labelled(outputs[min(calls["n"], len(outputs) - 1)], messages)
        calls["n"] += 1
        return reply(info, payload)

    return FunctionModel(handler), calls
