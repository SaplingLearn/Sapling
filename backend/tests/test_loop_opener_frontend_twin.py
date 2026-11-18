"""The learning loop's probe-phase opener is one fact kept in two places: the
backend serves it as the session's first assistant row (learning/turn_shape.py
LOOP_PROBE_OPENER / LOOP_PLAN_OPENER, spec §13 A121), and the Tutor's teaching
log (frontend/src/components/learn/loopHistory.ts PROBE_PHASE_OPENERS)
recognises that row to show the approved plan in its place once the check-in
and the plan are done (PR #866 review U2). If the copy drifts, the log would
again open on "We'll start with a quick check-in…" after the check-in, so this
pins the two together."""
from pathlib import Path

from learning.turn_shape import LOOP_PLAN_OPENER, LOOP_PROBE_OPENER
from services.loop.constants import _LOOP_OPENER_TEMPLATE

LOOP_HISTORY_TS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "learn" / "loopHistory.ts"
)


def _ts_string(text: str) -> str:
    """`text` as the frontend file spells it: a double-quoted TS literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def test_every_probe_phase_opener_is_known_to_the_frontend():
    src = LOOP_HISTORY_TS.read_text(encoding="utf-8")
    block = src.split("PROBE_PHASE_OPENERS", 1)[1].split("];", 1)[0]
    for opener in (LOOP_PROBE_OPENER, LOOP_PLAN_OPENER, _LOOP_OPENER_TEMPLATE):
        assert _ts_string(opener) in block, f"frontend PROBE_PHASE_OPENERS is missing {opener!r}"


def test_the_frontend_lists_no_opener_the_backend_does_not_serve():
    src = LOOP_HISTORY_TS.read_text(encoding="utf-8")
    block = src.split("PROBE_PHASE_OPENERS", 1)[1].split("];", 1)[0]
    listed = [line.strip().rstrip(",") for line in block.splitlines() if line.strip().startswith('"')]
    assert sorted(listed) == sorted({_ts_string(LOOP_PROBE_OPENER), _ts_string(LOOP_PLAN_OPENER)})
