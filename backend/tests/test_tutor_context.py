from services.tutor_context import needs_context


def test_short_acknowledgements_skip_context():
    assert not needs_context("Thanks!")
    assert not needs_context("got it")


def test_questions_keep_context():
    assert needs_context("Can you explain the chain rule?")


def test_blank_turn_does_not_request_context():
    assert not needs_context("  ")
