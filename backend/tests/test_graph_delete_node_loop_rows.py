"""A deleted concept node takes its learning-loop rows with it (PR #866 C9).

learner_state, misconceptions and the evidence journal cascade from
graph_nodes. The loop rows keyed by (user_id, node_id) with NO foreign key —
posttest_poses, posttest_skips, and the append-only teach-prompt records
learning_prequestions / learning_self_explanations — are removed by
`graph_service.delete_node` itself: the first two directly, the last two
through the service-only `learning_node_erase` RPC
(20261118195124_learning_session_node_erase.sql). Course delete drops one
term's enrollment and never touches a node (#766), so it orphans nothing.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services import graph_service

MIGRATION = next(
    (Path(__file__).resolve().parents[1] / "db" / "migrations").glob("*_learning_session_node_erase.sql")
)


class _Db:
    """Every table call and rpc in order; graph_nodes answers `node_rows`."""

    def __init__(self, node_rows):
        self.node_rows, self.log = node_rows, []

    def table(self, name):
        db = self
        m = MagicMock(name=name)

        def select(*_a, **_k):
            db.log.append(("select", name))
            return list(db.node_rows) if name == "graph_nodes" else []

        def delete(*a, **k):
            db.log.append(("delete", name, dict(k.get("filters") or (a[0] if a else {}))))
            return []

        m.select.side_effect = select
        m.delete.side_effect = delete
        return m

    def rpc(self, fn, params):
        self.log.append(("rpc", fn, dict(params)))
        return {"learning_self_explanations": 0, "learning_prequestions": 0}


@pytest.fixture
def db():
    fake = _Db([{"id": "n1", "course_id": "c1"}])
    with patch.object(graph_service, "table", side_effect=fake.table), \
         patch.object(graph_service, "rpc", side_effect=fake.rpc), \
         patch.object(graph_service, "_refresh_course_context"), \
         patch("services.academics.user_offering_ids_for_course", return_value=["o1"]):
        yield fake


def test_delete_node_removes_the_nodes_loop_rows_after_the_node(db):
    assert graph_service.delete_node("u1", "n1") == {"deleted": True}
    deletes = [e for e in db.log if e[0] in ("delete", "rpc")]
    assert [e[1] for e in deletes] == [
        "graph_edges", "graph_edges", "graph_nodes",
        "posttest_poses", "posttest_skips", "learning_node_erase",
    ]
    owned = {"user_id": "eq.u1", "node_id": "eq.n1"}
    assert deletes[3][2] == owned and deletes[4][2] == owned
    assert deletes[5][2] == {"p_user_id": "u1", "p_node_id": "n1"}


def test_a_retry_after_a_failed_clean_up_finishes_it(db):
    """The node is gone but its rows are not (the clean-up failed after the
    node delete): the retry's 404 still clears them, owner-scoped."""
    db.node_rows = []
    assert graph_service.delete_node("u1", "n1") == {"error": "Node not found", "deleted": False}
    assert [e[1] for e in db.log if e[0] in ("delete", "rpc")] == [
        "posttest_poses", "posttest_skips", "learning_node_erase",
    ]


def test_a_failed_clean_up_raises_and_never_runs_before_the_node_delete(db):
    db.rpc = MagicMock(side_effect=RuntimeError("PostgREST down"))
    with patch.object(graph_service, "rpc", db.rpc), pytest.raises(RuntimeError):
        graph_service.delete_node("u1", "n1")
    assert ("delete", "graph_nodes", {"id": "eq.n1", "user_id": "eq.u1"}) in db.log


def test_course_delete_touches_no_node_and_so_no_loop_row():
    with patch.object(graph_service, "table") as tbl, \
         patch.object(graph_service, "rpc") as rpc, \
         patch.object(graph_service, "_refresh_course_context"), \
         patch("services.academics.current_term", return_value={"id": "fall-2026"}), \
         patch("services.academics.user_offering_ids_for_course", return_value=["o1"]), \
         patch("services.academics.term_for_offering", return_value={"id": "fall-2026"}):
        assert graph_service.delete_course("u1", "c1") == {"deleted": True}
    assert {c.args[0] for c in tbl.call_args_list} == {"enrollments"}
    rpc.assert_not_called()


def test_the_erase_function_deletes_only_the_teach_prompt_rows_of_one_students_node():
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
    body = sql[sql.index("FUNCTION learning_node_erase"):]
    body = body[: body.index("$$;")]
    assert "SECURITY DEFINER" in body and "SET search_path = public, pg_temp" in body
    assert re.findall(r"DELETE FROM (\w+) WHERE user_id = p_user_id AND node_id = p_node_id;", body) == [
        "learning_self_explanations", "learning_prequestions",
    ]
    assert len(re.findall(r"\bDELETE\b", body)) == 2
    assert "GRANT EXECUTE ON FUNCTION learning_node_erase(text, text) TO service_role;" in sql
    assert "REVOKE ALL ON FUNCTION learning_node_erase(text, text) FROM PUBLIC;" in sql


def test_the_session_erase_function_clears_text_and_keeps_the_rows():
    """C8's twin: a session delete clears the text only (A76 reads the row)."""
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
    body = sql[sql.index("FUNCTION learning_session_text_erase"):]
    body = body[: body.index("$$;")]
    assert "SECURITY DEFINER" in body and "DELETE" not in body
    assert "SET reply_text = NULL, text_erased_at = clock_timestamp()" in body
    assert "SET guess_json = NULL, text_erased_at = clock_timestamp()" in body
    assert body.count("WHERE user_id = p_user_id AND session_id = p_session_id") == 2
    assert "GRANT EXECUTE ON FUNCTION learning_session_text_erase(text, text) TO service_role;" in sql


def test_a_failed_clean_up_still_refreshes_the_course_context():
    """#866 review C9: the node is deleted before its loop rows are erased. If
    that erase raises, the error still reaches the caller (a retry finishes
    the erase through the 404 path), but the course context is refreshed now,
    because the retry's 404 path has no course to refresh."""
    from unittest.mock import MagicMock, patch

    import pytest

    from services import graph_service

    fake = _Db([{"id": "n1", "course_id": "c1"}])
    refresh = MagicMock()
    down = MagicMock(side_effect=RuntimeError("PGRST202: learning_node_erase not found"))
    with patch.object(graph_service, "table", side_effect=fake.table), \
         patch.object(graph_service, "rpc", down), \
         patch.object(graph_service, "_refresh_course_context", refresh), \
         patch("services.academics.user_offering_ids_for_course", return_value=["o1"]):
        with pytest.raises(RuntimeError):
            graph_service.delete_node("u1", "n1")
    assert ("delete", "graph_nodes", {"id": "eq.n1", "user_id": "eq.u1"}) in fake.log
    refresh.assert_called_once_with("o1", "u1")
