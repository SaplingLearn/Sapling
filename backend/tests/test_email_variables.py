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


# ── Link variables: buttons and labelled links ──────────────────────────────

def _render(body, values=None):
    from services import email_templates
    return email_templates.broadcast("Hi", body, unsubscribe_url="https://u.example", values=values or {})


def test_link_alone_on_its_line_is_a_button(monkeypatch):
    import config
    monkeypatch.setattr(config, "FRONTEND_URL", "https://sapling.example")
    _, html, text = _render("Ready when you are.\n\n{{app_link}}\n\nSee you there.")
    assert '<a href="https://sapling.example/dashboard"' in html
    assert ">Open Sapling</a></td></tr></table>" in html          # a button table
    assert "https://sapling.example/dashboard" in text and "Open Sapling" not in text


def test_link_button_takes_a_custom_label(monkeypatch):
    import config
    monkeypatch.setattr(config, "FRONTEND_URL", "https://sapling.example")
    _, html, text = _render("{{signin_link|Join the beta}}")
    assert '<a href="https://sapling.example"' in html and ">Join the beta</a></td>" in html
    assert "Join the beta: https://sapling.example" in text


def test_link_inside_a_sentence_is_a_labelled_link(monkeypatch):
    import config
    monkeypatch.setattr(config, "FRONTEND_URL", "https://sapling.example")
    _, html, _ = _render("You can {{app_link|open your dashboard}} any time.")
    assert ('You can <a href="https://sapling.example/dashboard" target="_blank" '
            'style="color:#445D22;text-decoration:underline;font-weight:600;">open your dashboard</a> any time.') in html


def test_link_label_is_escaped():
    _, html, _ = _render("{{app_link|<b>go</b>}}")
    assert "<b>go</b>" not in html and "&lt;b&gt;go&lt;/b&gt;" in html


def test_a_smuggled_link_token_is_dropped():
    _, html, _ = _render("before \x00L7\x00 after")
    assert "before L7 after" in html


def test_link_in_the_subject_is_its_url(monkeypatch):
    import config
    from services import email_templates
    monkeypatch.setattr(config, "FRONTEND_URL", "https://sapling.example")
    subject, _, _ = email_templates.broadcast("Go: {{signin_link}}", "x", unsubscribe_url="https://u.example")
    assert subject == "Go: https://sapling.example"
