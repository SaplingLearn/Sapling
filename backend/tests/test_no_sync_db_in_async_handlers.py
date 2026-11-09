"""No sync PostgREST call on the event loop from an `async def` in routes/ (#117).

docs/design/async-db-client.md §4.2, static half. FastAPI runs a sync handler
in the threadpool, but an `async def` handler runs ON the event loop: a sync
`table(...).select(...)` there blocks every request on the replica (and every
SSE tutor stream) for a whole PostgREST round trip.

This walks the AST of every `routes/*.py` module (and of every module of the
#118 domain packages in ``DOMAIN_PACKAGES``) and flags, inside any
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
* a sync function that (transitively) makes one of those calls: one of the same
  module, or one a scanned module imports from another scanned module
  (``from services.<pkg>.<mod> import name`` / ``from .mod import name``, or
  ``from services.<pkg> import mod`` + ``mod.name(...)``, following package
  ``__init__`` re-exports). A split moved handler bodies and their sync
  helpers into sibling modules, so the walk must cross files to see them.

Passing the bound method or function to a hop is fine and is not a call:
``await run_in_threadpool(table("x").select, ...)`` /
``await run_in_threadpool(_helper, ...)`` (one hop mechanism: Starlette's
threadpool, AnyIO's 40-token limiter). The ``a*`` twins are the native fix
(``await table("x").aselect(...)``); a handler that awaits nothing else is
simplest as a plain ``def`` (FastAPI runs it in that same threadpool).

What it cannot see: a sync DB call reached through a function imported from
a module it does not scan (a flat ``services/*.py`` module, ``agents/``). The
runtime guard covers those (``db.sync_on_loop``; the
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
#: Every #118 domain package (the ``domains`` contract's source_modules in
#: .importlinter; a test pins the two together). Each holds handler bodies
#: moved out of routes/ verbatim, async ones included, so they stay in scope.
#: Scanned recursively (services/admin/analytics is a subpackage).
DOMAIN_PACKAGES = tuple(
    BACKEND / "services" / name
    for name in (
        "admin", "auth", "documents", "flashcards", "gradebook",
        "gradescope", "profile", "quiz", "social", "tutor",
    )
)

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


def _module_name(rel: str) -> str:
    """``services/quiz/attempts.py`` -> ``services.quiz.attempts``; a package
    ``__init__`` is the package itself."""
    name = rel.removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


class _Module:
    """One scanned file: its top-level functions and what it imports."""

    def __init__(self, source: str, rel: str):
        self.rel = rel
        self.name = _module_name(rel)
        self.is_package = rel.endswith("__init__.py")
        tree = ast.parse(source, filename=rel)
        self.top = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.sync_fns = {n.name: n for n in self.top if isinstance(n, ast.FunctionDef)}
        #: local name -> (module, name) for ``from <module> import name``
        self.names: dict[str, tuple[str, str]] = {}
        #: local name -> module, for ``import a.b as m`` (and, once every module
        #: is known, ``from a import b`` where ``a.b`` is a module)
        self.modules: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = self._absolute(node)
                for alias in node.names:
                    self.names[alias.asname or alias.name] = (base, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.modules[alias.asname] = alias.name

    def _absolute(self, node: ast.ImportFrom) -> str:
        if not node.level:
            return node.module or ""
        parts = self.name.split(".")
        # A package's own name is its package; a plain module drops itself.
        keep = len(parts) - node.level + (1 if self.is_package else 0)
        base = ".".join(parts[:keep])
        return f"{base}.{node.module}" if node.module else base


class _Universe:
    """Every scanned module, so a call resolves across files."""

    def __init__(self, sources: dict[str, str]):
        self.mods = {m.name: m for m in (_Module(src, rel) for rel, src in sources.items())}
        for mod in self.mods.values():
            for local, (base, name) in list(mod.names.items()):
                if f"{base}.{name}" in self.mods:
                    mod.modules[local] = f"{base}.{name}"
                    del mod.names[local]
        self.touches = self._touching()

    def _resolve_name(self, module: str, name: str, depth: int = 0):
        mod = self.mods.get(module)
        if mod is None or depth > 8:
            return None
        if name in mod.sync_fns:
            return (module, name)
        if name in mod.names:  # a re-export (package __init__)
            return self._resolve_name(*mod.names[name], depth + 1)
        return None

    def resolve(self, mod: _Module, call: ast.Call):
        """The (module, sync function) a call reaches, when a scanned module defines it."""
        f = call.func
        if isinstance(f, ast.Name):
            if f.id in mod.sync_fns:
                return (mod.name, f.id)
            if f.id in mod.names:
                return self._resolve_name(*mod.names[f.id])
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in mod.modules:
            return self._resolve_name(mod.modules[f.value.id], f.attr)
        return None

    def _touching(self) -> set[tuple[str, str]]:
        """Sync functions that reach the DB, transitively across scanned modules."""
        touches = {
            (mod.name, name)
            for mod in self.mods.values() for name, fn in mod.sync_fns.items()
            if any(hit for _c, hit in _db_calls_in(fn))
        }
        changed = True
        while changed:
            changed = False
            for mod in self.mods.values():
                for name, fn in mod.sync_fns.items():
                    if (mod.name, name) in touches:
                        continue
                    if any(self.resolve(mod, c) in touches for c in _calls_in(fn)):
                        touches.add((mod.name, name))
                        changed = True
        return touches

    def offenders(self) -> set[tuple[str, str, str]]:
        out: set[tuple[str, str, str]] = set()
        for mod in self.mods.values():
            for fn in mod.top:
                if not isinstance(fn, ast.AsyncFunctionDef):
                    continue
                for call, hit in _db_calls_in(fn):
                    if hit is None and self.resolve(mod, call) in self.touches:
                        hit = f"{_callee(call.func)}()"
                    if hit is not None:
                        out.add((mod.rel, fn.name, hit))
        return out


def _offenders_in(source: str, rel: str) -> set[tuple[str, str, str]]:
    return _Universe({rel: source}).offenders()


def _scanned_paths() -> list[Path]:
    paths = sorted(ROUTES.glob("*.py"))
    for package in DOMAIN_PACKAGES:
        paths += sorted(package.rglob("*.py"))
    return paths


def _all_offenders() -> set[tuple[str, str, str]]:
    sources = {p.relative_to(BACKEND).as_posix(): p.read_text() for p in _scanned_paths()}
    return _Universe(sources).offenders()


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


def test_the_checker_follows_helpers_across_sibling_modules():
    """A split moves a handler body and its sync helper into sibling modules:
    the walk must resolve the imported helper in the other file (absolute,
    relative, module-attribute and package-``__init__`` re-export forms)."""
    sources = {
        "services/probe/__init__.py": "from services.probe.store import load_row\n",
        "services/probe/store.py": """
