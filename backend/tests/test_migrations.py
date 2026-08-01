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
from pathlib import Path

from db.migrate import discover_migrations, is_valid_migration_name

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


def test_every_migration_has_a_sortable_numeric_prefix():
    """A file without a fixed-width numeric prefix sorts unpredictably and
    breaks apply order.

    Two shapes are accepted: the frozen legacy `NNNN_` files, and the
    `YYYYMMDDHHMMSS_` timestamps used for every new migration. See
    `tests/test_migration_naming.py` for why the legacy names can never be
    converted, and `db.migrate.is_valid_migration_name` for the rule itself.
    """
    bad = [n for n in _order() if not is_valid_migration_name(n)]
    assert bad == [], f"migrations with an unsortable prefix: {bad}"


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


def test_section_not_null_applies_before_the_null_section_index():
    """Load-bearing ordering for the recovered 0033.

    0033_offering_section_not_null collapses NULL sections into '', which makes
    0036's `WHERE section IS NULL` partial index match nothing. That is the
    intended end state — a later timestamped migration drops the dead index —
    but only in this order. Reversed, 0036 would build a real index over live
    NULL rows and 0033's backfill would then silently empty it, leaving an index
    that looks load-bearing and enforces nothing.
    """
    order = _order()
    assert order.index("0033_offering_section_not_null.sql") < order.index(
        "0036_offering_null_section_unique.sql"
    )


def test_the_dead_null_section_index_is_dropped_after_it_is_created():
    """The drop must land after 0036, or it drops nothing and the index
    survives. Timestamp prefixes sort after every legacy NNNN_ file, so this
    holds structurally — pinned because it is easy to break by renaming."""
    order = _order()
    assert order.index("0036_offering_null_section_unique.sql") < order.index(
        "20260801062439_drop_dead_null_section_index.sql"
    )


def test_summer_retirement_applies_after_the_terms_are_seeded():
    """0032_retire_summer_2026 deletes a term row that 0019 seeds. Reversed, the
    DELETE matches nothing and 0019 then re-creates summer-2026, silently
    undoing the retirement."""
    order = _order()
    assert order.index("0019_conventions_terms_schools.sql") < order.index(
        "0032_retire_summer_2026.sql"
    )


def test_discover_is_sorted_lexicographically():
    """Pin the runner's contract: apply order == sorted(filenames). If the runner
    ever switches to numeric-aware or ctime sorting, these pins must be revisited."""
    order = _order()
    assert order == sorted(order)


# The DB-backed counterpart — that the schema_migrations ledger records every
# file on disk — needs the real stack and lives in the integration lane
# (tests/integration/test_migrations_ledger.py).
