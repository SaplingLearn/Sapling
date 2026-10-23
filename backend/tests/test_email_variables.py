"""Broadcast personalization variables: {{key}} and {{key|fallback}}."""
import pytest

from services.email_variables import VARIABLES, fill, unknown_variables, unknown_variables_message


def test_fills_known_values():
    assert fill("Hi {{first_name}}, you are {{ email }}", {"first_name": "Ada", "email": "a@bu.edu"}) == (
        "Hi Ada, you are a@bu.edu"
    )


@pytest.mark.parametrize("values", [{}, {"first_name": ""}, {"first_name": "   "}, {"first_name": None}])
def test_missing_value_uses_the_builtin_fallback(values):
    assert fill("Hi {{first_name}},", values) == "Hi there,"


def test_admin_fallback_wins_over_the_builtin_one():
    assert fill("Hi {{first_name|friend}}!", {}) == "Hi friend!"
    assert fill("Hi {{ first_name | dear student }}!", {}) == "Hi dear student!"
    assert fill("Hi {{first_name|friend}}!", {"first_name": "Ada"}) == "Hi Ada!"


def test_value_whitespace_is_collapsed():
    assert fill("{{name}}", {"name": " Ada \n Lovelace "}) == "Ada Lovelace"


def test_unknown_and_malformed_are_left_alone():
    assert fill("{{frist_name}} {{}} {{ 1x }} {single}", {"first_name": "Ada"}) == "{{frist_name}} {{}} {{ 1x }} {single}"


def test_unknown_variables_lists_each_once_in_order():
    assert unknown_variables("{{b}} {{first_name}} {{a}}", "{{b}} {{c|x}}") == ["b", "a", "c"]
    assert unknown_variables("Hi {{first_name}} {{email|none}}") == []


def test_message_names_the_typos_and_the_options():
    msg = unknown_variables_message(["frist_name"])
    assert msg.startswith("Unknown variable {{frist_name}}.")
    for v in VARIABLES:
        assert "{{" + v["key"] + "}}" in msg
    assert unknown_variables_message(["a", "b"]).startswith("Unknown variables {{a}}, {{b}}.")
