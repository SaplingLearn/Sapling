"""The shared rule of the count ratchets (type_ratchet.py, lint_ratchet.py).

Both keep a JSON baseline of counts keyed ``<file>::<rule>``. A key that is not
listed may not have any; a listed one may not grow. A count that went DOWN only
warns, so two PRs that each fix one cannot leave main red between them, and
``--shrink`` lowers the baseline to today's numbers.

``--shrink`` never raises an entry: it refuses while anything has grown. The
one way to add or raise one is to write the file from scratch (delete it, then
``--shrink``), which shows up in review as a whole-file change.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path


def run(
    name: str,
    baseline_path: Path,
    counts: Counter[str],
    describe: Callable[[str], list[str]],
    *,
    shrink: bool,
    what: str,
) -> int:
    """Compare ``counts`` to the baseline; return the process exit code.

    ``describe(key)`` returns the ``file:line: message`` lines behind one key,
    printed under each entry that grew. ``what`` names the unit ("type errors").
    """
    exists = baseline_path.exists()
    baseline: dict[str, int] = json.loads(baseline_path.read_text()) if exists else {}

    grew = {k: (baseline.get(k, 0), n) for k, n in counts.items() if n > baseline.get(k, 0)}
    shrunk = {k: (n, counts.get(k, 0)) for k, n in baseline.items() if counts.get(k, 0) < n}

    if shrink:
        if grew and exists:
            print(f"{name}: refusing to --shrink while entries have grown; fix those first")
        else:
            new = {k: counts[k] for k in sorted(counts)}
            baseline_path.write_text(json.dumps(new, indent=2) + "\n")
            print(f"{name}: baseline now {sum(new.values())} {what} in {len(new)} entries")
            return 0

    for key, (was, now) in sorted(shrunk.items()):
        print(f"warning: {key} is down to {now} (baseline {was}); run with --shrink")

    if grew:
        print(f"\n{name}: new {what} (fix them; do not raise the baseline):")
        for key, (was, now) in sorted(grew.items()):
            print(f"  {key}: {now} (baseline {was})")
            for line in describe(key):
                print(f"    {line}")
        return 1

    print(f"{name}: OK ({sum(counts.values())} baselined {what}, none new)")
    return 0
