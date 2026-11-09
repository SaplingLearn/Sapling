"""The varied-practice review migrations take their locks briefly (spec §13
A141; the second review). 20261108205812 runs in one transaction and holds
ACCESS EXCLUSIVE on check_items and node_mastery_events to its commit, so it
fails fast on a lock it cannot get (lock_timeout) and scans nothing under them
(its CHECK is NOT VALID); 20261108224511 validates the CHECK in its own
transaction, which blocks no read or write. The real-database half is
tests/integration/test_varied_practice_db.py."""

from __future__ import annotations

import pathlib
import re

MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
REVIEW = MIGRATIONS / "20261108205812_learning_varied_practice_review.sql"
VALIDATE = MIGRATIONS / "20261108224511_learning_varied_practice_validate.sql"
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s';"


def _statements(path: pathlib.Path) -> list[str]:
    """The file's top-level statements, SQL line comments removed (a function
    body's own semicolons stay inside its dollar quotes)."""
    text = "\n".join(line.split("--", 1)[0] for line in path.read_text().splitlines())
    out, current, quoted = [], "", False
    for part in re.split(r"(\$\$|;)", text):
        if part == "$$":
            quoted = not quoted
            current += part
        elif part == ";" and not quoted:
            if current.strip():
                out.append(" ".join(current.split()))
            current = ""
        else:
            current += part
    if current.strip():
        out.append(" ".join(current.split()))
    return out


def test_the_review_migration_fails_fast_on_a_lock_and_scans_nothing_under_one():
    statements = _statements(REVIEW)
    assert statements[0] + ";" == LOCK_TIMEOUT  # before the first lock it takes
    (add,) = [s for s in statements if "ADD CONSTRAINT check_items_multi_concept_shape" in s]
    assert add.endswith("NOT VALID")
    assert not [s for s in statements if "VALIDATE CONSTRAINT" in s]  # never under its locks


def test_the_check_is_validated_later_in_its_own_transaction():
    assert VALIDATE.name > REVIEW.name  # db/migrate.py: one file, one transaction, in name order
    assert [s + ";" for s in _statements(VALIDATE)] == [
        LOCK_TIMEOUT,
        "ALTER TABLE public.check_items VALIDATE CONSTRAINT check_items_multi_concept_shape;",
    ]
