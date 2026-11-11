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
baseline to today's numbers. Missing-import errors are off in
pyrightconfig.json because CI installs the lockfile without the heavy OCR
stack; run this against that same environment (``pip install -r
requirements.lock``) so the counts match CI.

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

BACKEND = Path(__file__).resolve().parent.parent
BASELINE = BACKEND / "type_baseline.json"
# Pinned so a pyright release cannot turn main red on its own.
PYRIGHT = "pyright@1.1.414"


def measure() -> tuple[Counter[str], list[dict]]:
    proc = subprocess.run(
        ["npx", "--yes", PYRIGHT, "--outputjson", "-p", str(BACKEND / "pyrightconfig.json")],
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
    baseline: dict[str, int] = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}

    grew = {k: (baseline.get(k, 0), n) for k, n in counts.items() if n > baseline.get(k, 0)}
    shrunk = {k: (n, counts.get(k, 0)) for k, n in baseline.items() if counts.get(k, 0) < n}

    if args.shrink:
        if grew and BASELINE.exists():
            print("type_ratchet: refusing to --shrink while entries have grown; fix those first")
        else:
            new = {k: counts[k] for k in sorted(counts)}
            BASELINE.write_text(json.dumps(new, indent=2) + "\n")
            print(f"type_ratchet: baseline now {sum(new.values())} errors in {len(new)} entries")
            return 0

    for key, (was, now) in sorted(shrunk.items()):
        print(f"warning: {key} is down to {now} (baseline {was}); run with --shrink")

    if grew:
        print("\ntype_ratchet: new type errors (fix them; do not raise the baseline):")
        for key, (was, now) in sorted(grew.items()):
            print(f"  {key}: {now} (baseline {was})")
            file, rule = key.split("::")
            for d in errors:
                rel = Path(d["file"]).resolve().relative_to(BACKEND).as_posix()
                if rel == file and d.get("rule", "error") == rule:
                    line = d["range"]["start"]["line"] + 1
                    msg = d["message"].splitlines()[0]
                    print(f"    {file}:{line}: {msg}")
        return 1

    print(f"type_ratchet: OK ({sum(counts.values())} baselined errors, none new)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
