"""Code-size ratchet for architecture-hardening Phase 4, "Domain modules" (#118).

Phase 4 is done when no route file is over 600 lines and no function is over
complexity 25 (docs/architecture-hardening-plan.md). Neither is true today, and
the files that miss it most (routes/quiz.py, routes/learn.py,
routes/documents.py) are under active edit by open PRs, so they cannot be split
yet. This ratchet stops things getting worse in the meantime:

  complexity        every function ruff's C901 (McCabe) scores above
                    ``[lint.mccabe] max-complexity`` in ruff.toml is listed in
                    code_size_baseline.json with its current score. A function
                    that is not listed may not cross the limit; a listed one
                    may not score higher than its entry.
  route_file_lines  every ``routes/**/*.py`` file over ROUTE_FILE_MAX_LINES is
                    listed with its current line count. A file that is not
                    listed may not cross the limit; a listed one may not grow.

Complexity entries are keyed ``<file>::<qualname>`` — ``Class.method`` for a
method, ``outer.<locals>.inner`` for a nested function — so two functions that
share a name are each held to their own ceiling.

Test code (``tests/``) is out of scope for the complexity ceiling — Phase 4 is
about the app's domain code, and ruff.toml exempts it with a ``tests/**`` entry.

The measurement runs ruff ``--isolated``: ruff.toml's excludes, per-file-ignores
(plain or ``extend-``), ignore lists and ``# noqa`` comments cannot hide a
function from it. ``c901_config_bypasses`` additionally keeps ruff.toml free of
anything that would hide a function from plain ``ruff check .``.

Both lists can only shrink. ``tests/test_code_size_ratchet.py`` enforces them
in the normal pytest lane — growth and new offenders fail; an entry that is now
higher than it needs to be only warns (so two PRs that each shrink a file cannot
leave main red between them) and asks for ``--shrink``. ``ruff check .``
additionally enforces C901 for every file not baselined in ruff.toml (ruff can
only baseline per FILE, so the per-function ceilings live here).

Usage, from backend/:

    python scripts/code_size_ratchet.py           # report; exit 1 on a violation
    python scripts/code_size_ratchet.py --shrink  # lower the baseline to today's numbers

``--shrink`` only ever lowers an entry or deletes one that is back under the
limit; it never adds or raises one, and it exits 1 if a violation remains after
the write. It cannot re-key either: a move-only split that renames a file or a
function must move its baseline key (and its ruff.toml C901 entry) by hand in
the same change. Raising an entry is a hand edit to the JSON, which shows up in
review — split the function or file instead whenever you can (the target layout
is docs/design/domain-modules.md).

Complexity is ruff's McCabe count, which does not score boolean operators, so it
reads lower than radon/lizard on the same code; the 25 in the Phase 4 target is
measured with this tool.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys
import tomllib

BACKEND = pathlib.Path(__file__).resolve().parent.parent
BASELINE_FILE = "code_size_baseline.json"
ROUTE_FILE_MAX_LINES = 600
# Directories exempt from the complexity ceiling: excluded from the measuring
# ruff run, and ruff.toml carries a matching ``"<dir>**" = ["C901"]``
# per-file-ignores entry for each so ``ruff check .`` agrees.
COMPLEXITY_EXEMPT_DIRS = ("tests/",)

_MESSAGE = re.compile(r"^`(?P<name>[^`]+)` is too complex \((?P<score>\d+) > \d+\)$")


def _ruff_config(root: pathlib.Path) -> dict:
    return tomllib.loads((root / "ruff.toml").read_text())


def max_complexity(root: pathlib.Path = BACKEND) -> int:
    """The C901 limit configured in ruff.toml — the single source of truth."""
    return int(_ruff_config(root)["lint"]["mccabe"]["max-complexity"])


def _covers_c901(code: str) -> bool:
    """Whether a ruff rule selector (``C901``, ``C90``, ``C``, ``ALL``…) includes C901."""
    return code == "ALL" or (bool(code) and "C901".startswith(code))


def c901_ignored_files(root: pathlib.Path = BACKEND) -> set[str]:
    """Files ruff.toml exempts from C901 via per-file-ignores (not counting the
    ``COMPLEXITY_EXEMPT_DIRS`` globs)."""
    ignores = _ruff_config(root).get("lint", {}).get("per-file-ignores", {})
    exempt_globs = {f"{d}**" for d in COMPLEXITY_EXEMPT_DIRS}
    return {
        path
        for path, codes in ignores.items()
        if any(_covers_c901(c) for c in codes) and path not in exempt_globs
    }


def c901_config_bypasses(root: pathlib.Path = BACKEND) -> list[str]:
    """ruff.toml settings that would hide a function from ``ruff check .``'s C901.

    The ratchet's own measurement runs ``--isolated`` and ignores all of them;
    this keeps plain ``ruff check .`` honest too. The only sanctioned C901
    exemptions are the ``lint.per-file-ignores`` entries kept in sync with the
    baseline (``c901_ignored_files``) and the ``COMPLEXITY_EXEMPT_DIRS`` globs.
    """
    config = _ruff_config(root)
    lint = config.get("lint", {})
    exempt = tuple(COMPLEXITY_EXEMPT_DIRS)
    problems = []
    if "extend" in config:
        problems.append("`extend` pulls in another config the ratchet cannot see")
    for scope, table in (("", config), ("lint.", lint)):
        for key in ("include", "extend-include"):
            if key in table:
                problems.append(f"`{scope}{key}` narrows which files ruff checks")
        for key in ("exclude", "extend-exclude"):
            for pattern in table.get(key, []):
                if not pattern.startswith(exempt):
                    problems.append(f"`{scope}{key}` hides {pattern!r} from ruff")
        for key in ("ignore", "extend-ignore"):
            for code in table.get(key, []):
                if _covers_c901(code):
                    problems.append(f"`{scope}{key}` contains {code!r}, which switches C901 off")
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            if scope == "lint." and key == "per-file-ignores":
                continue  # the sanctioned, baseline-synced list
            for path, codes in table.get(key, {}).items():
                if any(_covers_c901(c) for c in codes) and not path.startswith(exempt):
                    problems.append(f"`{scope}{key}` exempts {path!r} from C901")
    for path, codes in lint.get("per-file-ignores", {}).items():
        for code in codes:
            if _covers_c901(code) and code != "C901":
                problems.append(
                    f"`lint.per-file-ignores` uses {code!r} for {path!r}; spell it 'C901'"
                )
    selected = [*lint.get("select", []), *lint.get("extend-select", [])]
    if not any(_covers_c901(c) for c in selected):
        problems.append("C901 is not in `lint.select`")
    return problems


def _qualnames(path: pathlib.Path) -> dict[int, tuple[str, str]]:
    """``{line of the def: (name, qualname)}`` for every function in ``path``.

    The qualname follows Python's ``__qualname__``: ``Class.method``,
    ``outer.<locals>.inner``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[int, tuple[str, str]] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                out[child.lineno] = (child.name, qualname)
                visit(child, f"{qualname}.<locals>.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def measure_complexity(root: pathlib.Path = BACKEND, limit: int | None = None) -> dict[str, int]:
    """Every function scoring above ``limit``, keyed ``<file>::<qualname>``.

    Runs ruff ``--isolated`` with only C901 selected and ``# noqa`` switched
    off, so nothing in ruff.toml (excludes, per-file-ignores, extend-* lists,
    ignore lists) and no inline or file-level noqa can hide a function from the
    per-function ceiling. Only the limit and target-version are read from
    ruff.toml. Directories in ``COMPLEXITY_EXEMPT_DIRS`` are excluded from the
    ruff run itself; ruff's default excludes (venv, .venv, node_modules, …)
    still apply.

    The key's qualname comes from the AST (``Class.method``,
    ``outer.<locals>.inner``), so same-named functions each keep their own
    ceiling. Only a genuine redefinition — the same qualname twice in one file —
    is numbered, ``name``, ``name#2``, … in source order. A file ruff cannot
    parse raises instead of silently dropping its functions (which would read as
    "back under the limit" and let ``--shrink`` delete entries).
    """
    config = _ruff_config(root)
    if limit is None:
        limit = int(config["lint"]["mccabe"]["max-complexity"])
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        ".",
        "--isolated",
        "--select",
        "C901",
        "--config",
        f"lint.mccabe.max-complexity={limit}",
        "--ignore-noqa",
        "--no-cache",
        "--exit-zero",
        "--output-format",
        "json",
    ]
    if "target-version" in config:
        cmd += ["--target-version", config["target-version"]]
    for exempt in COMPLEXITY_EXEMPT_DIRS:
        # An absolute path anchors the exclude at root/<dir>, not any <dir>.
        cmd += ["--extend-exclude", str(root.resolve() / exempt.rstrip("/"))]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ruff failed (exit {proc.returncode}): {proc.stderr.strip()}")

    found: list[tuple[str, int, str, int]] = []
    defs: dict[pathlib.Path, dict[int, tuple[str, str]]] = {}
    for item in json.loads(proc.stdout):
        path = pathlib.Path(item["filename"]).resolve()
        rel = path.relative_to(root.resolve()).as_posix()
        if item["code"] != "C901":
            raise RuntimeError(f"cannot measure complexity: {rel}: {item['message']}")
        match = _MESSAGE.match(item["message"])
        if match is None:
            raise RuntimeError(f"unrecognised C901 message: {item['message']!r}")
        row = int(item["location"]["row"])
        if path not in defs:
            defs[path] = _qualnames(path)
        name, qualname = defs[path].get(row, (None, None))
        if name != match["name"]:
            raise RuntimeError(
                f"cannot place {rel}:{row} `{match['name']}` in the AST (found {name!r})"
            )
        found.append((rel, row, qualname, int(match["score"])))

    result: dict[str, int] = {}
    for rel, _row, qualname, score in sorted(found):
        key = base = f"{rel}::{qualname}"
        n = 1
        while key in result:
            n += 1
            key = f"{base}#{n}"
        result[key] = score
    return result


