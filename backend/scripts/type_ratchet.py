"""Type-check ratchet: pyright (basic mode) over the backend app packages.

The backend had no type checker, and pyright finds a few hundred errors in it
today. Most are noise from untyped libraries and mixins, but some are real
(a return annotation that disagrees with what the function returns, an
Optional used without a check). Fixing them all at once would collide with
every open PR, so this works like the ruff and code-size ratchets:

  type_baseline.json  error counts keyed ``<file>::<rule>``. A key that is not
                      listed may not have errors; a listed one may not grow.

An entry that is now higher than it needs to be only warns, so two PRs that
each fix an error cannot leave main red between them; ``--shrink`` lowers the
baseline to today's numbers (the rule is shared with lint_ratchet.py, in
_count_ratchet.py). Missing-import errors are off in
pyrightconfig.json because CI installs the lockfile without the heavy OCR
stack; run this against that same environment (``pip install -r
requirements.lock``) so the counts match CI.

pyright itself is an npm package. Its version is pinned in
scripts/pyright/package.json and installed with ``npm ci`` from the
package-lock.json beside it, so the download is checked against a recorded
sha512 the way requirements.lock checks every pip package. The first run
installs it (needs node and npm); to move to a new pyright, change the version
there, run ``npm install --package-lock-only`` in that directory, and commit
both files with the re-measured baseline.

Usage, from backend/:

    python scripts/type_ratchet.py           # report; exit 1 on a violation
    python scripts/type_ratchet.py --shrink  # lower the baseline to today's numbers
                                             # (or write it, when there is none yet)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from _count_ratchet import run

BACKEND = Path(__file__).resolve().parent.parent
BASELINE = BACKEND / "type_baseline.json"
# pyright's pinned version and its integrity hash live here (package.json and
# package-lock.json), so a pyright release cannot turn main red on its own and
# a tampered download fails the install.
PYRIGHT_DIR = BACKEND / "scripts" / "pyright"


def _pyright() -> str:
    """Path to the locked pyright, installing it with ``npm ci`` when it is
    missing or is not the version package.json pins."""
    wanted = json.loads((PYRIGHT_DIR / "package.json").read_text())["dependencies"]["pyright"]
    installed = PYRIGHT_DIR / "node_modules" / "pyright" / "package.json"
    if not installed.exists() or json.loads(installed.read_text())["version"] != wanted:
        # `npm ci` installs exactly what package-lock.json records and fails on
        # an integrity mismatch. --ignore-scripts: nothing here needs one.
        done = subprocess.run(
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=PYRIGHT_DIR, capture_output=True, text=True,
        )
        if done.returncode != 0:
            sys.stderr.write(done.stdout + done.stderr)
            raise SystemExit("type_ratchet: could not install the locked pyright (needs node and npm)")
    return str(PYRIGHT_DIR / "node_modules" / ".bin" / "pyright")


def measure() -> tuple[Counter[str], list[dict]]:
    proc = subprocess.run(
        [_pyright(), "--outputjson", "-p", str(BACKEND / "pyrightconfig.json")],
        cwd=BACKEND, capture_output=True, text=True,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit("type_ratchet: pyright did not produce a JSON report") from None
    errors = [d for d in report["generalDiagnostics"] if d["severity"] == "error"]
    counts: Counter[str] = Counter()
    for d in errors:
        rel = Path(d["file"]).resolve().relative_to(BACKEND).as_posix()
        counts[f"{rel}::{d.get('rule', 'error')}"] += 1
    return counts, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--shrink", action="store_true", help="lower the baseline to today's numbers")
    args = parser.parse_args()

    counts, errors = measure()

    def describe(key: str) -> list[str]:
        file, rule = key.split("::")
        lines = []
        for d in errors:
            rel = Path(d["file"]).resolve().relative_to(BACKEND).as_posix()
            if rel == file and d.get("rule", "error") == rule:
                line = d["range"]["start"]["line"] + 1
                lines.append(f"{file}:{line}: {d['message'].splitlines()[0]}")
        return lines

    return run("type_ratchet", BASELINE, counts, describe, shrink=args.shrink, what="type errors")


if __name__ == "__main__":
    raise SystemExit(main())
