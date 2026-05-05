# Sub-agent D — Extend the syllabus eval set

The syllabus eval set already exists at `backend/tests/evals/syllabus_extraction.py`
(landed with refactor #1). This sub-agent extends it with adapter-shape
evaluators that pin the new wire-format contract introduced by refactor
#4. WRITE the changes, verify imports, report back. Do NOT run against
live Gemini — cassettes get re-recorded later only if needed.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/4-syllabus-unification` (already checked out)

## Why

Refactor #4 doesn't change the agent's system prompt (so existing
cassettes stay valid). It DOES introduce a wire-format adapter
(`syllabus_to_wire_dict`) that the new `services/calendar_service.py`
path uses. The eval set today only checks `SyllabusAssignments` shape;
it doesn't check the **wire-format dict** shape that downstream
consumers expect.

Add evaluators that pin the wire-format contract so a future schema
drift on the adapter (or a regression in `syllabus_to_wire_dict`'s
output) gets caught in CI.

## What to read first

- `backend/tests/evals/syllabus_extraction.py` — entire file. Note the
  existing structure (Cases, Evaluators, `run_with_cassette` adapter,
  `cli_main` entrypoint). Mirror the shape.
- `backend/tests/evals/quiz_generation.py` — same pattern; the
  `MultipleChoiceShapeEvaluator` is a good reference for shape-pinning
  evaluators.
- `backend/tests/evals/_replay.py` — replay/record/live driver; reuse
  `run_with_cassette` and `cli_main` as-is.
- `backend/agents/syllabus_extraction.py` — agent's output schema.
- `backend/agents/tools/syllabus_adapter.py` (or wherever Sub-agent A
  put it) — the adapter under test.

## What to write

### Extend `tests/evals/syllabus_extraction.py`

Add these evaluators (each as a `@dataclass` `Evaluator` subclass,
matching the existing style in the file):

```python
@dataclass
class WireFormatRequiredKeysEvaluator(Evaluator[..., SyllabusAssignments]):
    """The adapter (`syllabus_to_wire_dict`) MUST produce the legacy
    required keys: assignments, warnings, raw_text. Future refactors
    that drop one would break consumers in `routes/calendar.py` and
    elsewhere; this evaluator catches that regression.
    """

    REQUIRED = {"assignments", "warnings", "raw_text"}

    def evaluate(self, ctx) -> float:
        from agents.tools.syllabus_adapter import syllabus_to_wire_dict
        wire = syllabus_to_wire_dict(ctx.output, raw_text="")
        return 1.0 if self.REQUIRED.issubset(set(wire.keys())) else 0.0


@dataclass
class AssignmentTypeNonNullEvaluator(Evaluator[..., SyllabusAssignments]):
    """Every assignment in the wire dict must carry `assignment_type`
    (the adapter defaults missing values to "other"). `routes/calendar.py`
    uses this field to bucket items by category in the UI; null breaks
    the rendering.
    """

    def evaluate(self, ctx) -> float:
        from agents.tools.syllabus_adapter import syllabus_to_wire_dict
        wire = syllabus_to_wire_dict(ctx.output, raw_text="")
        items = wire.get("assignments") or []
        return 1.0 if all(a.get("assignment_type") for a in items) else 0.0


@dataclass
class DueDateIsoStringEvaluator(Evaluator[..., SyllabusAssignments]):
    """Adapter must serialize the agent's `date | None` to ISO-8601
    strings (or None) — `insert_new_assignments` and
    `assignment_dedupe_key` expect strings, not date objects.
    """

    def evaluate(self, ctx) -> float:
        from agents.tools.syllabus_adapter import syllabus_to_wire_dict
        wire = syllabus_to_wire_dict(ctx.output, raw_text="")
        for a in wire.get("assignments") or []:
            v = a.get("due_date")
            if v is None:
                continue
            if not isinstance(v, str):
                return 0.0
            # 'YYYY-MM-DD' shape — quick sanity check, not a full parser.
            if len(v) != 10 or v[4] != "-" or v[7] != "-":
                return 0.0
        return 1.0
```

Wire all three new evaluators into `make_dataset()` alongside the
existing ones.

### Don't add new cases unless needed

Existing cases already exercise the agent path. The new evaluators
run on the same cassettes. If you find that the recorded cassette
output is missing a feature the new evaluators check (e.g. all
recorded assignments have null `assignment_type` because the agent
schema doesn't carry it — which is exactly what Sub-agent A may
have flagged), DO NOT update the cassette to satisfy the evaluator.
Instead:

1. Confirm the adapter's `assignment_type="other"` default kicks in.
2. The evaluator should pass against the recorded cassette without
   recording new ones.
3. If it doesn't, the adapter has a bug — flag it back to Sub-agent A.

If you decide a NEW case would meaningfully exercise something the
existing cases don't (e.g. an empty assignments list, or a syllabus
with grading categories but no assignments), add it. Cap at 1-2 new
cases — over-cassette-ing is expensive and the existing eval set has
proven sufficient for the agent's behavior since refactor #1 shipped.

## Verify

After writing:

```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -c "import ast; ast.parse(open('tests/evals/syllabus_extraction.py').read()); print('parses OK')"

python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('eval_mod', 'tests/evals/syllabus_extraction.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
ds = mod.make_dataset()
print(f'cases: {len(ds.cases)}')
print(f'evaluators: {[type(e).__name__ for e in ds.evaluators]}')
"
```

Confirm the three new evaluators appear in the print output.

If the file imports the adapter from `agents.tools.syllabus_adapter`
or `agents.syllabus_extraction` (whichever path Sub-agent A chose),
verify the import resolves:

```bash
python -c "from agents.tools.syllabus_adapter import syllabus_to_wire_dict; print('OK')"
# OR
python -c "from agents.syllabus_extraction import syllabus_to_wire_dict; print('OK')"
```

DO NOT actually run against live Gemini. Replay-mode evals run
out-of-band by the user.

## Constraints

- DO NOT modify `agents/syllabus_extraction.py` (sub-agent A's file).
- DO NOT modify `services/calendar_service.py` (sub-agent B's file).
- DO NOT modify `routes/calendar.py` (sub-agent C's file).
- DO NOT bump prompt hashes or invalidate existing cassettes.
- DO NOT commit. No ADRs.

## Report

- Lines added to `tests/evals/syllabus_extraction.py`.
- The three new evaluator class names.
- Whether you added new cases (and which) or relied entirely on
  existing recorded cassettes.
- Output of the verify smoke-test command (the case + evaluator count).

Aim for under 150 words.