def measure_route_file_lines(
    root: pathlib.Path = BACKEND, limit: int = ROUTE_FILE_MAX_LINES
) -> dict[str, int]:
    """Every ``routes/**/*.py`` file longer than ``limit`` lines."""
    result: dict[str, int] = {}
    for path in sorted((root / "routes").rglob("*.py")):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > limit:
            result[path.relative_to(root).as_posix()] = lines
    return result


def compare(baseline: dict[str, int], current: dict[str, int], limit: int) -> list[str]:
    """Violations: a new entry over ``limit``, or a baselined one that grew."""
    problems = []
    for key, value in sorted(current.items()):
        ceiling = baseline.get(key)
        if ceiling is None:
            problems.append(f"{key}: {value} is over the limit of {limit} (new)")
        elif value > ceiling:
            problems.append(f"{key}: {value} is over its baselined ceiling of {ceiling}")
    return problems


def shrinkable(baseline: dict[str, int], current: dict[str, int]) -> list[str]:
    """Baseline entries that are higher than they need to be."""
    out = []
    for key, ceiling in sorted(baseline.items()):
        value = current.get(key)
        if value is None:
            out.append(f"{key}: back under the limit — delete its entry")
        elif value < ceiling:
            out.append(f"{key}: now {value}, baselined at {ceiling} — lower it")
    return out


