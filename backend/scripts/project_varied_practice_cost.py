"""Offline estimate of what varied practice costs with its flags on (spec §13
A140 `varied_isomorphs`, A141 `multi_concept_items`), by
scripts/project_loop_cost.py's method — its request capture, its
characters / 4 tokens, its prices, caching and thinking allowances — for
docs/research/learning-loop/2026-11-08-loop-cost-projection.md.

    cd backend
    SAPLING_EVAL_MODE=replay GEMINI_API_KEY=dummy-not-used-in-replay \\
      ANTHROPIC_API_KEY=dummy-not-used-in-replay \\
      ENCRYPTION_KEY=0000000000000000000000000000000000000000000000000000000000000000 \\
      venv/bin/python scripts/project_varied_practice_cost.py [--markdown] [--steady-traffic]

Nothing is called: no model, no network, no database. Serving adds no model
call — both dials are code over stored rows, and a combination is posed in
place of one of the session's checks, graded like any — so the flags cost
only drafting, per upload:

  • A140: the varied drafter replaces the plain one on every drafting call.
    Its input is the plain call's plus the surface rules and the concepts'
    stored surfaces (none on a first upload); its output is each recorded
    item with the descriptor in place of the two fields code derives. The
    alignment check and the blind solve never see the descriptor: unchanged.
  • A141: the combination drafter, MULTI_CONCEPT_COMBOS_PER_CALL combinations
    a call, one item per format each, at most MULTI_CONCEPT_COMBOS_PER_DOC
    combinations an upload (the cap, an upper bound: only an apex with a
    direct prerequisite has one), each call checked by the combination
    alignment check and the A124 blind solve. Its input is built from the
    check_items eval's documents: each document's three concepts paired as
    a prerequisite chain, its passages. Its output is the recorded items'
    mean size per format; the two checks' verdicts are estimated per item as
    the base script's are (†).

The top-up (A37, plain or varied) is not modelled, as in the base script.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import statistics
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"

#: † tokens per item of a verdict list (the base script's per_item_verdict)
PER_ITEM_VERDICT = 40
#: † tokens per component row of the combination alignment check's verdict
#: ({item, component, why, required}: ids, a flag and a one-line reason)
PER_COMPONENT_VERDICT = 20
#: † the components of an average combination (pairs before triples)
COMPONENTS_PER_COMBINATION = 2
#: a surface context at its cap, for the varied output's size
CONTEXT_AT_CAP = "rideshare surge pricing night"


def _base():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("project_loop_cost")


def _recorded():
    """[(concept, passages, CheckItemsOutput)] over the check_items eval's cases."""
    from agents.check_items import CheckItemsOutput

    from _replay import load_cassette

    base = _base()
    ev = base._eval("check_items")
    out = []
    for case in ev.CASES:
        body = load_cassette("check_items", case.name)
        if body is None:
            continue
        concept, chunks = case.inputs
        passages = [{"id": cid, "text": text} for cid, text in chunks]
        out.append((concept, passages, CheckItemsOutput.model_validate(body)))
    return out


def _varied_item(item) -> dict:
    """A recorded item as the varied schema has it: the descriptor in, the two
    fields code derives (answer_kind, stepwise) out."""
    data = {k: v for k, v in item.model_dump(mode="json").items() if k not in ("answer_kind", "stepwise")}
    data.update(surface_representation="numeric", surface_context=CONTEXT_AT_CAP)
    return data


