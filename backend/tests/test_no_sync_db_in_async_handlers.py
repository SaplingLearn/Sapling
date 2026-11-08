"""No sync PostgREST call on the event loop from an `async def` in routes/ (#117).

docs/design/async-db-client.md §4.2, static half. FastAPI runs a sync handler
in the threadpool, but an `async def` handler runs ON the event loop: a sync
`table(...).select(...)` there blocks every request on the replica (and every
SSE tutor stream) for a whole PostgREST round trip.

This walks the AST of every `routes/*.py` module and flags, inside any
`async def` (handlers and the module's async helpers alike), an INLINE call to

* a sync verb on a `table(...)` handle (``select``, ``insert``, ...),
* ``rpc(...)`` or ``page_all(...)``,
* a sync function of the same module that (transitively, within the module)
  makes one of those calls.

Passing the bound method or function to a hop is fine and is not a call:
``await run_in_threadpool(table("x").select, ...)``,
``await asyncio.to_thread(_helper, ...)``. The ``a*`` twins are the native
fix (``await table("x").aselect(...)``).

What it cannot see: a sync DB call reached through an IMPORTED service
function. The runtime guard covers those (``db.sync_on_loop``; the
``no_sync_db_on_loop`` fixture in tests/db_fakes.py makes it raise).

``ALLOWLIST`` is a ratchet, in the style of test_migration_naming.py: it may
only shrink. A new offender fails CI; fixing a listed one fails CI too until it
is removed from the list.
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROUTES = BACKEND / "routes"

SYNC_VERBS = frozenset({"select", "select_with_count", "insert", "update", "upsert", "delete"})
DB_FUNCS = frozenset({"rpc", "page_all"})

#: (routes file, async function, what it calls inline) -> why it is tolerated.
#: May only shrink.
ALLOWLIST: dict[tuple[str, str, str], str] = {
    # Measured on main at #117 wave 0 (the design doc counted only the five
    # DIRECT offenders; the in-module transitive walk finds these too). Each
    # converts with its router's wave (design §4.1) and leaves this list.
    ("routes/documents.py", "upload_document", "_validate_user()"):
        "wave 4 (documents CRUD; the upload pipeline is moving to the worker, #116)",
    ("routes/documents.py", "upload_document_sync", "_validate_user()"):
        "wave 4 (documents CRUD; the upload pipeline is moving to the worker, #116)",
    ("routes/learn.py", "_action_turn", "_get_session_offering_id()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_action_turn", "_load_message_history()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_action_turn", "_prepare_chat_run()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_action_turn", "save_message()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_chat_turn_json", "_get_session_offering_id()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_chat_turn_json", "_load_message_history()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_chat_turn_json", "_save_turn_rows()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_chat_via_agent", "_prepare_chat_run()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_start_session_agent", "_get_course_id_for_topic()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "_start_session_agent", "_prepare_chat_run()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "chat", "_persisted_turn()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "chat_stream", "_get_session_offering_id()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "chat_stream", "_load_message_history()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "chat_stream", "_persisted_turn()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "chat_stream", "_prepare_chat_run()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "start_session_stream", "_get_course_id_for_topic()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/learn.py", "start_session_stream", "_prepare_chat_run()"): "wave 3 (learn.py + the tutor stream)",
    ("routes/notes.py", "create", "_course_meta()"): "later wave (notes router)",
    ("routes/notes.py", "list_user_notes", "_course_meta()"): "later wave (notes router)",
    ("routes/notes.py", "read", "_course_meta()"): "later wave (notes router)",
}


def _is_table_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "table")


def _direct_db_call(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in SYNC_VERBS and _is_table_call(f.value):
        return f"table().{f.attr}"
    if isinstance(f, ast.Name) and f.id in DB_FUNCS:
        return f.id
    return None


def _calls_in(fn: ast.AST):
    """Every Call inside `fn`, not descending into nested defs/lambdas."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _offenders(path: Path) -> set[tuple[str, str, str]]:
    return _offenders_in(path.read_text(), path.relative_to(BACKEND).as_posix())


def _offenders_in(source: str, rel: str) -> set[tuple[str, str, str]]:
    tree = ast.parse(source, filename=rel)
    top = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    sync_fns = {n.name: n for n in top if isinstance(n, ast.FunctionDef)}

    # Module-level sync functions that reach the DB, transitively in-module.
    touches: set[str] = {
        name for name, fn in sync_fns.items()
        if any(_direct_db_call(c) for c in _calls_in(fn))
    }
    changed = True
    while changed:
        changed = False
        for name, fn in sync_fns.items():
            if name in touches:
                continue
            if any(isinstance(c.func, ast.Name) and c.func.id in touches for c in _calls_in(fn)):
                touches.add(name)
                changed = True

    out: set[tuple[str, str, str]] = set()
    for fn in top:
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for call in _calls_in(fn):
            hit = _direct_db_call(call)
            if hit is None and isinstance(call.func, ast.Name) and call.func.id in touches:
                hit = f"{call.func.id}()"
            if hit is not None:
                out.add((rel, fn.name, hit))
    return out


def _all_offenders() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in sorted(ROUTES.glob("*.py")):
        found |= _offenders(path)
    return found


def test_no_new_sync_db_calls_on_the_event_loop():
    new = sorted(_all_offenders() - set(ALLOWLIST))
    assert not new, (
        "sync PostgREST call(s) inline in an `async def` under routes/ (they block "
        "the event loop): " + "; ".join(f"{f}::{fn} -> {what}" for f, fn, what in new)
        + ". Use the a* twin (`await table(...).aselect(...)`), or hop: "
        "`await run_in_threadpool(fn, ...)`."
    )


def test_the_allowlist_only_shrinks():
    gone = sorted(set(ALLOWLIST) - _all_offenders())
    assert not gone, f"fixed (remove from ALLOWLIST): {gone}"


def test_the_checker_sees_the_shapes_it_claims_to():
    src = """
from db.connection import table, rpc

def _reads():
    return table("t").select("*")

def _indirect():
    return _reads()

async def bad_direct():
    table("t").insert({})

async def bad_rpc():
    rpc("fn", {})

async def bad_helper():
    _indirect()

async def good():
    await run_in_threadpool(_indirect)
    await run_in_threadpool(table("t").select, "*")
    await table("t").aselect("*")
    def inner():
        table("t").select("*")
    return inner
"""
    found = {(fn, what) for _f, fn, what in _offenders_in(src, "routes/probe.py")}
    assert found == {
        ("bad_direct", "table().insert"),
        ("bad_rpc", "rpc"),
        ("bad_helper", "_indirect()"),
    }
