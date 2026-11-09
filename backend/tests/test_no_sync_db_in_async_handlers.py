"""No sync PostgREST call on the event loop from an `async def` in routes/ (#117).

docs/design/async-db-client.md §4.2, static half. FastAPI runs a sync handler
in the threadpool, but an `async def` handler runs ON the event loop: a sync
`table(...).select(...)` there blocks every request on the replica (and every
SSE tutor stream) for a whole PostgREST round trip.

This walks the AST of every `routes/*.py` module and flags, inside any
`async def` (handlers and the module's async helpers alike), an INLINE call to

* a sync verb on a `table(...)` handle (``select``, ``insert``, ...), inline
  (``table("x").select(...)``) or through a local name
  (``t = table("x")`` ... ``t.select(...)``), and through a module attribute
  (``db.table("x").select(...)``, ``connection.table(...)``),
* ``rpc(...)`` or ``page_all(...)``, bare or as an attribute
  (``connection.rpc(...)``),
* the sync rate limiter, ``check_rate_limit(...)`` / ``claim_rate_limit(...)``
  (bare or as an attribute): with ``stateless_rate_limit`` on it is a
  PostgREST call (use ``acheck_rate_limit`` / ``aclaim_rate_limit``),
* a sync function of the same module that (transitively, within the module)
  makes one of those calls.

Passing the bound method or function to a hop is fine and is not a call:
``await run_in_threadpool(table("x").select, ...)`` /
``await run_in_threadpool(_helper, ...)`` (one hop mechanism: Starlette's
threadpool, AnyIO's 40-token limiter). The ``a*`` twins are the native fix
(``await table("x").aselect(...)``); a handler that awaits nothing else is
simplest as a plain ``def`` (FastAPI runs it in that same threadpool).

What it cannot see: a sync DB call reached through an IMPORTED service
function. The runtime guard covers those (``db.sync_on_loop``; the
``no_sync_db_on_loop`` fixture in tests/conftest.py makes it raise).

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
#: services/request_limits' sync limiter: a DB call under `stateless_rate_limit`.
LIMITER_FUNCS = frozenset({"check_rate_limit", "claim_rate_limit"})

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


def _callee(func: ast.AST) -> str | None:
    """`name(...)` or `<anything>.name(...)` -> "name"."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_table_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _callee(node.func) == "table"


def _table_aliases(fn: ast.AST) -> set[str]:
    """Local names bound to a `table(...)` handle in `fn` (``t = table("x")``)."""
    names: set[str] = set()
    for node in _walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_table_call(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _direct_db_call(call: ast.Call, aliases: frozenset[str] = frozenset()) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in SYNC_VERBS:
        if _is_table_call(f.value):
            return f"table().{f.attr}"
        if isinstance(f.value, ast.Name) and f.value.id in aliases:
            return f"{f.value.id}.{f.attr}"
    name = _callee(f)
    if name in DB_FUNCS or name in LIMITER_FUNCS:
        return name
    return None


def _walk(fn: ast.AST):
    """Every node inside `fn`, not descending into nested defs/lambdas."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _calls_in(fn: ast.AST):
    """Every Call inside `fn`, not descending into nested defs/lambdas."""
    return (node for node in _walk(fn) if isinstance(node, ast.Call))


def _db_calls_in(fn: ast.AST):
    aliases = frozenset(_table_aliases(fn))
    for call in _calls_in(fn):
        yield call, _direct_db_call(call, aliases)


def _offenders(path: Path) -> set[tuple[str, str, str]]:
    return _offenders_in(path.read_text(), path.relative_to(BACKEND).as_posix())


def _offenders_in(source: str, rel: str) -> set[tuple[str, str, str]]:
    tree = ast.parse(source, filename=rel)
    top = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    sync_fns = {n.name: n for n in top if isinstance(n, ast.FunctionDef)}

    # Module-level sync functions that reach the DB, transitively in-module.
    touches: set[str] = {
        name for name, fn in sync_fns.items()
        if any(hit for _c, hit in _db_calls_in(fn))
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
        for call, hit in _db_calls_in(fn):
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
from db import connection
from db.connection import table, rpc
from services import request_limits
from services.request_limits import check_rate_limit, claim_rate_limit

def _reads():
    return table("t").select("*")

def _indirect():
    return _reads()

def _aliased():
    t = table("t")
    return t.select("*")

def _limited(uid):
    return check_rate_limit(f"x:{uid}", limit=1, window_sec=60)

async def bad_direct():
    table("t").insert({})

async def bad_rpc():
    rpc("fn", {})

async def bad_helper():
    _indirect()

async def bad_alias():
    handle = table("t")
    handle.update({}, filters={})

async def bad_alias_helper():
    _aliased()

async def bad_attr_forms():
    connection.rpc("fn", {})
    connection.table("t").delete(filters={})

async def bad_limiter():
    claim_rate_limit("k", limit=1, window_sec=60)
    request_limits.check_rate_limit("k", limit=1, window_sec=60)

async def bad_limiter_helper():
    _limited("u")

async def good():
    await run_in_threadpool(_indirect)
    await run_in_threadpool(table("t").select, "*")
    await table("t").aselect("*")
    handle = table("t")
    await handle.aselect("*")
    await run_in_threadpool(handle.select, "*")
    await request_limits.acheck_rate_limit("k", limit=1, window_sec=60)
    await run_in_threadpool(_limited, "u")
    def inner():
        table("t").select("*")
    return inner
"""
    found = {(fn, what) for _f, fn, what in _offenders_in(src, "routes/probe.py")}
    assert found == {
        ("bad_direct", "table().insert"),
        ("bad_rpc", "rpc"),
        ("bad_helper", "_indirect()"),
        ("bad_alias", "handle.update"),
        ("bad_alias_helper", "_aliased()"),
        ("bad_attr_forms", "rpc"),
        ("bad_attr_forms", "table().delete"),
        ("bad_limiter", "claim_rate_limit"),
        ("bad_limiter", "check_rate_limit"),
        ("bad_limiter_helper", "_limited()"),
    }