def shrink(baseline: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    """Lower each entry to today's value and drop the ones that are gone.

    Never adds a key and never raises a value.
    """
    return {key: min(ceiling, current[key]) for key, ceiling in baseline.items() if key in current}


def load_baseline(root: pathlib.Path = BACKEND) -> dict:
    return json.loads((root / BASELINE_FILE).read_text())


def write_baseline(data: dict, root: pathlib.Path = BACKEND) -> None:
    out = {k: (dict(sorted(v.items())) if isinstance(v, dict) else v) for k, v in data.items()}
    (root / BASELINE_FILE).write_text(json.dumps(out, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--shrink", action="store_true", help="lower the baseline; never raises it")
    parser.add_argument("--root", type=pathlib.Path, default=BACKEND, help="backend directory")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    baseline = load_baseline(root)
    limit = max_complexity(root)
    checks = {
        "complexity": (measure_complexity(root, limit), limit),
        "route_file_lines": (measure_route_file_lines(root), ROUTE_FILE_MAX_LINES),
    }

    if args.shrink:
        for section, (current, _) in checks.items():
            baseline[section] = shrink(baseline[section], current)
        write_baseline(baseline, root)
        print(f"wrote {root / BASELINE_FILE}")
        # --shrink never raises or adds an entry, so growth and new offenders
        # survive it; say so instead of implying the tree is now clean.
        remaining = [
            line
            for section, (current, section_limit) in checks.items()
            for line in compare(baseline[section], current, section_limit)
        ]
        for line in remaining:
            print(f"  FAIL  {line}")
        if remaining:
            print("--shrink cannot fix these: split the code (docs/design/domain-modules.md)")
        return 1 if remaining else 0

    failed = False
    for section, (current, section_limit) in checks.items():
        problems = compare(baseline[section], current, section_limit)
        slack = shrinkable(baseline[section], current)
        print(f"{section}: {len(current)} over the limit of {section_limit}")
        for line in problems:
            print(f"  FAIL  {line}")
        for line in slack:
            print(f"  SHRINK  {line}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
