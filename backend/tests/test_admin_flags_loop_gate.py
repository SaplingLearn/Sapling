"""#866 K24: the admin Flags page reports a learning-loop flag as the student is
served it, never only as the flag store resolves it.

The loop's flags sit under its gate (learning/gate.py): the env kill switch
LEARNING_LOOP_ENABLED turns the loop off for everyone with no read, and every
other loop flag acts only where the student's own `learning_loop` flag is on
(each reader sits behind the loop's route-entry gate or reads it first). The
admin "Check a student" answer (GET /api/admin/flags/{key}/explain) resolved
only the flag itself, so under the kill switch it said "On: the default for
everyone" while every loop route 404'd, and a quiz flag read "On" for a student
who never sees the quiz features. The list rows showed the stored default the
same way.

Now: the explain answer follows the code's order (the kill switch, then the
student's learning_loop flag, then the flag's own rules), with the
learning_loop answer behind a "requires"; the list carries, per flag, the flag
it needs (`requires`) and what every student gets whatever is stored
(`forced`: the kill switch, a SAPLING_FLAG_ override). A flag the loop does not
gate answers exactly as before.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import config
from learning import gate as loop_gate
from services.feature_flags import REGISTRY
from tests.test_admin_flags_routes import _DB, _run, client

BACKEND = Path(__file__).resolve().parents[1]
EXPLAIN = "/api/admin/flags/{key}/explain?user_id=u1"


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for key in REGISTRY:
        monkeypatch.delenv(f"SAPLING_FLAG_{key.upper()}", raising=False)
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)


def _db(**flags):
    """Stored defaults, plus user rules as {key: variant} for u1 in `rules`."""
    db = _DB()
    rules = flags.pop("rules", {})
    for key, variant in flags.items():
        db.flags[key] = {"key": key, "default_variant": variant, "rollout_percent": 0,
                         "rollout_variant": None, "updated_at": None, "updated_by": None}
    for key, variant in rules.items():
        db.targets[(key, "user", "u1")] = {"flag_key": key, "target_type": "user",
                                            "target_id": "u1", "variant": variant}
    return db


def _explain(db, key):
    r, _ = _run(db, lambda: client.get(EXPLAIN.format(key=key)))
    assert r.status_code == 200, r.text
    return r.json()


def _rows(db):
    r, _ = _run(db, lambda: client.get("/api/admin/flags"))
    assert r.status_code == 200, r.text
    return {f["key"]: f for f in r.json()["flags"]}


KILL = {"variant": "off", "step": "kill_switch", "detail": "LEARNING_LOOP_ENABLED"}


def test_the_kill_switch_answers_for_the_loop_flag_whatever_is_stored(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    db = _db(learning_loop="on", rules={"learning_loop": "on"})
    assert _explain(db, "learning_loop") == KILL


def test_the_kill_switch_answers_for_every_loop_flag(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    db = _db(learning_loop="on", quiz_concept_plan="on", rules={"item_reports": "on"})
    assert _explain(db, "quiz_concept_plan") == KILL
    assert _explain(db, "item_reports") == KILL


def test_the_kill_switch_beats_an_env_override(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "on")
    monkeypatch.setenv("SAPLING_FLAG_QUIZ_CONCEPT_PLAN", "on")
    db = _db()
    assert _explain(db, "learning_loop") == KILL
    assert _explain(db, "quiz_concept_plan") == KILL


def test_a_loop_flag_is_off_for_a_student_without_the_loop_and_says_why():
    db = _db(learning_loop="off", rules={"quiz_concept_plan": "on"})
    assert _explain(db, "quiz_concept_plan") == {
        "variant": "off", "step": "requires", "detail": "learning_loop",
        "master": {"key": "learning_loop", "variant": "off", "step": "default", "detail": "stored default"},
    }


def test_the_loop_forced_off_by_its_env_override_is_named(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "off")
    db = _db(learning_loop="on", quiz_concept_plan="on")
    assert _explain(db, "quiz_concept_plan")["master"] == {
        "key": "learning_loop", "variant": "off", "step": "env_override", "detail": "SAPLING_FLAG_LEARNING_LOOP",
    }


def test_with_the_loop_on_a_loop_flag_answers_by_its_own_rules():
    db = _db(rules={"learning_loop": "on", "quiz_concept_plan": "on"})
    assert _explain(db, "quiz_concept_plan") == {"variant": "on", "step": "user", "detail": "u1"}
    assert _explain(db, "learning_loop") == {"variant": "on", "step": "user", "detail": "u1"}
    db = _db(rules={"learning_loop": "on"})
    assert _explain(db, "quiz_concept_plan") == {"variant": "off", "step": "default", "detail": "no stored configuration"}


def test_a_flag_the_loop_does_not_gate_answers_as_before(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    db = _db(hide_quiz="on", crisis_support="on")
    assert _explain(db, "hide_quiz") == {"variant": "on", "step": "default", "detail": "stored default"}
    assert _explain(db, "crisis_support") == {"variant": "on", "step": "default", "detail": "stored default"}


def test_the_list_names_what_each_flag_needs_and_what_everyone_gets(monkeypatch):
    db = _db(learning_loop="on", quiz_concept_plan="on")
    rows = _rows(db)
    assert rows["quiz_concept_plan"]["requires"] == "learning_loop"
    assert rows["learning_loop"]["requires"] is None and rows["hide_quiz"]["requires"] is None
    assert all(row["forced"] is None for row in rows.values())  # nothing above the stored settings

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    rows = _rows(db)
    assert rows["learning_loop"]["forced"] == KILL
    assert rows["quiz_concept_plan"]["forced"] == KILL
    assert rows["learning_loop"]["default_variant"] == "on"  # the stored setting stays visible
    assert rows["hide_quiz"]["forced"] is None and rows["crisis_support"]["forced"] is None


def test_the_list_names_an_env_override_of_the_loop(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "off")
    rows = _rows(_db(learning_loop="on", quiz_concept_plan="on"))
    assert rows["learning_loop"]["forced"] == {
        "variant": "off", "step": "env_override", "detail": "SAPLING_FLAG_LEARNING_LOOP",
    }
    assert rows["quiz_concept_plan"]["forced"] == {
        "variant": "off", "step": "requires", "detail": "learning_loop",
        "master": {"key": "learning_loop", "variant": "off", "step": "env_override",
                   "detail": "SAPLING_FLAG_LEARNING_LOOP"},
    }
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "on")
    rows = _rows(_db())
    assert rows["learning_loop"]["forced"] == {
        "variant": "on", "step": "env_override", "detail": "SAPLING_FLAG_LEARNING_LOOP",
    }
    assert rows["quiz_concept_plan"]["forced"] is None  # still its own settings, per student


def test_a_loop_flags_own_env_override_holds_only_where_the_loop_is_on(monkeypatch):
    """SAPLING_FLAG_<KEY>=on for a loop flag forces it for students with the
    loop on; a student without it still gets off, so the row must not claim
    "on for every student" unless learning_loop is forced on too."""
    monkeypatch.setenv("SAPLING_FLAG_QUIZ_CONCEPT_PLAN", "on")
    db = _db(learning_loop="off", quiz_concept_plan="off")
    on_override = {"variant": "on", "step": "env_override", "detail": "SAPLING_FLAG_QUIZ_CONCEPT_PLAN"}
    assert _rows(db)["quiz_concept_plan"]["forced"] == {**on_override, "only_with": "learning_loop"}
    assert _explain(db, "quiz_concept_plan")["step"] == "requires"  # u1 has no loop: off

    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "on")
    assert _rows(db)["quiz_concept_plan"]["forced"] == on_override  # now truly everyone

    monkeypatch.delenv("SAPLING_FLAG_LEARNING_LOOP")
    monkeypatch.setenv("SAPLING_FLAG_QUIZ_CONCEPT_PLAN", "off")
    assert _rows(db)["quiz_concept_plan"]["forced"] == {  # off holds whatever the loop says
        "variant": "off", "step": "env_override", "detail": "SAPLING_FLAG_QUIZ_CONCEPT_PLAN",
    }


def test_the_list_reads_no_flag_for_the_forced_answer(monkeypatch):
    """`forced` is the environment only: the kill switch costs no read."""
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    monkeypatch.setattr(loop_gate, "explain", lambda *a, **k: pytest.fail("read a flag"))
    assert loop_gate.forced_for_everyone("quiz_concept_plan").resolution.step == "kill_switch"


# ── which flags the loop gates ──────────────────────────────────────────────

EXPECTED_LOOP_FLAGS = {
    "item_reports", "retention_due_badge", "probe_matched_pretest", "upload_prereq_edges",
    "loop_tutor_v2", "help_gate_strict", "segment_prequestion", "self_explanation_prompts",
    "next_probe_hint",
    "varied_isomorphs", "multi_concept_items", "quiz_concept_plan", "quiz_planned_questions",
    "quiz_item_gates", "quiz_misconceptions", "quiz_results_routing",
    "skill_ladder",  # the graph route reads it after the loop's gate (routes/graph.py)
    "hint_ladder",  # a loop UI flag: the check card only renders with the loop on
    "verdict_v2",  # a loop UI flag: the verdict only renders with the loop on
}


def test_the_loop_flags_are_registered_and_pinned():
    assert set(loop_gate.LOOP_FLAGS) == EXPECTED_LOOP_FLAGS
    assert set(loop_gate.LOOP_FLAGS) <= set(REGISTRY)
    assert loop_gate.LEARNING_LOOP_FLAG not in loop_gate.LOOP_FLAGS
    # crisis support serves every AI surface, the legacy tutor's too: never gated
    assert "crisis_support" not in loop_gate.LOOP_FLAGS


def _flag_constants() -> dict[str, str]:
    """Every module-level NAME = "<registered flag key>" in the backend."""
    out: dict[str, str] = {}
    for top in ("services", "learning", "agents", "routes"):
        for path in (BACKEND / top).rglob("*.py"):
            for node in ast.parse(path.read_text()).body:
                if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                        and node.value.value in REGISTRY):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            out[target.id] = node.value.value
    return out


def test_every_flag_the_loop_package_reads_is_a_loop_flag():
    """A flag read inside services/loop/ (the loop routes' bodies, behind the
    route-entry gate) acts only where the loop is on: it must be in
    LOOP_FLAGS, or the admin page would report it on for students the loop
    never serves."""
    constants = _flag_constants()
    read: set[str] = set()
    for path in (BACKEND / "services" / "loop").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("flag_on", "flag_variant"):
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Constant) and arg.value in REGISTRY:
                    read.add(arg.value)
                elif isinstance(arg, ast.Name) and arg.id in constants:
                    read.add(constants[arg.id])
                elif isinstance(arg, ast.Attribute) and arg.attr in constants:
                    read.add(constants[arg.attr])
    assert read, "no flag read found in services/loop/ (moved? re-point this scan)"
    assert read <= set(loop_gate.LOOP_FLAGS), read - set(loop_gate.LOOP_FLAGS)
