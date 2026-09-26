# PKG-03 evidence-state — Learning Loop series (4 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the three hand-offs it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-03 `evidence-state`.** After this package: the `Evidence` model exists and carries every §3.1 weight as a derived number; the `learner_state` table exists and is read decayed and written from exactly one place; `services/graph_service.py::apply_graph_update` is the single BKT + FSRS writer — a `graph_update["evidence"]` list drives BKT update, one-hop prerequisite propagation, the `graph_nodes` mirror, one `node_mastery_events` row per evidence, and the FSRS state transition; a payload without `evidence` produces the byte-identical table-call trace it produced before this package. `tests/test_learning_evidence_apply.py` and the now-real `test_inv_01_single_graph_writer` prove it. Nothing calls the evidence path yet.

Branch: `feat/learning-loop-03-evidence-state`. PR title: `feat(learning): PKG-03 evidence-state`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows `00`, `01`, `02` must be `done` or `verified`. This package marks `01` and `02` `verified` after its State-of-the-world rows pass.
2. `docs/superpowers/plans/learning-loop/HANDOFF-01.md` and `HANDOFF-02.md` §Symbols added — the EXACT signatures of `bkt.update`, `bkt.decayed_p`, `bkt.propagate_prereq`, `bkt.tier_for`, `params.CHANNELS`, `fsrs.rating_for`, `fsrs.next_state`, and the FSRS state type. §Spec/Interfaces consumed below lists what this prompt ASSUMES; where a hand-off differs, the hand-off wins and you adapt the one named adapter, never the pure module.
3. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.1 (weights table, update with `w`, decay at read, propagation, tier mirror), §3.2 (rating map only), §3.3 "Evidence mapping by rung", §4 PKG-03 block, §5, §8 invariant 1.
5. `docs/superpowers/plans/learning-loop/README.md` — series conventions, especially "Touching an earlier package's code".
6. `docs/superpowers/plans/learning-loop/HANDOFF-template.md` — what you write at the end.
7. Code you will modify: `backend/services/graph_service.py:637–681` (`_insert_mastery_event`, retry semantics you keep) and `:683–911` (`apply_graph_update`; the `updated_nodes` loop at :759–839 is the shape you mirror; `existing_rows` at :697 is the ownership read you reuse); `backend/learning/evidence.py`, `backend/learning/learner_state.py` (docstring-only stubs); `backend/learning/params.py` (PKG-01's; two † constants, Task 3); `backend/tests/test_learning_loop_invariants.py::test_inv_01_single_graph_writer` (placeholder).
8. Code you will mirror: `backend/tests/test_graph_service.py:25–68` and `:469–560` (mock factories, the echo-back `upsert`, `patch("services.graph_service.table", side_effect=factory)`); `backend/db/connection.py:31–55` and `:92–112` (`select`/`update`/`upsert` signatures); `backend/tests/test_document_index_status_migration.py:1–40` (migration-invariant test style); `backend/agents/tools/graph_read.py:233–248` (two reads because the filter dict has no OR across columns); `backend/config.py:113–125` (legacy tiers — stay for the legacy path).
9. Research, only these: `docs/research/learning-loop/AI tutor learning loop research.md` §"Replace the scalar mastery score with per-channel BKT plus decay", lines 50–56 (worked example, decay-at-read composition, one-hop asymmetric propagation, strong-channel mastery rule); `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" lines 148–158 (`STATE` block: `streak_unassisted`, `opps`) and lines 205–214 (`EVIDENCE MAPPING`).

## State of the world

Verify the base before Task 1. Every row must be green.

| check | command | expected |
|---|---|---|
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped` (later packages raise the passed count) |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-01 | `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q` | N passed (N ≥ 20) |
| PKG-01 | `grep -cE "^def (update\|decayed_p\|propagate_prereq\|band\|tier_for)\(" backend/learning/bkt.py` | `5` |
| PKG-01 | `grep -cE "^[A-Z0-9_]+ = " backend/learning/params.py` | ≥ 40 |
| PKG-01 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_03` | `1 passed` |
| PKG-02 | `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q` | N passed (N ≥ 15) |
| PKG-02 | `grep -cE "^def (retrievability\|interval\|next_state\|rating_for\|order_due\|budget_select)\(" backend/learning/fsrs.py` | `6` |
| PKG-02 | `cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')"` | `ok` |
| this package's stubs are stubs | `wc -l backend/learning/evidence.py backend/learning/learner_state.py backend/tests/test_learning_evidence_apply.py` | each ≤ 5 lines |
| no migration for this package yet | `ls backend/db/migrations/*_learning_learner_state.sql 2>/dev/null` | empty |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` timestamped file; your migration's prefix must sort after it |
| graph tests green and pinned | `cd backend && venv/bin/python -m pytest tests/test_graph_service.py tests/test_graph_add_node.py tests/test_mastery_tier_unification.py -q` | all passed |

(The `\|` in the grep patterns above is a Markdown-table escape; type a plain `|` in the shell.)

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. A red PKG-01/02 row is that package's bug: fix it as a separate first commit `fix(learning-loop): PKG-0N — <what>`, add a ledger row `0N | reopened`, append "Post-hoc changes" to `HANDOFF-0N.md`, then continue.

## Spec

### Behaviour

1. `learning.evidence.Evidence` is the spec §5 Pydantic model, field for field, plus: `max_rung` bounded `0..LADDER_MAX_RUNG`; `channel == "idk"` with `correct == True` is a `ValidationError`; `max_rung ≥ 1` forces `assisted = True` (rungs unlock in order — PKG-06 gates — so any rung means H1 was used). `Channel` is the `Literal` of the six spec channel names. `evidence_weight(ev) -> float` is the product of the applicable §3.1 weights computed from the FLAGS: `WEIGHT_ASSISTED` when `correct and assisted`; `WEIGHT_SAME_SESSION_RECHECK` when `same_session_recheck`; `WEIGHT_LOW_CONFIDENCE` when `confidence is not None and confidence < GRADER_LOW_CONFIDENCE`; `0.0` (no upward evidence, spec §3.3) when `correct and max_rung ≥ EVIDENCE_NO_UPWARD_MIN_RUNG`. The `weight` field on an INPUT `Evidence` is ignored; `apply_graph_update` journals `evidence_weight(ev)`. A wrong answer at any rung is a standard incorrect observation (`WEIGHT_ASSISTED` never applies to an incorrect answer).
2. `learning.learner_state.LearnerState` is a dataclass mirroring the `learner_state` columns plus `exists: bool`. `read_states(user_id, node_ids, now=None) -> dict[node_id, LearnerState]` does ONE `table("learner_state").select(...)` with `node_id=in.(...)` and returns each row DECAYED: `p_known = bkt.decayed_p(p_stored, elapsed_days, fsrs_s or FSRS_S0_GOOD)`, `elapsed_days = (now − last_evidence_at) / timedelta(days=1)` (0 when null or in the future). `read_state(user_id, node_id, now=None)` is the single-row form; no row → `LearnerState(p_known=BKT_L0, counters 0, fsrs None, exists=False)`. `write_state(state, now=None)` upserts on `on_conflict="user_id,node_id"` with `updated_at = now`; the payload NEVER names `htc_k`, `unassisted_next`, `assist_gap`, `in_zone` (PKG-06 derives them; merge-duplicates would null them). `write_state` is called from `services/graph_service.py` only (invariant 1).
3. `apply_graph_update(user_id, graph_update, course_id=None)`: when `graph_update.get("evidence")` is truthy, every item is validated as `Evidence` FIRST (a `ValidationError` raises before any read or write); then, after the `updated_nodes` loop and before the streak touch, `_apply_evidence(...)` runs per evidence in list order:
   1. ownership: the node must be in `existing_rows` (the user-scoped, course-scoped read at :697, keyed by `id`); a missing node → WARNING, skipped, never written;
   2. same-session recheck: within one call, a later evidence whose `(session_id, question_hash)` (both non-null) equals an earlier one's is treated as `same_session_recheck=True`;
   3. `w = evidence_weight(ev)`; `p_before` = decayed `p_known` from an in-call state cache seeded by ONE `read_states` over all evidence node ids (a second evidence on the same node in one call sees the first's posterior); `p_after = bkt.update(p_before, channel, correct, weight=w)` when `w > 0`, else `p_before`;
   4. counters (spec §3.3, ZPD `STATE`): `opps += 1` always; `unassisted = not assisted and max_rung == 0`; `correct and unassisted` → `streak_unassisted += 1` and, when `is_strong_channel(channel)`, `n_strong_unassisted += 1`; otherwise `streak_unassisted = 0` (a streak is CONSECUTIVE unassisted first-attempt corrects, ZPD line 156; † see Deviations); `last_evidence_at = now`;
   5. FSRS: `rating = fsrs.rating_for(channel, correct, max_rung)` → `fsrs.next_state(...)` (adapter `_fsrs_after`) → `fsrs_d`, `fsrs_s`, `fsrs_last_review_at = now`, `fsrs_due_at`; then `write_state(state)`;
   6. mirror `graph_nodes` (`mastery_score = p_after`, `mastery_tier = bkt.tier_for(p_after)`, `times_studied + 1`, `last_studied_at`); journal exactly ONE `_insert_mastery_event(row)` with `event_type="evidence"`, `delta = p_after − p_before`, `reason = f"evidence:{channel}"`, and every new column always present (null when None) — `_insert_mastery_event` itself is not modified; append `{"concept", "before": p_before, "after": p_after}` to `mastery_changes` and the node's `course_id` to `touched_courses`, so `touch_streak_safe`, `update_course_context`, and the achievement dispatch fire exactly as on the legacy path;
   7. propagation: prerequisite edges touching the node are read (two user-scoped `graph_edges` selects, `relationship_type=eq.prerequisite`, one per endpoint column); `bkt.propagate_prereq(...)` (adapter `_propagation_targets`) yields `(target_node_id, correct)` pairs — parents on a correct answer, children on an incorrect one, direction per `EDGE_PREREQ_SOURCE_IS_PREREQ`; each target in `existing_rows` gets `bkt.update(p, PROPAGATION_CHANNEL, correct, weight=WEIGHT_PROPAGATION)` on its decayed state, `last_evidence_at = now`, `write_state`, and a mirror of `mastery_score` + `mastery_tier` ONLY. Propagated updates touch no counters, no FSRS, no journal row, no `mastery_changes` entry (they are reproducible from the journaled evidence). Targets outside `existing_rows` are skipped.
4. When `graph_update` has no `evidence` key, or it is `[]`/`None`, no line of the new code runs: the sequence of `table(...)` calls, their arguments, and the return value are identical to the pre-package code. Task 5's trace test is green on `main` before the change and green after.
5. Legacy tiers (`config.get_mastery_tier`) stay on the `new_nodes`/`updated_nodes` paths; `bkt.tier_for` is used ONLY in `_apply_evidence`. `tests/test_mastery_tier_unification.py` is untouched.
6. Flag: this package adds no caller. Nothing under `backend/routes/`, `backend/agents/`, `backend/services/` (other than `graph_service.py`) builds a `graph_update` with an `"evidence"` key — proven by `test_no_production_caller_passes_evidence_yet` (Task 6), which PKG-05 deletes when it wires `graded_check_tool`. With `LEARNING_LOOP_ENABLED` unset, and with it set, every request path is byte-identical to before.

### Schema (exact)

```sql
-- <ts>_learning_learner_state.sql
-- Learning loop series PKG-03: per-(user, concept) BKT/FSRS state and the
-- evidence columns on the mastery journal. Spec §4 PKG-03 block, verbatim.
-- Deploy order: this migration BEFORE the code (apply_graph_update names the
-- new node_mastery_events columns and the learner_state table).
CREATE TABLE IF NOT EXISTS learner_state (
  user_id            text NOT NULL,
  node_id            text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  p_known            double precision NOT NULL,
  n_strong_unassisted int NOT NULL DEFAULT 0,
  streak_unassisted  int NOT NULL DEFAULT 0,
  opps               int NOT NULL DEFAULT 0,
  fsrs_d             double precision,
  fsrs_s             double precision,
  fsrs_last_review_at timestamptz,
  fsrs_due_at        timestamptz,
  htc_k              double precision,
  unassisted_next    double precision,
  assist_gap         double precision,
  in_zone            boolean,
  last_evidence_at   timestamptz,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, node_id)
);
CREATE INDEX IF NOT EXISTS learner_state_due_idx ON learner_state (user_id, fsrs_due_at);
ALTER TABLE node_mastery_events
  ADD COLUMN IF NOT EXISTS channel text,
  ADD COLUMN IF NOT EXISTS correct boolean,
  ADD COLUMN IF NOT EXISTS weight double precision,
  ADD COLUMN IF NOT EXISTS assisted boolean,
  ADD COLUMN IF NOT EXISTS max_rung smallint,
  ADD COLUMN IF NOT EXISTS p_before double precision,
  ADD COLUMN IF NOT EXISTS p_after double precision,
  ADD COLUMN IF NOT EXISTS session_id text,
  ADD COLUMN IF NOT EXISTS check_item_id text,
  ADD COLUMN IF NOT EXISTS question_hash text,
  ADD COLUMN IF NOT EXISTS confidence double precision;
