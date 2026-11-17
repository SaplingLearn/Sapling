"""sec2 M11(b): the model-side crisis backstop.

Every free-chat agent (the tutor's three modes, the note chat) carries
`crisis_support_copy.MODEL_SAFETY_PROMPT` in its system prompt whatever the
`crisis_support` flag says: it covers what the phrase screen misses and the
time the flag is off. Its resources come from the card's own strings, so the
two can never disagree.
"""

from __future__ import annotations

import pytest

from services import crisis_support_copy as copy
from services.crisis_support_copy import MODEL_SAFETY_PROMPT


def test_the_backstop_names_every_resource_from_the_card_copy():
    for needle in ("988", "Text HOME to 741741", "911", "counseling",
                   copy.LIFELINE_988.name, copy.CRISIS_TEXT_LINE.name):
        assert needle in MODEL_SAFETY_PROMPT
    assert "stop tutoring" in MODEL_SAFETY_PROMPT
    assert "not a crisis service" in MODEL_SAFETY_PROMPT


def test_the_copy_is_still_pending_review():
    """Adding the backstop does not approve the copy; the flag stays off."""
    assert copy.REVIEW_STATUS == "pending_owner_review"


@pytest.mark.parametrize("mode", ["socratic", "expository", "teachback"])
def test_every_tutor_mode_carries_it(mode):
    from agents import chat_tutor

    prompt = {
        "socratic": chat_tutor._SOCRATIC_PROMPT,
        "expository": chat_tutor._EXPOSITORY_PROMPT,
        "teachback": chat_tutor._TEACHBACK_PROMPT,
    }[mode]
    assert MODEL_SAFETY_PROMPT in prompt


def test_the_note_chat_carries_it():
    from agents.note_chat import _PROMPT

    assert MODEL_SAFETY_PROMPT in _PROMPT


def test_it_does_not_depend_on_the_flag(monkeypatch):
    """The prompts are built at import from constants; no flag is read."""
    monkeypatch.setenv("SAPLING_FLAG_CRISIS_SUPPORT", "off")
    from agents import chat_tutor

    assert MODEL_SAFETY_PROMPT in chat_tutor._SHARED_PREAMBLE
