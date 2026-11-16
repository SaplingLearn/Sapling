"""#118: apply_graph_update's typed input (GraphUpdate) and its import fix.

* the legacy dict and the model drive byte-identical writes;
* the model is exactly as lenient as the dict-walking code it replaced
  (blank entries skipped, junk scalars defaulted, unknown keys ignored), and
  input that used to crash still raises — now before the first write;
* the post-update side effects are reached through module-level imports (no
  function-local import under a broad except), and a failing context refresh
  is logged instead of silently passed over.
"""

from __future__ import annotations

import ast
import inspect
import itertools
import json
import logging
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

import services.graph_service as gs
from services.graph_update_model import GraphUpdate, NewEdge, NewNode, UpdatedNode

BACKEND = Path(__file__).resolve().parents[1]

EXISTING = [
    {"id": "n1", "concept_name": "Loops", "mastery_score": 0.3,
     "times_studied": 1, "course_id": "c1"},
]


def _run(graph_update, *, course_id="c1", existing=EXISTING, refresh=None):
    """Run apply_graph_update with every collaborator faked; return (result, write log)."""
    log: list = []
    ids = itertools.count()

    def table(name):
        m = MagicMock()

        def verb(v):
            def call(*a, **k):
                log.append((name, v, json.dumps([a, k], default=str)))
                if v == "select":
                    return [dict(r) for r in existing]
                return []
            return call
        for v in ("select", "upsert", "insert", "update", "delete"):
            setattr(m, v, verb(v))
        return m

    def rpc(fn, params):
        log.append(("rpc", fn, json.dumps(params)))
        return [{"before_score": 0.3, "after_score": 0.45}]

    fixed_now = MagicMock()
    fixed_now.now.return_value.isoformat.return_value = "2026-11-08T00:00:00+00:00"
    with patch.object(gs, "table", table), patch.object(gs, "rpc", rpc), \
            patch.object(gs.uuid, "uuid4", lambda: f"uuid-{next(ids)}"), \
            patch.object(gs, "datetime", fixed_now), \
            patch.object(gs, "touch_streak_safe", lambda u: log.append(("streak", u))), \
            patch("services.academics.user_offering_ids_for_course",
                  lambda u, c: [f"off-{c}"]), \
            patch("services.course_context_service.refresh_course_context",
                  refresh or (lambda o, user_id: log.append(("refresh", o, user_id)))), \
            patch("services.achievement_service.check_achievements",
                  lambda u, e, d: log.append(("achievement", e))):
        result = gs.apply_graph_update("u1", graph_update, course_id=course_id)
    return result, log


MIXED = {
    "new_nodes": [
        {"concept_name": "  Big   O ", "initial_mastery": "0.4"},
        {"concept_name": "big o"},                      # in-batch duplicate
        {"concept_name": "   "},                        # blank: skipped
        {"concept_name": "Trees", "initial_mastery": 9},  # clamped to 1.0
    ],
    "updated_nodes": [
        {"concept_name": " loops ", "mastery_delta": 0.15, "reason": "quiz",
         "event_type": " quiz_correct "},
        {"concept_name": "Loops", "mastery_delta": "junk", "event_type": "  "},
        {"concept_name": "Unknown", "mastery_delta": 0.2},
        {"concept_name": None},
    ],
    "new_edges": [
        {"source": "loops", "target": " big  o", "strength": 0},  # 0 → 0.5 (as before)
        {"source": "Trees", "target": "trees"},                   # self-edge: skipped
        {"source": "Loops", "target": "Nope"},                    # unresolved: skipped
        {"source": "Trees", "target": "Loops", "strength": 7,
         "relationship_type": "prerequisite"},
    ],
    "unknown_key": {"ignored": True},
}


class TestDictAndModelAreEquivalent:
    def test_dict_and_model_inputs_write_identically(self):
        from_dict = _run(MIXED)
        from_model = _run(GraphUpdate.model_validate(MIXED))
        assert from_dict == from_model

    def test_model_built_from_sub_models_matches_dict(self):
        model = GraphUpdate(
            new_nodes=[NewNode(concept_name="X", initial_mastery=0.2)],
            updated_nodes=[UpdatedNode(concept_name="Loops", mastery_delta=0.1)],
            new_edges=[NewEdge(source="X", target="Loops")],
        )
        as_dict = {
            "new_nodes": [{"concept_name": "X", "initial_mastery": 0.2}],
            "updated_nodes": [{"concept_name": "Loops", "mastery_delta": 0.1}],
            "new_edges": [{"source": "X", "target": "Loops"}],
        }
        assert _run(model) == _run(as_dict)

    def test_mixed_batch_writes_exactly_these_rows(self):
        result, log = _run(MIXED)
        assert result == [
            {"concept": "Loops", "before": 0.3, "after": 0.45},
            {"concept": "Loops", "before": 0.3, "after": 0.45},
        ]
        writes = [(t, v, json.loads(body)) for t, v, body in
                  (e for e in log if e[0] in ("graph_nodes", "graph_edges", "node_mastery_events")
                   and e[1] != "select")]
        node_rows = [w[2][0][0] for w in writes if w[0] == "graph_nodes"]
        assert [(r["concept_name"], r["mastery_score"]) for r in node_rows] == [
            ("Big O", 0.4), ("Trees", 1.0),
        ]
        events = [w[2][0][0] for w in writes if w[0] == "node_mastery_events"]
        assert events[0]["event_type"] == "quiz_correct"
        assert events[0]["reason"] == "quiz" and events[0]["delta"] == 0.15
        assert "event_type" not in events[1]       # blank → omitted, column stays NULL
        assert events[1]["delta"] == 0.0 and events[1]["reason"] == ""
        edges = [w[2][0][0] for w in writes if w[0] == "graph_edges"]
        assert [(e["strength"], e["relationship_type"]) for e in edges] == [
            (0.5, "related"), (1.0, "prerequisite"),
        ]
        assert ("refresh", "off-c1", "u1") in log
        assert [e[1] for e in log if e[0] == "achievement"] == [
            "graph_nodes_count", "concepts_mastered", "courses_with_mastery",
        ]


