"""The varied-practice migrations' deploy order and the journal flag, as the
docs state them (spec §13 A140, A141; the second review): every
varied-practice migration is in the operations guide's and the readiness
record's wave-4 order, and the data model and the Evidence field say the
journal records a multi-concept answer."""

from __future__ import annotations

import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
MIGRATIONS = sorted(p.name for p in (BACKEND / "db" / "migrations").glob("*_learning_varied_practice*.sql"))


def _wave4(text: str, heading: str) -> str:
    start = text.index(heading)
    return text[start : text.index("\n#", start + len(heading))]


def test_every_varied_practice_migration_is_in_both_deploy_orders():
    assert MIGRATIONS == [
        "20261108185101_learning_varied_practice.sql",
        "20261108205812_learning_varied_practice_review.sql",
        "20261108224511_learning_varied_practice_validate.sql",
    ]
    operations = (REPO / "docs" / "learning-loop" / "operations.md").read_text()
    readiness = (REPO / "docs" / "operations" / "learning-engineering-readiness.md").read_text()
    guide = operations[operations.index("- **Wave 4**") :]
    record = _wave4(readiness, "### Learning-loop wave-4 rollout ordering")
    for name in MIGRATIONS:
        assert name in guide, name
        assert name in record, name
    # the review migration lands before the code (the stats read selects its column)
    assert "**before** the code" in guide.split(MIGRATIONS[1], 1)[1].split("`backend/db", 1)[0]


def test_the_data_model_and_the_field_say_the_journal_records_a_combination():
    model = (REPO / "docs" / "learning-loop" / "data-model.md").read_text()
    key_columns = model[model.index("- **Key columns:**") : model.index("- **Ids**")]
    assert "`multi_concept`" in key_columns
    assert "adds no column" not in model
    evidence = (BACKEND / "learning" / "evidence.py").read_text()
    field = evidence[: evidence.index("multi_concept: bool = False")]
    comment = field[field.rindex("same_session_recheck: bool = False") :]
    assert "node_mastery_events.multi_concept" in comment
    assert "No column journals it" not in evidence