-- evidence rows use event_type = 'evidence'; delta = p_after - p_before keeps legacy readers valid.
```

### Named constants

Consumed from `backend/learning/params.py` (PKG-01) — cite by name, never re-declare:

| Name | Value | Spec | Used for |
|---|---|---|---|
| `BKT_L0` | 0.35 | §3.1 | default `p_known` when no row; decay target |
| `WEIGHT_ASSISTED` | 0.5 | §3.1 | `evidence_weight` when `correct and assisted` |
| `WEIGHT_SAME_SESSION_RECHECK` | 0.5 | §3.1 | `evidence_weight` when `same_session_recheck` |
| `WEIGHT_PROPAGATION` | 0.5 | §3.1 | one-hop propagation observation weight |
| `WEIGHT_LOW_CONFIDENCE` | 0.5 | §3.1 | `evidence_weight` when `confidence < GRADER_LOW_CONFIDENCE` |
| `GRADER_LOW_CONFIDENCE` | 0.6 | §3.4 | the low-confidence cut |
| `FSRS_S0_GOOD` | `FSRS_W[2]` | §3.2 | stability for decay when no FSRS state |
| `EDGE_PREREQ_SOURCE_IS_PREREQ` | `True` | §3.1 | edge direction (inside `bkt.propagate_prereq`) |
| `CHANNELS` | table | §3.1 | `strong` flag per channel → `is_strong_channel` |
| `TIER_UNEXPLORED_MAX`, `BAND_NOVICE_MAX`, `BKT_PROFICIENT` | 0.10 / 0.30 / 0.95 | §3.1 | inside `bkt.tier_for`; only called here |

Added to `backend/learning/params.py` by this package (Task 3; a post-hoc change to PKG-01's file, recorded per README):

| Name | Value | Spec | Note |
|---|---|---|---|
| `EVIDENCE_NO_UPWARD_MIN_RUNG` | 4 | §3.3 "correct after H4–H6 → no upward BKT evidence" | † the rung number is in the spec text but had no name |
| `LADDER_MAX_RUNG` | 6 | §5 `max_rung: int = 0  # 0..6`; §3.3 ladder H0..H6 | † PKG-06's `Rung` enum reuses it |

Non-numeric module constants in `learning/evidence.py`: `PROPAGATION_CHANNEL = "chat_turn"` (§3.1), `EVIDENCE_EVENT_TYPE = "evidence"` (§4 comment), `PREREQ_RELATIONSHIP_TYPE = "prerequisite"` (§3.1).

### Interfaces consumed (ASSUMED — verify against HANDOFF-01/02 before Task 4)

| Symbol | Assumed signature | If different |
|---|---|---|
| `bkt.update` | `update(p: float, channel: str, correct: bool, weight: float = 1.0) -> float` (posterior + learn step only when `weight == 1.0`) | adapt the call in `_apply_evidence`; the `w > 0` branch already avoids `weight=0.0` |
| `bkt.decayed_p` | `decayed_p(p_stored: float, elapsed_days: float, stability: float) -> float` | adapt `learner_state._from_row` |
| `bkt.propagate_prereq` | `propagate_prereq(node_id: str, correct: bool, edges: list[tuple[str, str]]) -> list[tuple[str, bool]]` — `edges` are `(source_node_id, target_node_id)` prerequisite pairs; returns `(target, correct)` for parents on correct / children on incorrect, honoring `EDGE_PREREQ_SOURCE_IS_PREREQ` | adapt `_propagation_targets` only |
| `bkt.tier_for` | `tier_for(p: float) -> str` (`unexplored/struggling/learning/mastered`) | none expected |
| `params.CHANNELS` | mapping `channel -> object with .strong` (or `["strong"]`) | adapt `is_strong_channel` only |
| `fsrs.rating_for` | `rating_for(channel: str, correct: bool, max_rung: int) -> int` (1..4) | none expected |
| `fsrs.next_state` | `next_state(state: FsrsState \| None, rating: int, now: datetime) -> FsrsState`, `FsrsState(d, s, last_review_at, due_at)`; retention defaults to `FSRS_RETENTION_DEFAULT`; the `mc` stability cap is applied inside fsrs (if HANDOFF-02 exposes a `channel=`/`stability_gain_cap=` kwarg instead, pass it from `_fsrs_after`) | adapt `_fsrs_after` only |

Record every adaptation in the hand-off under Deviations with the actual signature.

### Invariants asserted by this package (spec §8 numbering)

- (1) No `table("graph_nodes"|"graph_edges"|"node_mastery_events"|"learner_state")…​.insert(|.update(|.upsert(` chain anywhere under `backend/` except `services/graph_service.py`, excluding `tests/`, `venv/`, `db/archive/`, `db/e2e_checks/`, and `db/seed_*.py` (fixtures and seeds, not application code — `db/e2e_checks/quiz.py:21` and `db/archive/seed.py:63` write nodes today and are exempt by path). `write_state` is referenced only from `learning/learner_state.py` (definition) and `services/graph_service.py`, and inside `graph_service.py` only within `apply_graph_update` or `_apply_evidence` (AST check).

Invariants 2, 7, 8 (PKG-00) keep passing: `learner_state.py` imports `db.connection` and is not in `PURE_MODULES`; the new migration matches the name rule.

### Error semantics

