"""Migration filename convention: timestamps for new migrations (#507 fallout).

Sequential NNNN_ prefixes are claimed when a branch is WRITTEN but only
validated when it MERGES, so two branches open at once routinely claim the same
number. One branch hit this twice in a single lifetime — first against main's
0042, then against an unpushed branch holding 0043/0044.

A UTC timestamp prefix removes the shared counter: two branches would have to
be created in the same second to collide.

WHY THE EXISTING FILES ARE NOT RENAMED
--------------------------------------
`schema_migrations.filename` is the PRIMARY KEY of the ledger, and
`pending_migrations` treats any basename not in that table as unapplied.
Renaming an applied migration therefore makes the runner apply it AGAIN. That
is not theoretical: `0021_gradebook.sql` DROPs and re-CREATEs the assignments
table, so a rename would destroy the gradebook on any environment that already
ran it.

So the legacy files are frozen exactly as they are, forever, and the convention
changes only for new migrations. Ordering still holds: "0" (0x30) sorts before
"2" (0x32), so every NNNN_ file applies before every timestamped one, which is
the correct order since the legacy ones came first.
"""
import re
from pathlib import Path

from db.migrate import discover_migrations, is_valid_migration_name

MIGRATIONS_DIR = Path("db/migrations")

# The complete set of sequentially-numbered migrations, frozen at the moment the
# convention changed. Nothing may be added to this list: a new NNNN_ file is
# exactly the mistake this convention exists to prevent, and the guard test
# below fails if one appears.
_LEGACY_NUMERIC_COUNT = 45


def _names() -> list[str]:
    return [p.name for p in discover_migrations(MIGRATIONS_DIR)]


class TestNameValidation:
    def test_accepts_a_utc_timestamp_prefix(self):
        """The new convention: YYYYMMDDHHMMSS_description.sql."""
        assert is_valid_migration_name("20260731224500_documents_file_sha256.sql")

    def test_still_accepts_the_legacy_four_digit_prefix(self):
        """The 45 existing files keep their names permanently — renaming an
        applied migration would re-run it against the ledger."""
        assert is_valid_migration_name("0021_gradebook.sql")

    def test_rejects_a_name_with_no_sortable_prefix(self):
        """Without a numeric prefix the file sorts unpredictably among its
        siblings, so apply order becomes whatever the alphabet says."""
        assert not is_valid_migration_name("add_widgets.sql")

    def test_rejects_a_prefix_that_is_neither_four_nor_fourteen_digits(self):
        """A 6- or 8-digit prefix would sort between the two schemes and break
        the guarantee that all legacy files apply first."""
        assert not is_valid_migration_name("202607_widgets.sql")
        assert not is_valid_migration_name("20260731_widgets.sql")


class TestOrderingGuarantee:
    def test_a_timestamped_migration_sorts_after_every_legacy_one(self):
        """The whole scheme rests on this. If it were false, a new migration
        could apply BEFORE the schema it depends on."""
        legacy = [n for n in _names() if re.match(r"^\d{4}_", n)]
        newest_legacy = max(legacy)

        assert "20260101000000_anything.sql" > newest_legacy

    def test_the_ordering_rests_on_the_leading_digit_not_on_length(self):
        """The guarantee is narrower than "timestamps sort last", and pinning
        the real reason keeps the docs honest.

        Comparison is character-by-character, so LENGTH does not decide it:
        a year-1000 timestamp would sort BEFORE a 9999_ prefix, since
        '1' < '9'. What actually holds is that every legacy file starts with
        '0' and every timestamp this millennium starts with '2'.
        """
        legacy = [n for n in _names() if re.match(r"^\d{4}_", n)]

        assert all(n.startswith("0") for n in legacy)
        # A sequential migration numbered 3000+ would break this, which is
        # another reason the legacy set is frozen.
        assert "20260731224500_x.sql" > max(legacy)
        assert "10000101000000_x.sql" < "9999_x.sql"  # the counter-example


class TestNoNewSequentialMigrations:
    """Guard, not a new behaviour: pins today's state so the NEXT sequentially
    numbered migration fails CI instead of colliding at merge time."""

    def test_every_migration_matches_one_of_the_two_conventions(self):
        bad = [n for n in _names() if not is_valid_migration_name(n)]
        assert bad == [], f"migrations with an invalid prefix: {bad}"

    def test_no_sequential_migration_has_been_added_since_the_cutover(self):
        legacy = [n for n in _names() if re.match(r"^\d{4}_", n)]
        assert len(legacy) == _LEGACY_NUMERIC_COUNT, (
            f"expected {_LEGACY_NUMERIC_COUNT} legacy NNNN_ migrations, found "
            f"{len(legacy)}. New migrations must use a UTC timestamp prefix "
            "(YYYYMMDDHHMMSS_description.sql) — see this module's docstring."
        )