class TestLenience:
    def test_missing_lists_are_empty(self):
        result, log = _run({})
        assert result == []
        assert not [e for e in log if e[1] in ("upsert", "insert")]

    def test_explicit_none_fields_keep_their_old_defaults(self):
        m = GraphUpdate.model_validate({
            "new_nodes": [{"concept_name": None, "initial_mastery": None}],
            "updated_nodes": [{"concept_name": "A", "mastery_delta": None, "reason": None}],
            "new_edges": [{"source": "a", "target": "b", "strength": None,
                           "relationship_type": None}],
        })
        assert m.new_nodes[0].concept_name == "" and m.new_nodes[0].initial_mastery == 0.0
        # reason / relationship_type were always written verbatim, None included.
        assert m.updated_nodes[0].reason is None and m.updated_nodes[0].mastery_delta == 0.0
        assert m.new_edges[0].strength == 0.5 and m.new_edges[0].relationship_type is None

    def test_updated_node_name_is_strip_only(self):
        assert UpdatedNode.model_validate({"concept_name": "  a   b "}).concept_name == "a   b"
        assert NewNode.model_validate({"concept_name": "  a   b "}).concept_name == "a b"

    @pytest.mark.parametrize("bad, exc", [
        ({"updated_nodes": None}, ValidationError),
        ({"new_nodes": ["not a mapping"]}, ValidationError),
        ({"new_edges": [{"source": 7, "target": "x"}]}, AttributeError),
    ])
    def test_input_that_crashed_still_raises_before_any_write(self, bad, exc):
        update = {"new_nodes": [{"concept_name": "Written first before #118"}], **bad}
        with pytest.raises(exc):
            _run(update)
        # Validation happens up front now: not even the existing-node read runs.
        with patch.object(gs, "table") as table, pytest.raises(exc):
            gs.apply_graph_update("u1", update)
        table.assert_not_called()


class TestImportFix:
    HELPERS = (
        "apply_graph_update", "_existing_nodes_by_name", "_upsert_new_nodes",
        "_mastery_event_row", "_apply_mastery_updates", "_upsert_new_edges",
        "_refresh_touched_course_contexts", "_dispatch_graph_achievements",
    )

    def test_no_function_local_imports_on_the_update_path(self):
        """No import under a broad except. The ONE function-level import is
        course_context_service's in _refresh_touched_course_contexts (it keeps
        the agents stack and its loop off graph_service's import), and it is a
        top-level statement of that function, outside any try."""
        for name in self.HELPERS:
            fn = ast.parse(textwrap.dedent(inspect.getsource(getattr(gs, name)))).body[0]
            local = [n for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))]
            if name != "_refresh_touched_course_contexts":
                assert not local, f"{name} imports inside the function"
                continue
            assert [ast.unparse(n) for n in local] == [
                "from services import course_context_service"]
            assert local[0] in fn.body, "the import must not sit inside a try/loop"

    @pytest.mark.parametrize("first", [
        "services.graph_service",
        "services.course_context_service",
        "services.achievement_service",
        "services.academics",
        "agents.tools.graph",
    ])
    def test_import_order_has_no_cycle(self, first):
        code = (
            f"import {first}\n"
            "import services.graph_service as gs\n"
            "from services import course_context_service\n"
            "assert course_context_service.refresh_course_context\n"
            "assert gs.achievement_service.check_achievements\n"
            "assert gs.academics.user_offering_ids_for_course\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                              capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr

    def test_importing_graph_service_stays_off_the_agents_stack(self):
        code = (
            "import sys\n"
            "import services.graph_service\n"
            "assert 'services.course_context_service' not in sys.modules\n"
            "assert not [m for m in sys.modules if m == 'agents' or m.startswith('agents.')]\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                              capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr

    def test_a_refresh_import_error_propagates(self, monkeypatch):
        """A broken course_context_service import is a bug, not a failed
        refresh: it must surface, never be logged and passed over."""
        import services

        monkeypatch.setitem(sys.modules, "services.course_context_service", None)
        monkeypatch.delattr(services, "course_context_service", raising=False)
        with patch("services.academics.user_offering_ids_for_course", lambda u, c: ["off-c1"]):
            with pytest.raises(ImportError):
                gs._refresh_touched_course_contexts("u1", {"c1"})

    def test_refresh_failure_is_logged_not_swallowed(self, caplog):
        def boom(offering_id, user_id):
            raise RuntimeError("context down")
        with caplog.at_level(logging.WARNING, logger="services.graph_service"):
            result, _ = _run({"updated_nodes": [{"concept_name": "Loops", "mastery_delta": 0.1}]},
                             refresh=boom)
        assert result  # the graph write still reports its change
        rec = [r for r in caplog.records if "course-context refresh failed" in r.getMessage()]
        assert rec and rec[0].exc_info and "off-c1" in rec[0].getMessage()
