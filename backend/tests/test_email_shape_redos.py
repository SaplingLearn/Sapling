"""The email checks run on hostile input in linear time (sec2 H1).

``/api/careers/apply`` is public and a Starlette form field can be 1 MB. The
old careers pattern ``^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$`` ran BEFORE the length
check and backtracked quadratically on ``"a@" + "." * N + " "``: 1 MB pinned
the single uvicorn worker for about 50 minutes.
"""
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.email_shape import MAX_EMAIL_LEN, is_email_shape

_ONE_MB = 1_000_000

ADVERSARIAL = [
    "a@" + "." * _ONE_MB + " ",
    "a@" + "a." * (_ONE_MB // 2) + "!",
    "a" * _ONE_MB + "@",
    "a@" + "." * (MAX_EMAIL_LEN - 3) + " ",  # just under the length cap
]


@pytest.mark.parametrize("value", ADVERSARIAL, ids=["dots", "labels", "local", "at-cap"])
def test_adversarial_input_is_rejected_in_under_50ms(value):
    t0 = time.perf_counter()
    assert is_email_shape(value) is False
    assert time.perf_counter() - t0 < 0.05


def test_the_pattern_itself_is_linear_past_the_length_cap():
    # Even with the length guard lifted the pattern must not backtrack.
    value = "a@" + "." * _ONE_MB + " "
    t0 = time.perf_counter()
    assert is_email_shape(value, max_len=10 * _ONE_MB) is False
    assert time.perf_counter() - t0 < 0.05


@pytest.mark.parametrize("value", [
    "ada@example.com", "a.b+c@sub.example.co.uk", "x@y.z",
])
def test_ordinary_addresses_pass(value):
    assert is_email_shape(value)


@pytest.mark.parametrize("value", [
    "", "no-at.example.com", "a@b", "a@b.", "a@.b.c", "a@@b.c", "a b@c.d", "a@b c.d",
    "a@" + "b" * MAX_EMAIL_LEN + ".com",
])
def test_non_addresses_fail(value):
    assert not is_email_shape(value)


def test_extra_forbidden_characters():
    assert is_email_shape("a@b.c", extra_forbidden=',;<>()"')
    assert not is_email_shape("a,b@c.d", extra_forbidden=',;<>()"')
    assert not is_email_shape('a@b".c', extra_forbidden=',;<>()"')


def test_careers_apply_rejects_a_1mb_adversarial_email_fast():
    from main import app

    client = TestClient(app)
    form = {
        "position": "Engineer", "full_name": "Ada",
        "email": "a@" + "." * _ONE_MB + " ", "linkedin_url": "https://linkedin.com/in/a",
    }
    with patch("routes.careers.table") as t:
        t0 = time.perf_counter()
        r = client.post("/api/careers/apply", data=form)
        elapsed = time.perf_counter() - t0
    assert r.status_code == 422
    t.assert_not_called()
    # The whole request (multipart parse included) stays far from the old
    # minutes; the validator alone is pinned at 50 ms above.
    assert elapsed < 2.0


def test_allowlist_bodies_keep_their_shape_rules():
    from pydantic import ValidationError

    from models import AllowlistBulkBody, AllowlistEmailBody

    assert AllowlistEmailBody(email=" Ada@Example.com ").email == "ada@example.com"
    assert AllowlistBulkBody(emails=["a@b.co", "A@B.CO"]).emails == ["a@b.co"]
    for bad in ("a,b@c.d", "a@b", "a@" + "." * 300 + " "):
        with pytest.raises(ValidationError):
            AllowlistEmailBody(email=bad)


def test_email_service_scrub_is_linear():
    from services.email_service import _EMAILISH

    text = "x" * 200_000
    t0 = time.perf_counter()
    assert _EMAILISH.sub("<address>", text) == text
    assert time.perf_counter() - t0 < 0.05
    assert _EMAILISH.sub("<a>", "to bob@example.com, ann@x.y") == "to <a>, <a>"
