"""Lint ratchet for the bug-finding ruff rules: ASYNC, bugbear (B), blind except (BLE).

These rules find real bugs (a blocking call inside ``async def``, a ``raise``
that drops its cause, an ``except Exception`` that swallows everything), and
the backend had about 400 violations of them when they were turned on. ruff
can only baseline a rule per FILE: a ``per-file-ignores`` entry switches the
rule off for the whole file, so a NEW blind except in ``graph_service.py``
would pass for as long as the file had an old one. So these rules are not in
ruff.toml at all, and this script counts them instead:

  lint_baseline.json  violation counts keyed ``<file>::<rule>``. A key that is
                      not listed may not have any; a listed one may not grow.

An entry that is now higher than it needs to be only warns; ``--shrink`` lowers
the baseline to today's numbers (see _count_ratchet.py for the shared rule).

ruff runs ``--isolated``, so nothing in ruff.toml (per-file-ignores, excludes,
ignore lists) can hide a violation from its count. An inline ``# noqa: BLE001``
is honoured: that is the way to keep an intentional one in new code, and it
shows up in review on the line it excuses. Fix the violation when you can.

Usage, from backend/:

    python scripts/lint_ratchet.py           # report; exit 1 on a violation
    python scripts/lint_ratchet.py --shrink  # lower the baseline to today's numbers
                                             # (or write it, when there is none yet)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

from _count_ratchet import run

BACKEND = Path(__file__).resolve().parent.parent
BASELINE = BACKEND / "lint_baseline.json"
RULES = ("ASYNC", "B", "BLE")
# B008 (function call in a default argument) flags every FastAPI `Depends()` /
# `File()` / `Body()` parameter, which is the framework's own idiom.
IGNORED = ("B008",)


def measure(root: Path = BACKEND) -> tuple[Counter[str], list[dict]]:
    """Every violation of RULES under ``root``, counted per ``<file>::<rule>``."""
    target = tomllib.loads((BACKEND / "ruff.toml").read_text())["target-version"]
    proc = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check", ".",
            "--isolated", "--no-cache", "--target-version", target,
            "--select", ",".join(RULES), "--ignore", ",".join(IGNORED),
            "--output-format", "json",
        ],
        cwd=root, capture_output=True, text=True,
    )
    # 0 = clean, 1 = violations found; anything else is ruff failing to run.
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit("lint_ratchet: ruff did not run")
    try:
        found = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit("lint_ratchet: ruff did not produce a JSON report") from None
    counts: Counter[str] = Counter()
    for v in found:
        # A file ruff cannot parse reports without a rule code. Counting it
        # under no rule would read as "this file is clean".
        if not v.get("code") or not str(v["code"]).startswith(RULES):
            raise SystemExit(f"lint_ratchet: {v['filename']}: {v.get('message', 'unreadable')}")
        v["rel"] = Path(v["filename"]).resolve().relative_to(root.resolve()).as_posix()
        counts[f"{v['rel']}::{v['code']}"] += 1
    return counts, found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--shrink", action="store_true", help="lower the baseline to today's numbers")
    args = parser.parse_args()

    counts, found = measure()

    def describe(key: str) -> list[str]:
        file, rule = key.split("::")
        return [
            f"{file}:{v['location']['row']}: {v['message']}"
            for v in found
            if v["rel"] == file and v["code"] == rule
        ]

    return run("lint_ratchet", BASELINE, counts, describe, shrink=args.shrink, what="lint violations")


if __name__ == "__main__":
    raise SystemExit(main())
