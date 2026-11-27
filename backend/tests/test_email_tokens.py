"""The emails are built from the app's design tokens.

Email clients can't read CSS variables, so services/email_templates.py copies
the values it uses. These tests read frontend/src/styles/tokens.css and fail
when a copy drifts, so a token change reaches the emails too.
"""
import re
from pathlib import Path

import pytest

from services import email_templates as t

TOKENS_CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "styles" / "tokens.css"

pytestmark = pytest.mark.skipif(not TOKENS_CSS.exists(), reason="frontend/ is not checked out")


def _root_tokens() -> dict[str, str]:
    css = TOKENS_CSS.read_text()
    root = css[css.index(":root {"):]
    root = root[: root.index("\n}")]
    root = re.sub(r"/\*.*?\*/", "", root, flags=re.S)
    return {m[1]: m[2].strip() for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*([^;]+);", root)}


def _resolve(name: str, tokens: dict[str, str]) -> str:
    value = tokens[name]
    while (m := re.fullmatch(r"var\(--([a-z0-9-]+)\)", value)):
        value = tokens[m[1]]
    return value


def _on_white(value: str) -> str:
    """A token as the hex it paints on the white email page."""
    m = re.fullmatch(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)", value)
    if not m:
        return value.lower()
    r, g, b, a = int(m[1]), int(m[2]), int(m[3]), float(m[4])
    return "#" + "".join(f"{round(c * a + 255 * (1 - a)):02x}" for c in (r, g, b))


@pytest.mark.parametrize("name", sorted(t.TOKENS))
def test_colour_matches_token(name):
    tokens = _root_tokens()
    assert t.TOKENS[name].lower() == _on_white(_resolve(name, tokens)), f"--{name} changed in tokens.css"


@pytest.mark.parametrize(
    ("const", "token"),
    [("_FS_MD", "fs-md"), ("_FS_LG", "fs-lg"), ("_FS_XL", "fs-xl"), ("_FS_2XL", "fs-2xl"),
     ("_FS_4XL", "fs-4xl"), ("_FS_5XL", "fs-5xl"), ("R_SM", "r-sm"), ("R_LG", "r-lg")],
)
def test_size_matches_token(const, token):
    assert f"{getattr(t, const)}px" == _root_tokens()[token]


def test_every_colour_in_an_email_is_a_token():
    """No hex in the rendered emails but the tokens, white, and the header
    image's own ground."""
    allowed = {v.lower() for v in t.TOKENS.values()} | {"#ffffff", "#f2f4f0"}
    _, html, _ = t.waitlist_approved("Sam", signin_url="https://x.test", unsubscribe_url="https://x.test/u")
    _, html2, _ = t.ops_alert("Spend", [("a", "b"), ("c", "d")], dashboard_url="https://x.test", unsubscribe_url="https://x.test/u")
    found = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}\b", html + html2)}
    assert found <= allowed, f"not a token: {sorted(found - allowed)}"
