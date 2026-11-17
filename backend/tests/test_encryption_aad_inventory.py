"""Every 🔒 seal and open passes a binding (finding M13, phase-0 inventory).

docs/security/encryption-aad-plan.md: a v2 value opens only in the cell it was
sealed for, so a writer that forgets its binding writes legacy v1 (which the
strict-read switch will later refuse) and a reader that forgets it cannot open
v2 at all. This scan walks every application module and fails on a call to an
`services.encryption` seal/open helper without ``bind=``, or on the helper
passed around as a value (which hides the call from the scan).

`UNBOUND` is the reviewed list of what remains unbound, per file, with the
reason. It may only shrink: a new unbound call fails here.
"""
from __future__ import annotations

import ast
from pathlib import Path

from services import encryption

BACKEND = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"tests", "venv", ".venv", "__pycache__", "node_modules"}

HELPERS = {
    "encrypt", "decrypt", "encrypt_if_present", "decrypt_if_present", "decrypt_numeric",
    "encrypt_json", "decrypt_json", "decrypt_json_column", "encrypt_bytes", "decrypt_bytes",
}

#: path (relative to backend/) -> (unbound call count, why).
UNBOUND: dict[str, tuple[int, str]] = {
    "db/backfill_encryption.py": (
        6, "the old plaintext -> v1 backfill (offline). Its map names columns the "
           "registry no longer has; it skips enc2: by prefix, and "
           "db/backfill_encryption_aad.py binds whatever it writes."),
    "db/backfill_encryption_aad.py": (
        2, "_open_v1: opens a LEGACY value, which by definition has no AAD."),
    "services/account_bundle.py": (
        1, "the unlisted-column sweep probes a v1-shaped value in a column nobody "
           "registered, so there is no binding to give; v2 is caught by prefix."),
}


def _modules():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in SKIP_DIRS or any(p in SKIP_DIRS for p in rel.parts):
            continue
        if rel.as_posix() == "services/encryption.py":
            continue
        yield rel.as_posix(), path


def _unbound_sites(source: str) -> list[int]:
    tree = ast.parse(source)
    names: set[str] = set()   # helpers imported by name (maybe aliased)
    modules: set[str] = set()  # aliases of the encryption module itself
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "services.encryption":
            for a in node.names:
                if a.name in HELPERS:
                    names.add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "services":
            for a in node.names:
                if a.name == "encryption":
                    modules.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "services.encryption":
                    modules.add(a.asname or "services")
    if not names and not modules:
        return []

    def is_helper(func: ast.AST) -> bool:
        if isinstance(func, ast.Name):
            return func.id in names
        if isinstance(func, ast.Attribute) and func.attr in HELPERS:
            v = func.value
            if isinstance(v, ast.Name) and v.id in modules:
                return True
            # `services.encryption.decrypt(...)`
            return (isinstance(v, ast.Attribute) and v.attr == "encryption"
                    and isinstance(v.value, ast.Name) and v.value.id in modules)
        return False

    called: set[int] = set()
    sites: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and is_helper(node.func):
            called.add(id(node.func))
            if not any(k.arg == "bind" for k in node.keywords):
                sites.append(node.lineno)
    for node in ast.walk(tree):
        # A helper referenced but not called (passed as a value) hides its call.
        if isinstance(node, (ast.Name, ast.Attribute)) and is_helper(node) \
                and isinstance(getattr(node, "ctx", None), ast.Load) and id(node) not in called:
            sites.append(node.lineno)
    return sorted(sites)


def test_every_seal_and_open_is_bound_or_listed():
    found = {}
    for rel, path in _modules():
        sites = _unbound_sites(path.read_text())
        if sites:
            found[rel] = sites
    problems = []
    for rel, sites in found.items():
        allowed = UNBOUND.get(rel, (0, ""))[0]
        if len(sites) > allowed:
            problems.append(f"{rel}: {len(sites)} unbound (allowed {allowed}) at lines {sites}")
    stale = [rel for rel, (n, _) in UNBOUND.items() if len(found.get(rel, [])) < n]
    assert not problems, (
        "seal/open without bind= (pass bind=encryption.bind(table, column, row)):\n  "
        + "\n  ".join(problems)
    )
    assert not stale, f"UNBOUND allows more than these files use; shrink it: {stale}"


def test_registry_is_consistent():
    pairs = [(s.table, s.column) for s in encryption.ENCRYPTED_COLUMNS]
    assert len(pairs) == len(set(pairs))
    for spec in encryption.ENCRYPTED_COLUMNS:
        assert spec.kind in {encryption.TEXT, encryption.JSON, encryption.NUMERIC, encryption.BYTES}
        assert spec.key and spec.pk
        if spec.aad_table or spec.aad_column:
            # A column sealed for another cell must name a registered one.
            encryption.column_spec(spec.aad_table, spec.aad_column)
