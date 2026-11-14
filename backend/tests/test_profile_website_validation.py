"""Profile ``website`` is rendered as an ``href`` on the public profile for
every viewer, so UpdateProfileBody accepts only an http(s) URL (a bare host
is stored as https), length-capped; anything else is a 422.
"""

import pytest
from pydantic import ValidationError

from models import PROFILE_WEBSITE_MAX, UpdateProfileBody


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("https://example.com/me", "https://example.com/me"),
        ("http://example.com", "http://example.com"),
        ("  https://example.com  ", "https://example.com"),
        ("HTTPS://Example.com/x?y=1#z", "HTTPS://Example.com/x?y=1#z"),
        ("example.com", "https://example.com"),
        ("sub.example.co.uk/path", "https://sub.example.co.uk/path"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_website_accepts_http_urls(given, stored):
    assert UpdateProfileBody(website=given).website == stored


def test_website_omitted_stays_none():
    assert UpdateProfileBody().website is None


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        " javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "ftp://example.com",
        "//evil.example/path",
        "/relative/path",
        "https://",
        "https:///nohost",
        "https://user:pass@example.com",
        "https://exa mple.com",
        "https://example.com/\x00",
        "not a url",
        "https://example.com/" + "a" * PROFILE_WEBSITE_MAX,
    ],
)
def test_website_rejects_everything_else(bad):
    with pytest.raises(ValidationError):
        UpdateProfileBody(website=bad)

