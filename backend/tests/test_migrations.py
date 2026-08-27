"""Migration ledger + apply-order pins (#398).

The runner applies migrations in `sorted(glob("*.sql"))` order — pure
lexicographic by filename (`db/migrate.py::discover_migrations`). Three prefixes
carry TWO files each (0019 / 0020 / 0021), so the numeric prefix alone does not
determine order — the suffix does, and a rename could silently flip it.

The 0021 pair is load-bearing: `0021_gradebook.sql` DROPs and re-CREATEs the
enrollment-keyed `assignments` table, and `0021_gradebook_curve.sql` then ALTERs
it to add the `curve_*` columns. So gradebook MUST apply before gradebook_curve —
otherwise the curve columns are added to the old table and then dropped when
gradebook recreates it, and `routes/gradebook.py` reads columns that don't exist.

These order pins are pure filename logic (no database) so they gate in the
default lane. The ledger-consistency check needs the real local stack and is
marked `integration`.

NOTE (issue #398 comment, corrected): the comment states the 0021 pair "sorts
gradebook_curve BEFORE gradebook under filesystem sort, which is the opposite of
the numeric intent." That is not what the runner does. `sorted()` compares
`"0021_gradebook.sql"` vs `"0021_gradebook_curve.sql"` and, because `.` (0x2E) <
`_` (0x5F), applies **gradebook first** — which is exactly the required
dependency order. `test_gradebook_applies_before_curve` pins that.
"""
import re
from pathlib import Path

from db.migrate import discover_migrations

MIGRATIONS_DIR = "db/migrations"

# Duplicate-prefix pairs and the order the runner MUST keep (first, then second).
_PINNED_PAIRS = [
    ("0019_conventions_terms_schools.sql", "0019_gradebook_drops.sql"),
    ("0020_academics_split.sql", "0020_gradescope.sql"),
    ("0021_gradebook.sql", "0021_gradebook_curve.sql"),
]


def _order() -> list[str]:
    return [p.name for p in discover_migrations(Path(MIGRATIONS_DIR))]


# ── Offline: apply-order pins (pure filename logic) ─────────────────────────


def test_every_migration_has_a_four_digit_numeric_prefix():
    """A file without the NNNN_ prefix sorts unpredictably and breaks ordering."""
    bad = [n for n in _order() if not re.match(r"^\d{4}_.*\.sql$", n)]
    assert bad == [], f"migrations without a NNNN_ prefix: {bad}"


def test_migration_filenames_are_unique():
    """The runner keys the ledger on basename; a duplicate basename would make
    one migration silently shadow another."""
    names = _order()
    assert len(names) == len(set(names))


def test_duplicate_prefix_pairs_apply_in_pinned_order():
    """The three NNNN pairs must apply in the pinned order — a rename that flips
    the lexicographic suffix would reorder them silently, so pin it."""
    order = _order()
    for first, second in _PINNED_PAIRS:
        assert first in order and second in order, f"missing {first!r}/{second!r}"
        assert order.index(first) < order.index(second), (
            f"{first} must apply before {second}, got "
            f"{order.index(first)} vs {order.index(second)}"
        )


def test_gradebook_applies_before_curve():
    """Load-bearing: 0021_gradebook CREATEs `assignments`; 0021_gradebook_curve
    ALTERs it. Reversed, the curve columns would be dropped on recreate. This is
    the pin that contradicts the #398 comment's 'curve before gradebook' claim."""
    order = _order()
    assert order.index("0021_gradebook.sql") < order.index("0021_gradebook_curve.sql")


def test_discover_is_sorted_lexicographically():
    """Pin the runner's contract: apply order == sorted(filenames). If the runner
    ever switches to numeric-aware or ctime sorting, these pins must be revisited."""
    order = _order()
    assert order == sorted(order)


# ── Offline: schema CHECK vs. what route code actually writes ───────────────
#
# The mock Supabase in conftest.py enforces no CHECK constraints, so a route that
# writes a value its column forbids passes every unit test and fails only against
# a real database. That is exactly how the Gradescope sync shipped broken:
# 0021_gradebook tightened `assignments.source` to ('manual','syllabus') while
# routes/gradescope.py was writing 'gradescope', so every synced row was rejected
# and the endpoint still returned HTTP 200. These pins are static (no DB), so they
# gate in the default lane alongside the order pins above.

_SOURCE_CHECK_RE = re.compile(r"CHECK\s*\(\s*source\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
_SOURCE_WRITE_RE = re.compile(r"""["']source["']\s*:\s*["']([a-z_]+)["']""")


def _allowed_source_values() -> set[str]:
    """The effective assignments.source CHECK — the LAST definition in apply order
    wins, since a later migration drops and re-adds the constraint."""
    allowed: set[str] = set()
    for path in discover_migrations(Path(MIGRATIONS_DIR)):
        for match in _SOURCE_CHECK_RE.finditer(path.read_text(encoding="utf-8")):
            allowed = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    return allowed


def test_assignments_source_check_covers_every_value_routes_write():
    """Every `"source": "..."` literal in routes/ must be permitted by the
    effective CHECK. Catches the class of bug the mock DB cannot: a constraint
    tightened in a migration without updating (or noticing) an existing writer."""
    allowed = _allowed_source_values()
    assert allowed, "no assignments.source CHECK found in migrations"

    written: dict[str, set[str]] = {}
    for path in sorted(Path("routes").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for value in _SOURCE_WRITE_RE.findall(text):
            written.setdefault(value, set()).add(path.name)

    violations = {v: sorted(f) for v, f in written.items() if v not in allowed}
    assert violations == {}, (
        f"routes write assignments.source values the CHECK forbids: {violations}. "
        f"Allowed: {sorted(allowed)}"
    )


def test_gradescope_is_an_allowed_source_value():
    """Pin the 0032 widening directly: routes/gradescope.py::sync_course depends
    on it for both its insert and its update path."""
    assert "gradescope" in _allowed_source_values()


# The DB-backed counterpart — that the schema_migrations ledger records every
# file on disk — needs the real stack and lives in the integration lane
# (tests/integration/test_migrations_ledger.py).