- An invalid evidence dict raises `pydantic.ValidationError` from `apply_graph_update` before any read or write. Callers (PKG-05's route) own the 4xx mapping.
- An evidence for a node the user does not own (not in `existing_rows`) is skipped with `graph: evidence skipped node=%s user=%s (not owned or outside course)` at WARNING; never a write, never a raise.
- `_insert_mastery_event` keeps its retry-without-`event_type` semantics unchanged. On an environment that took the code before the migration, the `learner_state` upsert fails first (unknown table) and raises out of `apply_graph_update`; that is the intended signal — migration before code (the migration's header says so) and PKG-05 is the first caller.
- `read_states` never swallows: a PostgREST error propagates (there is no honest default for "the store is down").
- No agent runs in this package; no ADR 0024 degrade path is touched.

### Events added

None. `EVENT_TAXONOMY` is untouched (PKG-06 adds `zpd.*`). `node_mastery_events.event_type = 'evidence'` is a journal column value, not an `events` row.

## Non-goals

- No caller: no route, agent, tool, or `SaplingDeps.pending_evidence` consumer (PKG-05, PKG-07). No `learning_loop_active` call.
- No band/ceiling/gate logic or `htc_k`/`unassisted_next`/`assist_gap`/`in_zone` derivation (PKG-06), no misconception record (PKG-10), no retention selection by exam window or set size (PKG-12; `next_state` runs at its default retention).
- No change to `bkt.py`, `fsrs.py`, any PKG-01/02 test, the legacy `new_nodes`/`updated_nodes`/`new_edges` code, `get_mastery_tier`, `quiz_config`, or `update_mastery_tool` (PKG-14 removes those). The only PKG-01 edit is the two † constants in `params.py`.
- No `report_empty_result` (`learner_state` reads are not agent read tools; empty is the normal "new concept" state). No batching beyond the one up-front `read_states`. No taxonomy change, no `chat_stream.py` change, no migration other than the one above.

## Tasks

### Task 1: Invariant 1 — single graph writer (real scan)

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (replace the `test_inv_01_single_graph_writer` placeholder; add `import ast` to the module imports; add the helpers next to `_imports_of`)

**Interfaces:**
- Consumes: filesystem under `backend/`, `ast`.
- Produces: the invariant every later package's writes are checked against.

- [ ] **Step 1: Replace the placeholder with the real test**

```python
GRAPH_TABLES = ("graph_nodes", "graph_edges", "node_mastery_events", "learner_state")
GRAPH_WRITER = "services/graph_service.py"
GRAPH_WRITER_FUNCS = ("apply_graph_update", "_apply_evidence")
INV01_EXEMPT_PREFIXES = ("tests/", "venv/", "db/archive/", "db/e2e_checks/")
_WRITE_CHAIN = re.compile(
    r'table\(\s*"(' + "|".join(GRAPH_TABLES) + r')"\s*\)\s*\.\s*(insert|update|upsert)\s*\('
)


def _application_py_files():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(INV01_EXEMPT_PREFIXES) or path.name.startswith("seed_"):
            continue
        yield rel, path


def _write_state_call_lines(path: pathlib.Path) -> list[int]:
    tree = ast.parse(path.read_text())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "write_state")
            or (isinstance(node.func, ast.Name) and node.func.id == "write_state")
        )
    ]


def test_inv_01_single_graph_writer():
    offenders: list[str] = []
    for rel, path in _application_py_files():
        text = path.read_text()
        if rel != GRAPH_WRITER:
            for m in _WRITE_CHAIN.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{rel}:{line} writes {m.group(1)} via .{m.group(2)}(")
        if rel not in (GRAPH_WRITER, "learning/learner_state.py") and "write_state" in text:
            offenders.append(f"{rel} references learner_state.write_state")
    assert offenders == [], "\n".join(offenders)

    # Inside the writer file, write_state may only be called from the two
    # named functions — the evidence path is a branch of apply_graph_update,
    # not a second entry point.
    writer = BACKEND / GRAPH_WRITER
    tree = ast.parse(writer.read_text())
    allowed = [
        (fn.lineno, fn.end_lineno)
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef) and fn.name in GRAPH_WRITER_FUNCS
    ]
    calls = _write_state_call_lines(writer)
    assert calls, "graph_service never calls write_state — PKG-03 not wired"
    for line in calls:
        assert any(lo <= line <= hi for lo, hi in allowed), (
            f"{GRAPH_WRITER}:{line} calls write_state outside {GRAPH_WRITER_FUNCS}"
        )
```

- [ ] **Step 2: Run to see the current state**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v -k inv_01`
Expected: FAIL — `AssertionError: graph_service never calls write_state — PKG-03 not wired`. The scan half must already be clean; if `offenders` lists a file, that is a pre-existing violation: STOP and record it in the ledger before continuing.

- [ ] **Step 3: Commit the red test**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-03 — real single-graph-writer invariant

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: Migration `learning_learner_state`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_learner_state.sql`
- Test: `backend/tests/test_learning_learner_state_migration.py`

**Interfaces:**
- Produces: table `learner_state`, index `learner_state_due_idx`, eleven nullable columns on `node_mastery_events`.

- [ ] **Step 1: Write the failing test**

```python
"""PKG-03 migration invariants. Live schema is proven by migration replay in
the E2E lane; this guards the properties graph_service depends on."""
import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"

NEW_EVENT_COLUMNS = (
    "channel", "correct", "weight", "assisted", "max_rung", "p_before", "p_after",
    "session_id", "check_item_id", "question_hash", "confidence",
)


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_learner_state.sql"))
    assert len(hits) == 1, f"expected exactly one learner_state migration, got {hits}"
    return hits[0].read_text()


def test_learner_state_table_is_keyed_per_user_and_node_and_cascades():
    sql = _migration()
    assert "CREATE TABLE IF NOT EXISTS learner_state" in sql
    assert re.search(r"PRIMARY KEY\s*\(\s*user_id\s*,\s*node_id\s*\)", sql)
    assert re.search(
        r"node_id\s+text\s+NOT NULL\s+REFERENCES\s+graph_nodes\(id\)\s+ON DELETE CASCADE", sql
    )


def test_p_known_is_required_and_counters_default_to_zero():
    sql = _migration()
    assert re.search(r"p_known\s+double precision\s+NOT NULL", sql)
    for col in ("n_strong_unassisted", "streak_unassisted", "opps"):
        assert re.search(rf"{col}\s+int\s+NOT NULL\s+DEFAULT\s+0", sql), col


def test_due_index_exists_for_the_scheduler():
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS learner_state_due_idx ON learner_state\s*\(\s*user_id\s*,\s*fsrs_due_at\s*\)",
        _migration(),
    )


def test_every_evidence_column_is_added_idempotently_and_nullable():
    sql = _migration()
    for col in NEW_EVENT_COLUMNS:
        m = re.search(rf"ADD COLUMN IF NOT EXISTS\s+{col}\s+[^,;]+", sql)
        assert m, col
        assert "NOT NULL" not in m.group(0), f"{col} must stay nullable for legacy writers"


def test_migration_prefix_is_a_utc_timestamp_after_pkg00():
    name = sorted(MIG_DIR.glob("*_learning_learner_state.sql"))[0].name
    assert re.fullmatch(r"\d{14}_learning_learner_state\.sql", name), name
    beta = sorted(MIG_DIR.glob("*_learning_loop_beta.sql"))[0].name
    assert name > beta, "must sort after PKG-00's migration"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_learner_state_migration.py -v`
Expected: 5 FAIL — `expected exactly one learner_state migration, got []`

- [ ] **Step 3: Write the migration**

Generate the prefix with `date -u +%Y%m%d%H%M%S`. File content is the SQL in §Spec/Schema, verbatim, including the header comment.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_learner_state_migration.py tests/test_learning_loop_invariants.py::test_inv_08_series_migrations_named_and_never_modified tests/test_migration_naming.py tests/test_migrations.py -q && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_learner_state.sql backend/tests/test_learning_learner_state_migration.py
git commit -m "feat(learning-loop): PKG-03 — learner_state table + evidence columns on node_mastery_events

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: `learning/evidence.py` — model, channel, weights

**Files:**
- Modify: `backend/learning/params.py` (append the two † constants; PKG-01's file — separate first commit)
- Create (replace stub): `backend/learning/evidence.py`
- Create (replace stub): `backend/tests/test_learning_evidence_apply.py` (this task writes the header and the `TestEvidenceModel`/`TestEvidenceWeight` classes; Tasks 4–6 append)

**Interfaces:**
- Consumes: `learning.params` names in §Named constants.
- Produces: `learning.evidence.Evidence`, `Channel`, `evidence_weight(ev) -> float`, `is_strong_channel(channel) -> bool`, `PROPAGATION_CHANNEL`, `EVIDENCE_EVENT_TYPE`, `PREREQ_RELATIONSHIP_TYPE`.

- [ ] **Step 1: Add the † constants to `params.py` and commit as a PKG-01 post-hoc change**

Append in the §3.3 block of `params.py`:

```python
# PKG-03 (†, spec §3.3 "correct after H4–H6 → no upward BKT evidence"; the
# rung number is in the spec text but had no name until the evidence model
# needed it). PKG-06's Rung enum reuses LADDER_MAX_RUNG.
EVIDENCE_NO_UPWARD_MIN_RUNG = 4
LADDER_MAX_RUNG = 6
```

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py tests/test_learning_loop_invariants.py -q -k "bkt or inv_03"` → all passed.

```
git add backend/learning/params.py
git commit -m "fix(learning-loop): PKG-01 — name EVIDENCE_NO_UPWARD_MIN_RUNG and LADDER_MAX_RUNG for PKG-03

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Add the ledger row `| 01 | bkt-core | reopened | feat/learning-loop-03-evidence-state | <sha> | 0 | — | HANDOFF-01.md |` and append to `HANDOFF-01.md` §Post-hoc changes: `PKG-03 <date>: added EVIDENCE_NO_UPWARD_MIN_RUNG=4 and LADDER_MAX_RUNG=6 to params.py — commit <sha>`. (Both files are committed with Task 7.)

- [ ] **Step 2: Write the failing tests**

```python
"""PKG-03: Evidence model + weights (spec §3.1, §5), learner_state access,
and apply_graph_update's evidence path (spec §5). Mocks follow
tests/test_graph_service.py::_bulk_factory."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from learning.params import (
    BKT_L0,
    EVIDENCE_NO_UPWARD_MIN_RUNG,
    GRADER_LOW_CONFIDENCE,
    LADDER_MAX_RUNG,
    WEIGHT_ASSISTED,
    WEIGHT_LOW_CONFIDENCE,
    WEIGHT_PROPAGATION,
    WEIGHT_SAME_SESSION_RECHECK,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


# ── Evidence model + weights ──────────────────────────────────────────────────


def _ev(**kw):
    from learning.evidence import Evidence

    base = {"node_id": "n1", "channel": "free_response", "correct": True}
    base.update(kw)
    return Evidence(**base)


class TestEvidenceModel:
    def test_minimal_defaults_match_spec(self):
        ev = _ev()
        assert (ev.assisted, ev.max_rung, ev.weight) == (False, 0, 1.0)
        assert ev.session_id is None and ev.check_item_id is None
        assert ev.question_hash is None and ev.confidence is None
        assert ev.same_session_recheck is False

    def test_channel_is_the_spec_literal(self):
        for channel in ("free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn", "idk"):
            _ev(channel=channel, correct=False)
        with pytest.raises(ValidationError):
            _ev(channel="vibes")

    def test_idk_cannot_be_correct(self):
        with pytest.raises(ValidationError, match="idk"):
            _ev(channel="idk", correct=True)

    def test_max_rung_bounded_and_any_rung_implies_assisted(self):
        with pytest.raises(ValidationError):
            _ev(max_rung=LADDER_MAX_RUNG + 1)
        with pytest.raises(ValidationError):
            _ev(max_rung=-1)
        assert _ev(max_rung=1).assisted is True


class TestEvidenceWeight:
    def test_unassisted_first_attempt_is_full_weight(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev()) == 1.0

    def test_assisted_correct_halves_but_assisted_wrong_is_standard(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(assisted=True, max_rung=2)) == WEIGHT_ASSISTED
        assert evidence_weight(_ev(correct=False, assisted=True, max_rung=3)) == 1.0

    def test_same_session_recheck_halves(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(same_session_recheck=True)) == WEIGHT_SAME_SESSION_RECHECK

    def test_low_confidence_halves_and_threshold_is_exclusive(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(confidence=GRADER_LOW_CONFIDENCE)) == 1.0
        assert evidence_weight(_ev(confidence=GRADER_LOW_CONFIDENCE - 0.01)) == WEIGHT_LOW_CONFIDENCE

    def test_weights_compose_as_a_product(self):
        from learning.evidence import evidence_weight

        ev = _ev(assisted=True, max_rung=1, same_session_recheck=True, confidence=0.1)
        assert evidence_weight(ev) == pytest.approx(
            WEIGHT_ASSISTED * WEIGHT_SAME_SESSION_RECHECK * WEIGHT_LOW_CONFIDENCE
        )

    def test_correct_after_worked_example_is_no_upward_evidence(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(max_rung=EVIDENCE_NO_UPWARD_MIN_RUNG)) == 0.0
        assert evidence_weight(_ev(max_rung=LADDER_MAX_RUNG)) == 0.0

    def test_input_weight_field_is_ignored(self):
        from learning.evidence import evidence_weight

        assert evidence_weight(_ev(weight=0.2)) == 1.0

    def test_strong_channels_match_spec_table(self):
        from learning.evidence import is_strong_channel

        assert {c for c in ("free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn", "idk")
                if is_strong_channel(c)} == {"free_response", "mc_reasoned"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py -v`
Expected: every test FAILS with `ImportError: cannot import name 'Evidence' from 'learning.evidence'`.

- [ ] **Step 4: Implement `learning/evidence.py`**

```python
"""Evidence model (spec §5) and §3.1 observation weights.

The only input shape apply_graph_update accepts on the loop path. Weights
are DERIVED from the flags here; the `weight` field on an input Evidence is
overwritten by apply_graph_update with evidence_weight(ev) and journaled.
No LLM, no db: this module is data + arithmetic.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from learning.params import (
    CHANNELS,
    EVIDENCE_NO_UPWARD_MIN_RUNG,
    GRADER_LOW_CONFIDENCE,
    LADDER_MAX_RUNG,
    WEIGHT_ASSISTED,
    WEIGHT_LOW_CONFIDENCE,
    WEIGHT_SAME_SESSION_RECHECK,
)

Channel = Literal["free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn", "idk"]

#: One-hop prerequisite propagation is a chat_turn-strength observation (spec §3.1).
PROPAGATION_CHANNEL: Channel = "chat_turn"
#: node_mastery_events.event_type for rows written by the evidence path (spec §4).
EVIDENCE_EVENT_TYPE = "evidence"
#: graph_edges.relationship_type the propagation walks (spec §3.1).
PREREQ_RELATIONSHIP_TYPE = "prerequisite"


class Evidence(BaseModel):
    node_id: str
    channel: Channel
    correct: bool
    assisted: bool = False  # any rung H1..H3 used before the answer
    max_rung: int = Field(default=0, ge=0, le=LADDER_MAX_RUNG)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)  # derived; see evidence_weight
    session_id: str | None = None
    check_item_id: str | None = None
    question_hash: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    same_session_recheck: bool = False

    @model_validator(mode="after")
    def _consistency(self) -> "Evidence":
        if self.channel == "idk" and self.correct:
            raise ValueError("idk evidence cannot be correct")
        if self.max_rung >= 1 and not self.assisted:
            # Rungs unlock in order (PKG-06 gates), so any rung means H1 was used.
            object.__setattr__(self, "assisted", True)
        return self


def is_strong_channel(channel: str) -> bool:
    """Spec §3.1 channel table, `strong?` column, read from params.CHANNELS."""
    entry = CHANNELS[channel]
    strong = entry["strong"] if isinstance(entry, dict) else getattr(entry, "strong")
    return bool(strong)


def evidence_weight(ev: Evidence) -> float:
    """Product of the applicable §3.1 weights, from the flags only.

    0.0 means "no upward BKT evidence" (spec §3.3: correct after H4–H6);
    apply_graph_update then leaves p_known untouched and lets FSRS record
    the Again rating.
    """
    if ev.correct and ev.max_rung >= EVIDENCE_NO_UPWARD_MIN_RUNG:
        return 0.0
    w = 1.0
    if ev.correct and ev.assisted:
        w *= WEIGHT_ASSISTED
    if ev.same_session_recheck:
        w *= WEIGHT_SAME_SESSION_RECHECK
    if ev.confidence is not None and ev.confidence < GRADER_LOW_CONFIDENCE:
        w *= WEIGHT_LOW_CONFIDENCE
    return w
```

If HANDOFF-01's `CHANNELS` has a different shape (a `NamedTuple` per channel, or a separate `STRONG_CHANNELS` set), adapt `is_strong_channel` only and record it.

- [ ] **Step 5: Run tests, lint, format**

Run: `cd backend && venv/bin/ruff format learning/evidence.py tests/test_learning_evidence_apply.py && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_learning_loop_invariants.py -q -k "not inv_01" && venv/bin/ruff check .`
Expected: `12 passed` in the evidence module; invariants green except the deselected `inv_01`; `All checks passed!`

- [ ] **Step 6: Commit**

```
git add backend/learning/evidence.py backend/tests/test_learning_evidence_apply.py
git commit -m "feat(learning-loop): PKG-03 — Evidence model and §3.1 weights

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: `learning/learner_state.py` — decayed read, single-writer write

**Files:**
- Create (replace stub): `backend/learning/learner_state.py`
- Modify: `backend/tests/test_learning_evidence_apply.py` (append `TestLearnerState`)

**Interfaces:**
- Consumes: `db.connection.table`, `bkt.decayed_p`, `params.BKT_L0`, `params.FSRS_S0_GOOD`.
- Produces: `LearnerState`, `read_state(user_id, node_id, now=None)`, `read_states(user_id, node_ids, now=None)`, `write_state(state, now=None)`, `LEARNER_STATE_COLUMNS`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── learner_state ─────────────────────────────────────────────────────────────


def _state_row(**over):
    row = {
        "user_id": "u1", "node_id": "n1", "p_known": 0.9,
        "n_strong_unassisted": 2, "streak_unassisted": 1, "opps": 4,
        "fsrs_d": 5.0, "fsrs_s": 10.0,
        "fsrs_last_review_at": (NOW - timedelta(days=3)).isoformat(),
        "fsrs_due_at": (NOW + timedelta(days=7)).isoformat(),
        "htc_k": 0.5, "unassisted_next": 0.7, "assist_gap": 0.1, "in_zone": True,
        "last_evidence_at": (NOW - timedelta(days=3)).isoformat(),
        "updated_at": (NOW - timedelta(days=3)).isoformat(),
    }
    row.update(over)
    return row


def _ls_table(rows):
    t = MagicMock()
    t.select.return_value = rows
    t.upsert.return_value = []
    return t


class TestLearnerState:
    def test_missing_row_defaults_to_prior_and_exists_false(self):
        from learning import learner_state as ls

        t = _ls_table([])
        with patch("learning.learner_state.table", return_value=t):
            st = ls.read_state("u1", "n1", now=NOW)
        assert st.exists is False and st.p_known == BKT_L0
        assert (st.opps, st.streak_unassisted, st.n_strong_unassisted) == (0, 0, 0)
        assert st.fsrs_s is None and st.last_evidence_at is None
        _, kwargs = t.select.call_args
        assert kwargs["filters"] == {"user_id": "eq.u1", "node_id": "in.(n1)"}

    def test_read_decays_toward_prior_with_elapsed_time(self):
        from learning import bkt
        from learning import learner_state as ls

        with patch("learning.learner_state.table", return_value=_ls_table([_state_row()])):
            st = ls.read_state("u1", "n1", now=NOW)
        assert st.exists is True
        assert st.p_known == pytest.approx(bkt.decayed_p(0.9, 3.0, 10.0))
        assert BKT_L0 < st.p_known < 0.9

    def test_no_elapsed_time_means_no_decay_and_missing_stability_uses_s0_good(self):
        from learning import bkt
        from learning import learner_state as ls
        from learning.params import FSRS_S0_GOOD

        rows = [_state_row(last_evidence_at=NOW.isoformat())]
        with patch("learning.learner_state.table", return_value=_ls_table(rows)):
            assert ls.read_state("u1", "n1", now=NOW).p_known == pytest.approx(0.9)
        rows = [_state_row(fsrs_s=None, fsrs_d=None)]
        with patch("learning.learner_state.table", return_value=_ls_table(rows)):
            st = ls.read_state("u1", "n1", now=NOW)
        assert st.p_known == pytest.approx(bkt.decayed_p(0.9, 3.0, FSRS_S0_GOOD))

    def test_read_states_is_one_batched_select(self):
        from learning import learner_state as ls

        t = _ls_table([_state_row(node_id="n1"), _state_row(node_id="n2", p_known=0.2)])
        with patch("learning.learner_state.table", return_value=t):
            states = ls.read_states("u1", ["n2", "n1", "n2"], now=NOW)
            assert ls.read_states("u1", [], now=NOW) == {}
        assert set(states) == {"n1", "n2"}
        t.select.assert_called_once()
        assert t.select.call_args.kwargs["filters"]["node_id"] == "in.(n1,n2)"

    def test_write_upserts_on_user_node_and_never_names_derived_columns(self):
        from learning import learner_state as ls

        st = ls.LearnerState(user_id="u1", node_id="n1", p_known=0.7, opps=1, streak_unassisted=1,
                             n_strong_unassisted=1, fsrs_d=5.0, fsrs_s=3.0,
                             fsrs_last_review_at=NOW, fsrs_due_at=NOW + timedelta(days=2),
                             last_evidence_at=NOW)
        t = _ls_table([])
        with patch("learning.learner_state.table", return_value=t):
            ls.write_state(st, now=NOW)
            ls.write_state(ls.LearnerState(user_id="u1", node_id="n1", p_known=0.5), now=NOW)
        full, bare = [c.args[0] for c in t.upsert.call_args_list]
        assert t.upsert.call_args.kwargs == {"on_conflict": "user_id,node_id"}
        assert full["p_known"] == 0.7 and full["opps"] == 1
        assert full["updated_at"] == NOW.isoformat()
        assert full["fsrs_due_at"] == (NOW + timedelta(days=2)).isoformat()
        for derived in ("htc_k", "unassisted_next", "assist_gap", "in_zone"):
            assert derived not in full
        assert bare["fsrs_last_review_at"] is None and bare["last_evidence_at"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py -v -k TestLearnerState`
Expected: FAIL — `AttributeError: module 'learning.learner_state' has no attribute 'read_state'`

- [ ] **Step 3: Implement**

```python
"""learner_state table access (spec §4 PKG-03, §5).

read_* return p_known DECAYED toward BKT_L0 along the concept's FSRS
stability (spec §3.1, "Decay at read"). write_state is called ONLY from
services.graph_service.apply_graph_update — spec §8 invariant 1,
tests/test_learning_loop_invariants.py::test_inv_01_single_graph_writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from db.connection import table
from learning import bkt
from learning.params import BKT_L0, FSRS_S0_GOOD

LEARNER_STATE_COLUMNS = (
    "user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,opps,"
    "fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,"
    "htc_k,unassisted_next,assist_gap,in_zone,last_evidence_at,updated_at"
)


@dataclass
class LearnerState:
    user_id: str
    node_id: str
    p_known: float = BKT_L0  # decayed at read; the posterior after an update
    n_strong_unassisted: int = 0
    streak_unassisted: int = 0
    opps: int = 0
    fsrs_d: float | None = None
    fsrs_s: float | None = None
    fsrs_last_review_at: datetime | None = None
    fsrs_due_at: datetime | None = None
    htc_k: float | None = None  # PKG-06 derives; never written here
    unassisted_next: float | None = None
    assist_gap: float | None = None
    in_zone: bool | None = None
    last_evidence_at: datetime | None = None
    exists: bool = False


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    ts = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _from_row(row: dict, now: datetime) -> LearnerState:
    stored = row.get("p_known")
    p_stored = float(stored) if stored is not None else BKT_L0
    st = LearnerState(user_id=row["user_id"], node_id=row["node_id"], p_known=p_stored, exists=True)
    for col in ("n_strong_unassisted", "streak_unassisted", "opps"):
        setattr(st, col, int(row.get(col) or 0))
    for col in ("fsrs_d", "fsrs_s", "htc_k", "unassisted_next", "assist_gap", "in_zone"):
        setattr(st, col, row.get(col))
    for col in ("fsrs_last_review_at", "fsrs_due_at", "last_evidence_at"):
        setattr(st, col, _parse_ts(row.get(col)))
    elapsed_days = 0.0
    if st.last_evidence_at is not None:
        elapsed_days = max(0.0, (now - st.last_evidence_at) / timedelta(days=1))
    stability = st.fsrs_s if st.fsrs_s is not None else FSRS_S0_GOOD
    st.p_known = bkt.decayed_p(p_stored, elapsed_days, stability)
    return st


def read_states(user_id: str, node_ids, now: datetime | None = None) -> dict[str, LearnerState]:
    """One batched read; each returned state is decayed to `now`."""
    ids = sorted({n for n in node_ids if n})
    if not ids:
        return {}
    now = now or datetime.now(timezone.utc)
    rows = table("learner_state").select(
        LEARNER_STATE_COLUMNS,
        filters={"user_id": f"eq.{user_id}", "node_id": f"in.({','.join(ids)})"},
    ) or []
    return {r["node_id"]: _from_row(r, now) for r in rows if r.get("node_id") in ids}


def read_state(user_id: str, node_id: str, now: datetime | None = None) -> LearnerState:
    """Single-row form; a missing row is the BKT prior with exists=False."""
    return read_states(user_id, [node_id], now=now).get(node_id) or LearnerState(
        user_id=user_id, node_id=node_id
    )


def write_state(state: LearnerState, now: datetime | None = None) -> None:
    """Upsert the BKT/FSRS columns. ONLY caller: graph_service.apply_graph_update.

    The derived columns (htc_k, unassisted_next, assist_gap, in_zone) are
    deliberately absent: PostgREST merge-duplicates would null them.
    """
    now = now or datetime.now(timezone.utc)
    table("learner_state").upsert(
        {
            "user_id": state.user_id,
            "node_id": state.node_id,
            "p_known": state.p_known,
            "n_strong_unassisted": state.n_strong_unassisted,
            "streak_unassisted": state.streak_unassisted,
            "opps": state.opps,
            "fsrs_d": state.fsrs_d,
            "fsrs_s": state.fsrs_s,
            "fsrs_last_review_at": _iso(state.fsrs_last_review_at),
            "fsrs_due_at": _iso(state.fsrs_due_at),
            "last_evidence_at": _iso(state.last_evidence_at),
            "updated_at": _iso(now),
        },
        on_conflict="user_id,node_id",
    )
```

- [ ] **Step 4: Run tests, lint, format**

Run: `cd backend && venv/bin/ruff format learning/learner_state.py tests/test_learning_evidence_apply.py && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_learning_loop_invariants.py -q -k "not inv_01" && venv/bin/ruff check .`
Expected: all passed (`inv_07` now exercises `learner_state.py` for real); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/learner_state.py backend/tests/test_learning_evidence_apply.py
git commit -m "feat(learning-loop): PKG-03 — learner_state decayed read / single-writer write

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: Legacy byte-identity snapshot (green FIRST, before graph_service changes)

**Files:**
- Modify: `backend/tests/test_learning_evidence_apply.py` (append the trace recorder + two tests)

**Interfaces:**
- Consumes: `services.graph_service.apply_graph_update` as it is on `main`.
- Produces: the pin that Task 6 must not move.

This is the one test in the package that must PASS before its implementation task. It records every `table(...)` call the legacy path makes for a representative payload (a new node, a mastery update with `event_type`, a prerequisite edge) and compares it with a literal. If the literal is wrong, the literal is wrong — fix it from the printed diff now, on unmodified `graph_service.py`, and only then move to Task 6.

- [ ] **Step 1: Write the test** (append)

```python
# ── legacy byte-identity ──────────────────────────────────────────────────────

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00")


def _norm(value):
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, str):
        if _UUID.fullmatch(value):
            return "<UUID>"
        if _ISO.fullmatch(value):
            return "<TS>"
    return value


def _tracing_factory(rows_by_table: dict, trace: list):
    """Every table call lands in `trace` as (table, method, args, kwargs);
    graph_nodes.upsert echoes its payload like live PostgREST does."""
    mocks: dict = {}

    def factory(name):
        if name in mocks:
            return mocks[name]
        m = MagicMock()

        def _rec(method):
            def _call(*args, **kwargs):
                trace.append((name, method, _norm(args), _norm(kwargs)))
                if method == "select":
                    return list(rows_by_table.get(name, []))
                if method == "upsert" and name == "graph_nodes":
                    return [args[0]] if isinstance(args[0], dict) else list(args[0])
                return []
            return _call

        for method in ("select", "insert", "update", "upsert", "delete"):
            setattr(m, method, MagicMock(side_effect=_rec(method)))
        mocks[name] = m
        return m

    return factory


LEGACY_NODES = [
    {"id": "n1", "concept_name": "Recursion", "mastery_score": 0.5, "times_studied": 1, "course_id": "c1"},
]
LEGACY_PAYLOAD = {
    "new_nodes": [{"concept_name": "Loops", "initial_mastery": 0.0}],
    "updated_nodes": [
        {"concept_name": "recursion", "mastery_delta": 0.1, "reason": "Quiz: 3/3 correct",
         "event_type": "quiz_correct"},
    ],
    "new_edges": [
        {"source": "Loops", "target": "Recursion", "relationship_type": "prerequisite", "strength": 0.8},
    ],
}
LEGACY_TRACE = [
    ("graph_nodes", "select",
     ["id,concept_name,mastery_score,times_studied,course_id"],
     {"filters": {"user_id": "eq.u1", "course_id": "eq.c1"}}),
    ("graph_nodes", "upsert",
     [{"id": "<UUID>", "user_id": "u1", "concept_name": "Loops", "mastery_score": 0.0,
       "mastery_tier": "unexplored", "course_id": "c1"}],
     {"on_conflict": "user_id,course_id,concept_name"}),
    ("graph_nodes", "update",
     [{"mastery_score": 0.6, "mastery_tier": "learning", "times_studied": 2, "last_studied_at": "<TS>"}],
     {"filters": {"id": "eq.n1"}}),
    ("node_mastery_events", "insert",
     [{"id": "<UUID>", "node_id": "n1", "delta": 0.1, "reason": "Quiz: 3/3 correct",
       "created_at": "<TS>", "event_type": "quiz_correct"}],
     {}),
    ("graph_edges", "upsert",
     [{"id": "<UUID>", "user_id": "u1", "source_node_id": "<UUID>", "target_node_id": "n1",
       "strength": 0.8, "relationship_type": "prerequisite"}],
     {"on_conflict": "user_id,source_node_id,target_node_id,relationship_type"}),
]


def _run_legacy(payload):
    from services.graph_service import apply_graph_update

    trace: list = []
    factory = _tracing_factory({"graph_nodes": LEGACY_NODES}, trace)
    with patch("services.graph_service.table", side_effect=factory), \
         patch("services.graph_service.touch_streak_safe"), \
         patch("services.course_context_service.update_course_context"), \
         patch("services.academics.user_offering_ids_for_course", return_value=[]), \
         patch("services.achievement_service.check_achievements"):
        result = apply_graph_update("u1", payload, course_id="c1")
    return result, trace


def test_legacy_payload_table_trace_unchanged():
    """Green on main BEFORE Task 6, green after: a payload without `evidence`
    makes exactly these table calls, in this order, with these arguments."""
    result, trace = _run_legacy(LEGACY_PAYLOAD)
    assert result == [{"concept": "Recursion", "before": 0.5, "after": 0.6}]
    assert trace == LEGACY_TRACE


@pytest.mark.parametrize("evidence_value", [None, []])
def test_empty_evidence_key_is_the_legacy_path(evidence_value):
    result, trace = _run_legacy({**LEGACY_PAYLOAD, "evidence": evidence_value})
    assert result == [{"concept": "Recursion", "before": 0.5, "after": 0.6}]
    assert trace == LEGACY_TRACE
```

- [ ] **Step 2: Run on unmodified `graph_service.py` — it must PASS**

Run: `cd backend && git diff --quiet main -- services/graph_service.py && venv/bin/python -m pytest tests/test_learning_evidence_apply.py -v -k "legacy or empty_evidence"`
Expected: `3 passed`. If the trace differs, `pytest -vv` prints the diff: correct `LEGACY_TRACE` to what the CURRENT code does, re-run to green. Never change `graph_service.py` in this task.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_evidence_apply.py
git commit -m "test(learning-loop): PKG-03 — pin the legacy apply_graph_update table trace

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: `apply_graph_update` evidence path

**Files:**
- Modify: `backend/services/graph_service.py` (imports; `_prerequisite_edges`, `_propagation_targets`, `_fsrs_after`, `_apply_evidence` helpers above `apply_graph_update`; two small edits inside `apply_graph_update`)
- Modify: `backend/tests/test_learning_evidence_apply.py` (append `TestApplyEvidence`, `test_no_production_caller_passes_evidence_yet`)

**Interfaces:**
- Consumes: `learning.evidence`, `learning.learner_state`, `learning.bkt`, `learning.fsrs`, `params.WEIGHT_PROPAGATION`.
- Produces: `apply_graph_update(..., {"evidence": [...]})` behaviour per §Spec/Behaviour 3.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── apply_graph_update evidence path ──────────────────────────────────────────


def _evidence_factory(nodes, edges=(), states=()):
    """Per-table mocks. learner_state.select returns `states` regardless of the
    filter (read_states maps by node_id); graph_edges.select returns every edge
    (bkt.propagate_prereq picks the direction)."""
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock()
            rows = {"graph_nodes": nodes, "graph_edges": edges, "learner_state": states}.get(name, [])
            m.select.return_value = list(rows)
            for method in ("insert", "update", "upsert", "delete"):
                getattr(m, method).return_value = []
            if name == "graph_nodes":
                m.upsert.side_effect = lambda data, **kw: [data]
            mocks[name] = m
        return mocks[name]

    return factory, mocks


NODES = [
    {"id": "n1", "concept_name": "Recursion", "mastery_score": 0.5, "times_studied": 1, "course_id": "c1"},
    {"id": "n0", "concept_name": "Functions", "mastery_score": 0.5, "times_studied": 3, "course_id": "c1"},
    {"id": "n2", "concept_name": "Memoization", "mastery_score": 0.5, "times_studied": 0, "course_id": "c1"},
]
# n0 (Functions) is a prerequisite of n1 (Recursion); n1 is a prerequisite of n2.
EDGES = [
    {"source_node_id": "n0", "target_node_id": "n1", "relationship_type": "prerequisite"},
    {"source_node_id": "n1", "target_node_id": "n2", "relationship_type": "prerequisite"},
]


def _apply(payload, nodes=NODES, edges=EDGES, states=()):
    from services.graph_service import apply_graph_update

    factory, mocks = _evidence_factory(nodes, edges, states)
    with patch("services.graph_service.table", side_effect=factory), \
         patch("learning.learner_state.table", side_effect=factory), \
         patch("services.graph_service.touch_streak_safe") as streak, \
         patch("services.course_context_service.update_course_context"), \
         patch("services.academics.user_offering_ids_for_course", return_value=[]), \
         patch("services.achievement_service.check_achievements"):
        result = apply_graph_update("u1", payload, course_id="c1")
    return result, mocks, streak


def _event_rows(mocks):
    return [c.args[0] for c in mocks["node_mastery_events"].insert.call_args_list]


def _state_writes(mocks):
    return [c.args[0] for c in mocks["learner_state"].upsert.call_args_list]


def _node_updates(mocks):
    return [(c.kwargs["filters"]["id"], c.args[0]) for c in mocks["graph_nodes"].update.call_args_list]


class TestApplyEvidence:
    def test_one_event_row_per_evidence_with_every_column(self):
        from learning.evidence import EVIDENCE_EVENT_TYPE

        payload = {"evidence": [
            {"node_id": "n1", "channel": "free_response", "correct": True,
             "session_id": "s1", "check_item_id": "ci1", "question_hash": "q1", "confidence": 0.9},
            {"node_id": "n1", "channel": "mc", "correct": False, "session_id": "s1", "question_hash": "q2"},
        ]}
        _, mocks, _ = _apply(payload, edges=[])
        rows = [r for r in _event_rows(mocks) if r["event_type"] == EVIDENCE_EVENT_TYPE]
        assert len(rows) == 2
        first = rows[0]
        for col in ("id", "node_id", "delta", "reason", "created_at", "event_type", "channel",
                    "correct", "weight", "assisted", "max_rung", "p_before", "p_after",
                    "session_id", "check_item_id", "question_hash", "confidence"):
            assert col in first, col
        assert first["node_id"] == "n1" and first["channel"] == "free_response"
        assert first["correct"] is True and first["weight"] == 1.0
        assert first["delta"] == pytest.approx(first["p_after"] - first["p_before"])
        assert first["reason"] == "evidence:free_response"
        assert rows[1]["check_item_id"] is None and rows[1]["confidence"] is None

    def test_correct_strong_evidence_raises_p_from_prior_and_mirrors_the_node(self):
        from learning import bkt

        result, mocks, streak = _apply({"evidence": [
            {"node_id": "n1", "channel": "free_response", "correct": True}]}, edges=[])
        [row] = _event_rows(mocks)
        assert row["p_before"] == pytest.approx(BKT_L0)
        assert row["p_after"] == pytest.approx(bkt.update(BKT_L0, "free_response", True, weight=1.0))
        assert row["p_after"] > row["p_before"]
        assert result == [{"concept": "Recursion", "before": row["p_before"], "after": row["p_after"]}]
        streak.assert_called_once_with("u1")
        [(node_filter, upd)] = _node_updates(mocks)
        assert node_filter == "eq.n1"
        assert upd["mastery_score"] == pytest.approx(row["p_after"])
        assert upd["mastery_tier"] == bkt.tier_for(row["p_after"])
        assert upd["times_studied"] == 2 and _ISO.fullmatch(upd["last_studied_at"])

    def test_second_evidence_on_same_node_sees_first_posterior(self):
        _, mocks, _ = _apply({"evidence": [
            {"node_id": "n1", "channel": "mc", "correct": True},
            {"node_id": "n1", "channel": "mc", "correct": True},
        ]}, edges=[])
        a, b = _event_rows(mocks)
        assert b["p_before"] == pytest.approx(a["p_after"])
        assert mocks["learner_state"].select.call_count == 1
        (_, upd_a), (_, upd_b) = _node_updates(mocks)
        assert (upd_a["times_studied"], upd_b["times_studied"]) == (2, 3)

    def test_weights_are_journaled_from_flags_not_input(self):
        _, mocks, _ = _apply({"evidence": [
            {"node_id": "n1", "channel": "free_response", "correct": True, "assisted": True,
             "max_rung": 2, "weight": 0.9},
        ]}, edges=[])
        [row] = _event_rows(mocks)
        assert row["weight"] == WEIGHT_ASSISTED and row["assisted"] is True and row["max_rung"] == 2

    def test_same_session_recheck_detected_within_one_call(self):
        _, mocks, _ = _apply({"evidence": [
            {"node_id": "n1", "channel": "free_response", "correct": False, "session_id": "s", "question_hash": "q"},
            {"node_id": "n1", "channel": "free_response", "correct": True, "session_id": "s", "question_hash": "q"},
        ]}, edges=[])
        first, second = _event_rows(mocks)
        assert first["weight"] == 1.0
        assert second["weight"] == WEIGHT_SAME_SESSION_RECHECK

    def test_idk_lowers_p_and_resets_streak(self):
        states = [_state_row(node_id="n1", p_known=0.8, streak_unassisted=2, opps=5,
                             last_evidence_at=NOW.isoformat())]
        _, mocks, _ = _apply({"evidence": [{"node_id": "n1", "channel": "idk", "correct": False}]},
                             edges=[], states=states)
        [row] = _event_rows(mocks)
        assert row["p_after"] < row["p_before"]
        [st] = [w for w in _state_writes(mocks) if w["node_id"] == "n1"]
        assert st["streak_unassisted"] == 0 and st["opps"] == 6

    def test_counters_follow_the_evidence_mapping(self):
        _, mocks, _ = _apply({"evidence": [
            {"node_id": "n1", "channel": "free_response", "correct": True},               # strong, unassisted
            {"node_id": "n1", "channel": "mc", "correct": True},                          # unassisted, not strong
            {"node_id": "n1", "channel": "free_response", "correct": True, "max_rung": 2},  # assisted
        ]}, edges=[])
        a, b, c = [w for w in _state_writes(mocks) if w["node_id"] == "n1"]
        assert (a["opps"], a["streak_unassisted"], a["n_strong_unassisted"]) == (1, 1, 1)
        assert (b["opps"], b["streak_unassisted"], b["n_strong_unassisted"]) == (2, 2, 1)
        assert (c["opps"], c["streak_unassisted"], c["n_strong_unassisted"]) == (3, 0, 1)

    def test_correct_after_worked_example_leaves_p_and_still_schedules(self):
        from learning import fsrs

        _, mocks, _ = _apply({"evidence": [
            {"node_id": "n1", "channel": "free_response", "correct": True,
             "max_rung": EVIDENCE_NO_UPWARD_MIN_RUNG},
        ]}, edges=[])
        [row] = _event_rows(mocks)
        assert row["p_after"] == pytest.approx(row["p_before"]) and row["weight"] == 0.0
        [st] = _state_writes(mocks)
        assert st["fsrs_d"] is not None and st["fsrs_s"] is not None
        assert st["fsrs_last_review_at"] == st["last_evidence_at"] and st["fsrs_due_at"] is not None
        assert fsrs.rating_for("free_response", True, EVIDENCE_NO_UPWARD_MIN_RUNG) == 1  # Again

    def test_correct_propagates_to_prerequisite_parent_only(self):
        from learning import bkt
        from learning.evidence import PROPAGATION_CHANNEL

        _, mocks, _ = _apply({"evidence": [{"node_id": "n1", "channel": "free_response", "correct": True}]})
        writes = {w["node_id"]: w for w in _state_writes(mocks)}
        assert set(writes) == {"n1", "n0"}, "parent n0 updated, child n2 untouched"
        assert writes["n0"]["p_known"] == pytest.approx(
            bkt.update(BKT_L0, PROPAGATION_CHANNEL, True, weight=WEIGHT_PROPAGATION))
        assert writes["n0"]["opps"] == 0 and writes["n0"]["fsrs_s"] is None
        updates = dict(_node_updates(mocks))
        assert set(updates) == {"eq.n1", "eq.n0"}
        assert set(updates["eq.n0"]) == {"mastery_score", "mastery_tier"}
        assert [r["node_id"] for r in _event_rows(mocks)] == ["n1"], "no journal row for propagation"
        for call in mocks["graph_edges"].select.call_args_list:
            f = call.kwargs["filters"]
            assert f["user_id"] == "eq.u1" and f["relationship_type"] == "eq.prerequisite"

    def test_incorrect_propagates_to_dependent_child_only(self):
        _, mocks, _ = _apply({"evidence": [{"node_id": "n1", "channel": "free_response", "correct": False}]})
        writes = {w["node_id"]: w for w in _state_writes(mocks)}
        assert set(writes) == {"n1", "n2"}, "child n2 updated, parent n0 untouched"
        assert writes["n2"]["p_known"] < BKT_L0

    def test_unowned_node_is_skipped_with_a_warning(self, caplog):
        with caplog.at_level("WARNING"):
            result, mocks, streak = _apply({"evidence": [{"node_id": "ghost", "channel": "mc", "correct": True}]},
                                           edges=[])
        assert result == []
        assert _state_writes(mocks) == [] and _event_rows(mocks) == [] and _node_updates(mocks) == []
        streak.assert_not_called()
        assert any("ghost" in r.getMessage() for r in caplog.records)

    def test_invalid_evidence_raises_before_any_write(self):
        with pytest.raises(ValidationError):
            _apply({"evidence": [
                {"node_id": "n1", "channel": "free_response", "correct": True},
                {"node_id": "n1", "channel": "idk", "correct": True},
            ]}, edges=[])

    def test_evidence_and_legacy_keys_coexist(self):
        payload = {**LEGACY_PAYLOAD, "evidence": [{"node_id": "n1", "channel": "mc", "correct": True}]}
        result, mocks, _ = _apply(payload, edges=[])
        assert [c["concept"] for c in result] == ["Recursion", "Recursion"]
        assert [r.get("event_type") for r in _event_rows(mocks)] == ["quiz_correct", "evidence"]


def test_no_production_caller_passes_evidence_yet():
    """PKG-03 adds the path and no caller. PKG-05 deletes this test when it
    wires graded_check_tool → apply_graph_update(..., {"evidence": ...})."""
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[1]
    hits = []
    for sub in ("routes", "agents", "services"):
        for path in (backend / sub).rglob("*.py"):
            if path.name == "graph_service.py":
                continue
            if re.search(r'["\']evidence["\']\s*:', path.read_text()):
                hits.append(str(path.relative_to(backend)))
    assert hits == [], hits
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py -v -k "TestApplyEvidence or no_production_caller"`
Expected: `test_no_production_caller_passes_evidence_yet` PASSES; every `TestApplyEvidence` test FAILS — most with `assert 0 == 2` / `ValueError: not enough values to unpack` (no rows written), `test_invalid_evidence_raises_before_any_write` with `DID NOT RAISE`.

- [ ] **Step 3: Implement**

Imports at the top of `graph_service.py`, after `from db.connection import table`:

```python
from learning import bkt, fsrs
from learning.evidence import (
    EVIDENCE_EVENT_TYPE,
    PREREQ_RELATIONSHIP_TYPE,
    PROPAGATION_CHANNEL,
    Evidence,
    evidence_weight,
    is_strong_channel,
)
from learning.learner_state import LearnerState, read_states, write_state
from learning.params import WEIGHT_PROPAGATION
```

Helpers, placed directly above `def apply_graph_update` (after `_insert_mastery_event`):

```python
def _prerequisite_edges(user_id: str, node_id: str) -> list[tuple[str, str]]:
    """(source_node_id, target_node_id) prerequisite pairs touching node_id.
    Two reads: the filter dict has no OR across columns (graph_read.py)."""
    pairs: set[tuple[str, str]] = set()
    for col in ("source_node_id", "target_node_id"):
        rows = table("graph_edges").select(
            "source_node_id,target_node_id",
            filters={
                "user_id": f"eq.{user_id}",
                "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}",
                col: f"eq.{node_id}",
            },
        ) or []
        for r in rows:
            src, tgt = r.get("source_node_id"), r.get("target_node_id")
            if src and tgt:
                pairs.add((src, tgt))
    return sorted(pairs)


def _propagation_targets(user_id: str, ev: Evidence) -> list[tuple[str, bool]]:
    """ADAPTER — the one place bkt.propagate_prereq's signature is assumed
    (HANDOFF-01). Returns (target_node_id, observed_correct) pairs."""
    edges = _prerequisite_edges(user_id, ev.node_id)
    if not edges:
        return []
    return list(bkt.propagate_prereq(ev.node_id, ev.correct, edges))


def _fsrs_after(st: LearnerState, ev: Evidence, now: datetime) -> None:
    """ADAPTER — the one place fsrs.next_state's state type is assumed
    (HANDOFF-02). Mutates st's fsrs_* fields in place."""
    rating = fsrs.rating_for(ev.channel, ev.correct, ev.max_rung)
    prev = None
    if st.fsrs_s is not None:
        prev = fsrs.FsrsState(
            d=st.fsrs_d, s=st.fsrs_s,
            last_review_at=st.fsrs_last_review_at, due_at=st.fsrs_due_at,
        )
    nxt = fsrs.next_state(prev, rating, now)
    st.fsrs_d, st.fsrs_s = nxt.d, nxt.s
    st.fsrs_last_review_at, st.fsrs_due_at = now, nxt.due_at


def _apply_evidence(
    user_id: str,
    evidences: list[Evidence],
    by_id: dict[str, dict],
    touched_courses: set,
    now: datetime,
) -> list[dict]:
    """PKG-03: the BKT + FSRS write path (spec §5). ONLY caller: apply_graph_update.

    Per evidence, in order: ownership → weight → decayed read → bkt.update →
    counters → FSRS → learner_state → graph_nodes mirror → ONE journal row →
    one-hop propagation (learner_state + mirror only). Propagated updates are
    derived from the journaled evidence, so they are not journaled themselves.
    """
    changes: list[dict] = []
    now_iso = now.isoformat()
    states = read_states(user_id, [ev.node_id for ev in evidences], now=now)
    seen_rechecks: set[tuple[str, str]] = set()

    for ev in evidences:
        row = by_id.get(ev.node_id)
        if row is None:
            logger.warning(
                "graph: evidence skipped node=%s user=%s (not owned or outside course)",
                ev.node_id, user_id,
            )
            continue
        if ev.session_id and ev.question_hash:
            key = (ev.session_id, ev.question_hash)
            if key in seen_rechecks and not ev.same_session_recheck:
                ev = ev.model_copy(update={"same_session_recheck": True})
            seen_rechecks.add(key)
        w = evidence_weight(ev)

        st = states.get(ev.node_id) or LearnerState(user_id=user_id, node_id=ev.node_id)
        p_before = st.p_known
        p_after = bkt.update(p_before, ev.channel, ev.correct, weight=w) if w > 0.0 else p_before

        unassisted = not ev.assisted and ev.max_rung == 0
        st.opps += 1
        if ev.correct and unassisted:
            st.streak_unassisted += 1
            if is_strong_channel(ev.channel):
                st.n_strong_unassisted += 1
        else:
            st.streak_unassisted = 0
        st.p_known = p_after
        st.last_evidence_at = now
        _fsrs_after(st, ev, now)
        write_state(st, now=now)
        states[ev.node_id] = st

        times = (row.get("times_studied") or 0) + 1
        table("graph_nodes").update(
            {
                "mastery_score": p_after,
                "mastery_tier": bkt.tier_for(p_after),
                "times_studied": times,
                "last_studied_at": now_iso,
            },
            filters={"id": f"eq.{row['id']}"},
        )
        row["times_studied"] = times
        row["mastery_score"] = p_after

        _insert_mastery_event({
            "id": str(uuid.uuid4()),
            "node_id": row["id"],
            "delta": p_after - p_before,
            "reason": f"evidence:{ev.channel}",
            "created_at": now_iso,
            "event_type": EVIDENCE_EVENT_TYPE,
            "channel": ev.channel,
            "correct": ev.correct,
            "weight": w,
            "assisted": ev.assisted,
            "max_rung": ev.max_rung,
            "p_before": p_before,
            "p_after": p_after,
            "session_id": ev.session_id,
            "check_item_id": ev.check_item_id,
            "question_hash": ev.question_hash,
            "confidence": ev.confidence,
        })
        changes.append({"concept": row["concept_name"], "before": p_before, "after": p_after})
        if row.get("course_id"):
            touched_courses.add(row["course_id"])

        for target_id, target_correct in _propagation_targets(user_id, ev):
            trow = by_id.get(target_id)
            if trow is None or target_id == ev.node_id:
                continue
            tst = states.get(target_id)
            if tst is None:
                tst = read_states(user_id, [target_id], now=now).get(target_id) or LearnerState(
                    user_id=user_id, node_id=target_id
                )
            tst.p_known = bkt.update(
                tst.p_known, PROPAGATION_CHANNEL, target_correct, weight=WEIGHT_PROPAGATION
            )
            tst.last_evidence_at = now
            write_state(tst, now=now)
            states[target_id] = tst
            table("graph_nodes").update(
                {"mastery_score": tst.p_known, "mastery_tier": bkt.tier_for(tst.p_known)},
                filters={"id": f"eq.{target_id}"},
            )
            trow["mastery_score"] = tst.p_known
    return changes
```

Inside `apply_graph_update`, two edits and nothing else:

(a) Immediately after `touched_courses: set = set()` (:692), validate before any read:

```python
    raw_evidence = graph_update.get("evidence") or []
    evidences = [e if isinstance(e, Evidence) else Evidence.model_validate(e) for e in raw_evidence]
```

(b) Immediately after the `updated_nodes` `for` loop ends (before `if mastery_changes:` at :841):

```python
    if evidences:
        # PKG-03: graded evidence is the only thing that moves p_known on the
        # loop path (spec §1). Legacy keys above are untouched; this block is
        # skipped entirely when the payload carries no evidence.
        mastery_changes.extend(
            _apply_evidence(
                user_id,
                evidences,
                {r["id"]: r for r in existing_rows if r.get("id")},
                touched_courses,
                datetime.now(timezone.utc),
            )
        )
```

Adapt `_propagation_targets` / `_fsrs_after` / `is_strong_channel` to the real HANDOFF-01/02 signatures now, if they differ; nothing else in the diff changes.

- [ ] **Step 4: Run the full package, the pinned graph suites, lint**

Run: `cd backend && venv/bin/ruff format tests/test_learning_evidence_apply.py && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py tests/test_graph_add_node.py tests/test_graph_tools_bugs.py tests/test_mastery_tier_unification.py tests/test_quiz_scoring_e.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed — including `test_legacy_payload_table_trace_unchanged` (unchanged literal) and `test_inv_01_single_graph_writer`; `All checks passed!`. Do NOT run `ruff format` on `graph_service.py` (a whole-file reformat would bury the diff); format only the new files.

- [ ] **Step 5: Commit**

```
git add backend/services/graph_service.py backend/tests/test_learning_evidence_apply.py
git commit -m "feat(learning-loop): PKG-03 — apply_graph_update is the single BKT/FSRS writer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-03.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these four lines (they become PKG-05/06/11's State-of-the-world rows):

```
cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q → all passed
ls backend/db/migrations/*_learning_learner_state.sql                                            → 1 file
grep -c '"evidence"' backend/services/graph_service.py                                           → ≥ 1
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01    → 1 passed
```

Under "Symbols added" list at least: `learning/evidence.py::Evidence`, `::Channel`, `::evidence_weight`, `::is_strong_channel`, `::PROPAGATION_CHANNEL`, `::EVIDENCE_EVENT_TYPE`, `::PREREQ_RELATIONSHIP_TYPE`; `learning/learner_state.py::LearnerState`, `::read_state`, `::read_states`, `::write_state`, `::LEARNER_STATE_COLUMNS`; `services/graph_service.py::_apply_evidence`, `::_propagation_targets`, `::_fsrs_after`, `::_prerequisite_edges`; table `learner_state`; the eleven `node_mastery_events` columns; the `event_type = 'evidence'` value; `params.EVIDENCE_NO_UPWARD_MIN_RUNG`, `params.LADDER_MAX_RUNG`.

Under "Constants chosen": the two † constants. Under "Deviations": (i) the two † constants added to PKG-01's `params.py`; (ii) `streak_unassisted` resets on a correct-but-assisted answer (spec §3.3 "counts 0 toward streak", read as consecutive per ZPD line 156) †; (iii) propagated updates are not journaled and do not enter `mastery_changes` †; (iv) any signature adaptation from §Interfaces consumed, with the real signature. Under "Known gaps": `read_states` is one batch per call plus one read per propagation target on a cache miss (PKG-12 may want a wider batch); `graph_nodes.mastery_score` mirrors the POSTERIOR, so the Tree shows an undecayed number until the next evidence (PKG-13 decides whether the Tree reads `learner_state`); the `_insert_mastery_event` retry cannot help a pre-migration environment for evidence rows (migration-before-code). Under "Open questions": whether propagated changes should be surfaced to the tutor stream's `graph_update` event (PKG-07); whether `rating_for` should see `confidence` (PKG-05).

- [ ] **Step 2:** Ledger: append `| 03 | evidence-state | done | feat/learning-loop-03-evidence-state | <sha> | 4 modules | — | HANDOFF-03.md |`; append rows `| 01 | bkt-core | verified | … | … | … | PKG-03, <date>, State-of-the-world PKG-01 rows → all green | HANDOFF-01.md |` and the same for `02` (after the Task 3 `01 | reopened` row, a `verified` row is the honest final state: PKG-03 re-ran PKG-01's suite after its post-hoc change). Append the Deviations lines from Step 1 to `LEDGER.md` §Deviations.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-03.md docs/superpowers/plans/learning-loop/HANDOFF-01.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-03 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 8: PR

- [ ] **Step 1:** Run the self-check loop once more (all seven steps, including the one E2E cycle in step 5).

- [ ] **Step 2: Open the PR**

```
gh pr create --title "feat(learning): PKG-03 evidence-state" --body-file - <<'EOF'
Learning loop series, package 3 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.1, §3.3, §4, §5, §8.

- learning/evidence.py: Evidence model (spec §5), Channel, evidence_weight (§3.1 weights from flags)
- learning/learner_state.py: decayed read (BKT_L0 + FSRS retrievability), single-writer write
- migration <ts>_learning_learner_state.sql: learner_state table + 11 evidence columns on node_mastery_events
- services/graph_service.py::apply_graph_update: `evidence` list → bkt.update → one-hop prerequisite propagation → learner_state → graph_nodes mirror → one node_mastery_events row (event_type='evidence') → FSRS next_state
- test_inv_01_single_graph_writer is now a real source/AST scan
- legacy payloads (no `evidence` key) make the byte-identical table-call trace (pinned by test)

Flag-off behaviour is byte-identical: nothing calls the evidence path yet (PKG-05 is the first caller); `test_no_production_caller_passes_evidence_yet` proves it.

Deploy order: migration before code.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (If you find yourself editing anything under `backend/agents/`, stop: scope creep.)
5. Request-path agent or route touched? **No route or agent; yes a request-path service** (`apply_graph_update` sits under quiz submit, document upload, and the tutor's tools) **plus a migration**. The legacy path is pinned byte-identical by Task 5, so the per-task E2E cycle is skipped; run ONE full cycle before the PR to prove the migration replays on PG15 and the oracles stay clean: `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c 'make e2e-up && (cd frontend && npx playwright test) && (cd backend && venv/bin/python -m e2e_oracles); rc=$?; make e2e-down; exit $rc'` → journeys pass, oracles exit 0. No new spec, no handler constants.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency suites unchanged and green: `tests/test_learning_gate.py`, `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py`, `tests/test_learning_deps.py`, `tests/test_learning_settings_flag.py`, `tests/test_learning_loop_beta_migration.py`.
- Pre-series suites this package's diff touches, unchanged and green: `tests/test_graph_service.py` (every `apply_graph_update` test), `tests/test_graph_add_node.py`, `tests/test_graph_tools_bugs.py`, `tests/test_mastery_tier_unification.py`, `tests/test_quiz_scoring_e.py`, `tests/test_documents_routes.py`, `tests/test_migration_naming.py`, `tests/test_migrations.py`, `tests/test_event_capture_seams.py` (taxonomy pin untouched).
- `test_legacy_payload_table_trace_unchanged` passes with the literal committed in Task 5 — if Task 6 needs the literal changed, Task 6 is wrong.
- With `LEARNING_LOOP_ENABLED` unset or set: no route behaviour changes (no caller passes `evidence`).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` → all passed
2. `ls backend/db/migrations/*_learning_learner_state.sql` → 1 file
3. `grep -c '"evidence"' backend/services/graph_service.py` → ≥ 1
4. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` → `1 passed`
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` → `6 passed, 6 skipped` (inv 01, 02, 03, 07, 08, 11; one more passed if HANDOFF-02 reports asserting inv 10)
6. `cd backend && venv/bin/python -m pytest tests/test_learning_learner_state_migration.py -q` → `5 passed`
7. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
8. `grep -cE "^(EVIDENCE_NO_UPWARD_MIN_RUNG|LADDER_MAX_RUNG) = " backend/learning/params.py` → `2`
9. `grep -c "def _apply_evidence" backend/services/graph_service.py` → `1`; `grep -c "get_mastery_tier" backend/services/graph_service.py` → unchanged from `main` (legacy tiers stay)
10. `git diff --stat main...HEAD` lists only: `backend/learning/params.py`, `backend/learning/evidence.py`, `backend/learning/learner_state.py`, `backend/services/graph_service.py`, `backend/db/migrations/*_learning_learner_state.sql`, `backend/tests/test_learning_evidence_apply.py`, `backend/tests/test_learning_learner_state_migration.py`, `backend/tests/test_learning_loop_invariants.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-03.md,HANDOFF-01.md,LEDGER.md}`.
11. One E2E cycle under the lock: journeys pass, oracles exit 0.
12. `LEDGER.md` has rows `03 | evidence-state | done | …`, `01 | … | verified`, `02 | … | verified`.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-03.md` per the template; the Verify commands block is fixed above (Task 7). Headings, all kept even when "none": What changed · Symbols added · Constants chosen · Deviations from spec · Known gaps · Verify commands · Open questions for the series owner · Post-hoc changes.

## Do not

- Do not add a caller: no route, agent, tool, `SaplingDeps.pending_evidence` consumer, or `learning_loop_active` call. Do not mount `routes/learn_loop.py`. Do not touch `services/chat_stream.py`, `services/events_service.py`, `agents/*`, `routes/*`, `services/quiz_config.py`, `config.py`.
- Do not modify `learning/bkt.py`, `learning/fsrs.py`, or their tests. The only PKG-01 edit is the two † constants in `params.py`, as a separate first commit with the ledger/hand-off bookkeeping.
- Do not change one byte of the legacy `new_nodes`/`updated_nodes`/`new_edges` code or `_insert_mastery_event`. Do not reformat `graph_service.py`. Do not change `LEGACY_TRACE` after Task 5.
- Do not write `graph_nodes`, `graph_edges`, `node_mastery_events`, or `learner_state` from anywhere but `apply_graph_update`/`_apply_evidence`. Do not call `write_state` from `learner_state.py` itself.
- All Supabase access through `db/connection.py::table()`; no `httpx`, no `supabase` import. Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation; DDL verbatim from spec §4.
- No numeric literals in `learning/` or in `_apply_evidence` beyond the identity values `0`, `0.0`, `1.0`, and `+1` increments; every threshold and weight is a `params` name. No `lru_cache`. No `report_empty_result`.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines. Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec/Behaviour 3 and the spec file's §3.1/§3.3/§5 before guessing. A signature mismatch with PKG-01/02 is solved in the named adapter, never by editing the pure module.
2. `test_legacy_payload_table_trace_unchanged` red after Task 6 → your block runs on an empty `evidence`; `evidences` must be `[]` and `if evidences:` must be the only new statement the legacy path evaluates.
3. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
4. Never widen scope to unblock. Never disable a test to unblock.
5. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