from db.connection import table

def load_row(uid):
    return table("t").select("*", filters={"id": f"eq.{uid}"})

def _two_hops(uid):
    return load_row(uid)
""",
        "services/probe/handlers.py": """
from services.probe.store import load_row
from .store import _two_hops
from services.probe import store
from services.probe import load_row as reexported

async def bad_absolute(uid):
    load_row(uid)

async def bad_relative_transitive(uid):
    _two_hops(uid)

async def bad_module_attr(uid):
    store.load_row(uid)

async def bad_reexport(uid):
    reexported(uid)

async def good(uid):
    await run_in_threadpool(load_row, uid)
    await run_in_threadpool(store._two_hops, uid)
""",
        "routes/probe.py": """
from services.probe import load_row

async def bad_route(uid):
    load_row(uid)
""",
    }
    found = {(f, fn, what) for f, fn, what in _Universe(sources).offenders()}
    assert found == {
        ("services/probe/handlers.py", "bad_absolute", "load_row()"),
        ("services/probe/handlers.py", "bad_relative_transitive", "_two_hops()"),
        ("services/probe/handlers.py", "bad_module_attr", "load_row()"),
        ("services/probe/handlers.py", "bad_reexport", "reexported()"),
        ("routes/probe.py", "bad_route", "load_row()"),
    }


def test_every_domain_package_is_scanned():
    """DOMAIN_PACKAGES is the .importlinter ``domains`` contract's package list."""
    import configparser

    cfg = configparser.ConfigParser()
    cfg.read(BACKEND / ".importlinter")
    declared = set(cfg["importlinter:contract:domains"]["source_modules"].split())
    scanned = {f"services.{p.name}" for p in DOMAIN_PACKAGES}
    assert scanned == declared
    assert all(p.is_dir() for p in DOMAIN_PACKAGES)