def measure() -> dict:
    from agents.check_items import build_prompt
    from agents.check_items_combo import build_combo_prompt, check_items_combo_agent
    from agents.check_items_combo_verify import check_items_combo_verify_agent
    from agents.check_items_varied import build_varied_prompt, check_items_varied_agent
    from learning.multi_concept import label
    from learning.params import (
        CHECK_ITEM_CONCEPTS_PER_CALL,
        CHECK_ITEM_FORMATS,
        MULTI_CONCEPT_COMBOS_PER_CALL,
        SURFACE_REPRESENTATIONS,
    )
    from learning.surface import Surface

    base = _base()
    with base._anthropic_capture():
        prefixes = {
            "check_items": base._prefix_tokens(base._request(base_agent(), "check_items")),
            "varied": base._prefix_tokens(base._request(check_items_varied_agent, "check_items")),
            "combo": base._prefix_tokens(base._request(check_items_combo_agent, "check_items")),
            "combo_verify": base._prefix_tokens(
                base._request(check_items_combo_verify_agent, "check_items_verify")
            ),
            "solve": base._prefix_tokens(base._request(solve_agent(), "check_items_solve")),
        }
    recorded = _recorded()
    k = CHECK_ITEM_CONCEPTS_PER_CALL
    plain_in = statistics.mean(base._tokens(build_prompt([c], p)) for c, p, _ in recorded) * k
    plain_out = statistics.mean(base._tokens(o.model_dump_json()) for _, _, o in recorded) * k
    varied_in = statistics.mean(base._tokens(build_varied_prompt([c], p, {})) for c, p, _ in recorded) * k
    # a re-draft of concepts that already hold a surface of every representation
    used = {c: [Surface(r, CONTEXT_AT_CAP) for r in SURFACE_REPRESENTATIONS] for c, _, _ in recorded}
    varied_in_used = statistics.mean(
        base._tokens(build_varied_prompt([c], p, {c: used[c]})) for c, p, _ in recorded
    ) * k
    varied_out = statistics.mean(
        base._tokens(json.dumps({"items": [_varied_item(i) for i in o.items]})) for _, _, o in recorded
    ) * k
    # the combination drafter: each document's three concepts as a prerequisite
    # chain (the eval documents name them in teaching order) — three combinations
    by_doc: dict[str, list] = {}
    for concept, passages, _ in recorded:
        by_doc.setdefault(passages[0]["id"].split(":")[0], []).append((concept, passages))
    combo_ins = []
    for concepts in by_doc.values():
        names = [c for c, _ in concepts][:3]
        if len(names) < 3:
            continue
        labels = [label([names[1], names[0]]), label([names[2], names[1]]), label([names[2], names[0]])]
        combo_ins.append(base._tokens(build_combo_prompt(labels[:MULTI_CONCEPT_COMBOS_PER_CALL], concepts[0][1])))
    per_format = {
        fmt: statistics.mean(
            base._tokens(i.model_dump_json()) for _, _, o in recorded for i in o.items if i.format == fmt
        )
        for fmt in CHECK_ITEM_FORMATS
    }
    combo_items = MULTI_CONCEPT_COMBOS_PER_CALL * len(CHECK_ITEM_FORMATS)
    combo_out = MULTI_CONCEPT_COMBOS_PER_CALL * sum(per_format.values())
    combo_in = statistics.mean(combo_ins)
    component_lines = combo_items * COMPONENTS_PER_COMBINATION * base._tokens("COMPONENT k1: a concept name\n")
    Call = base.Call
    return {
        "prefixes": prefixes,
        "plain": Call("check_items", prefixes["check_items"], plain_in, plain_out, samples=len(recorded)),
        "varied": Call("check_items", prefixes["varied"], varied_in, varied_out, samples=len(recorded)),
        "varied_redraft": Call("check_items", prefixes["varied"], varied_in_used, varied_out),
        "combo": [
            Call("check_items", prefixes["combo"], combo_in, combo_out, samples=len(combo_ins)),
            Call(
                "check_items_verify", prefixes["combo_verify"], combo_out + component_lines,
                combo_items * (PER_ITEM_VERDICT + COMPONENTS_PER_COMBINATION * PER_COMPONENT_VERDICT),
            ),
            Call("check_items_solve", prefixes["solve"], combo_in, combo_items * PER_ITEM_VERDICT),
        ],
    }


def base_agent():
    from agents.check_items import check_items_agent

    return check_items_agent


def solve_agent():
    from agents.check_items_solve import check_items_solve_agent

    return check_items_solve_agent


def project(measured: dict, mix: dict[str, str], cached: bool) -> dict[str, float]:
    """Per upload: A140's added cost (the varied drafter in place of the plain
    one on every drafting call), A141's (its combination calls and their
    checks); per student-month at the base script's uploads."""
    from learning.params import MULTI_CONCEPT_COMBOS_PER_CALL, MULTI_CONCEPT_COMBOS_PER_DOC

    base = _base()
    batches = math.ceil(base.UPLOAD_CONCEPTS / 3)
    plain, _ = base.call_cost(measured["plain"], mix["check_items"], cached=cached, calls=batches)
    varied, _ = base.call_cost(measured["varied"], mix["check_items"], cached=cached, calls=batches)
    redraft, _ = base.call_cost(measured["varied_redraft"], mix["check_items"], cached=cached, calls=batches)
    combo_calls = math.ceil(MULTI_CONCEPT_COMBOS_PER_DOC / MULTI_CONCEPT_COMBOS_PER_CALL)
    combos = sum(
        base.call_cost(call, mix[call.slot], cached=cached, calls=combo_calls)[0]
        for call in measured["combo"]
    )
    month = (varied - plain + combos) * base.UPLOADS_PER_STUDENT_MONTH
    return {
        "a140": varied - plain,
        "a140_redraft": redraft - plain,
        "a141": combos,
        "month": month,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--steady-traffic", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args(argv)
    base = _base()
    base._guard()
    base.STEADY_TRAFFIC = args.steady_traffic
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(base.EVALS))
    from learning.params import LOOP_COST_TARGET_USD_PER_STUDENT_MONTH as target

    measured = measure()
    head = ["mix", "caching", "A140 per upload", "A140 re-draft", "A141 per upload",
            "both per student-month", "of the target"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] if args.markdown else ["  ".join(head)]
    for name, mix in base.mixes().items():
        for cached in (False,) if name.startswith("today") else (False, True):
            r = project(measured, mix, cached)
            cells = [name, "on" if cached else "off", f"${r['a140']:.4f}", f"${r['a140_redraft']:.4f}",
                     f"${r['a141']:.4f}", f"${r['month']:.4f}", f"{100 * r['month'] / target:.1f}%"]
            lines.append(("| " + " | ".join(cells) + " |") if args.markdown else "  ".join(cells))
    print("\n".join(lines))
    print()
    print("static prefixes (tokens, chars/4):", json.dumps(measured["prefixes"], sort_keys=True))
    for name in ("plain", "varied", "varied_redraft"):
        call = measured[name]
        print(f"  {name:15} {call.slot:20} prefix {call.prefix:5} input {call.input:7.0f} output {call.output:6.0f}")
    for call in measured["combo"]:
        print(f"  {'combination':15} {call.slot:20} prefix {call.prefix:5} input {call.input:7.0f} output {call.output:6.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
