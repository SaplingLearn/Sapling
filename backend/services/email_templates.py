"""Email bodies. Pure functions returning `(subject, html, text)`.

The HTML is deliberately old-fashioned — a single centred table, inline styles,
no web fonts, no images — because that is what renders the same in Gmail,
Outlook and Apple Mail. Every template carries the recipient's one-click
unsubscribe link in its footer (the same URL rides the List-Unsubscribe header).

Nothing here interpolates unescaped input. Broadcast bodies are admin-written
PLAIN TEXT: they are HTML-escaped, blank-line paragraphs become <p>, and bare
http(s) URLs become links. Raw admin HTML is never injected.
"""

from __future__ import annotations

import re
from html import escape

BRAND = "#445D22"
_TEXT = "#24301a"
_MUTED = "#6b7262"
_BG = "#f5f3ec"
_CARD = "#ffffff"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?)]}'\""


def _e(value: str) -> str:
    return escape(value or "", quote=True)


def _button(href: str, label: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:24px 0 8px 0;"><tr>'
        f'<td style="border-radius:8px;background:{BRAND};">'
        f'<a href="{_e(href)}" target="_blank" '
        f'style="display:inline-block;padding:12px 22px;font-family:{_FONT};'
        'font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;'
        f'border-radius:8px;">{_e(label)}</a>'
        "</td></tr></table>"
    )


def _p(inner_html: str) -> str:
    return (
        f'<p style="margin:0 0 14px 0;font-family:{_FONT};font-size:15px;'
        f'line-height:1.6;color:{_TEXT};">{inner_html}</p>'
    )


def _layout(*, preheader: str, heading: str, body_html: str, unsubscribe_url: str) -> str:
    """The shared shell. `body_html` must already be safe HTML."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_e(heading)}</title>
</head>
<body style="margin:0;padding:0;background:{_BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_e(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{_BG};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
<tr><td style="padding:0 4px 16px 4px;font-family:{_FONT};font-size:20px;font-weight:700;color:{BRAND};letter-spacing:-0.2px;">Sapling</td></tr>
<tr><td style="background:{_CARD};border-radius:12px;padding:32px 28px;border-top:4px solid {BRAND};">
<h1 style="margin:0 0 16px 0;font-family:{_FONT};font-size:22px;line-height:1.3;color:{_TEXT};">{_e(heading)}</h1>
{body_html}
</td></tr>
<tr><td style="padding:20px 4px 0 4px;font-family:{_FONT};font-size:12px;line-height:1.6;color:{_MUTED};">
You're receiving this because you signed up for Sapling.
<a href="{_e(unsubscribe_url)}" style="color:{_MUTED};text-decoration:underline;">Unsubscribe</a>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def _text_footer(unsubscribe_url: str) -> str:
    return (
        "\n\n--\nYou're receiving this because you signed up for Sapling.\n"
        f"Unsubscribe: {unsubscribe_url}\n"
    )


# ── Transactional ───────────────────────────────────────────────────────────


def waitlist_confirmation(*, unsubscribe_url: str) -> tuple[str, str, str]:
    subject = "You're on the Sapling waitlist"
    heading = "You're on the list"
    lines = [
        "Thanks for signing up for Sapling. We're letting students in a few at a time "
        "so we can make it great for every one of them.",
        "We'll email you as soon as your spot opens up. Nothing else to do until then.",
    ]
    html = _layout(
        preheader="We'll email you when your spot opens up.",
        heading=heading,
        body_html="".join(_p(_e(line)) for line in lines) + _p(_e("See you soon,") + "<br>" + _e("The Sapling team")),
        unsubscribe_url=unsubscribe_url,
    )
    text = "\n\n".join([heading, *lines, "See you soon,\nThe Sapling team"]) + _text_footer(unsubscribe_url)
    return subject, html, text


def waitlist_approved(*, signin_url: str, unsubscribe_url: str) -> tuple[str, str, str]:
    subject = "You're in: welcome to Sapling"
    heading = "Your spot is ready"
    lines = [
        "Good news: you're off the waitlist. Your Sapling account is ready whenever you are.",
        "Sign in with your school Google account to upload your course materials, "
        "study with your AI tutor and watch your knowledge tree grow.",
    ]
    html = _layout(
        preheader="You're off the waitlist. Sign in to get started.",
        heading=heading,
        body_html=(
            "".join(_p(_e(line)) for line in lines)
            + _button(signin_url, "Sign in to Sapling")
            + _p(_e("Happy studying,") + "<br>" + _e("The Sapling team"))
        ),
        unsubscribe_url=unsubscribe_url,
    )
    text = "\n\n".join([
        heading, *lines, f"Sign in: {signin_url}", "Happy studying,\nThe Sapling team",
    ]) + _text_footer(unsubscribe_url)
    return subject, html, text


def welcome(first_name: str | None, *, app_url: str, unsubscribe_url: str) -> tuple[str, str, str]:
    name = (first_name or "").strip()
    subject = "Welcome to Sapling"
    heading = f"Welcome, {name}!" if name else "Welcome to Sapling!"
    lines = [
        "We're glad you're here. A few ways to get going:",
    ]
    tips = [
        "Upload a syllabus or lecture notes and Sapling maps out the concepts.",
        "Ask the tutor to walk you through anything you're stuck on.",
        "Quiz yourself and watch your knowledge tree fill in.",
    ]
    tips_html = (
        f'<ul style="margin:0 0 14px 0;padding-left:20px;font-family:{_FONT};font-size:15px;'
        f'line-height:1.6;color:{_TEXT};">'
        + "".join(f'<li style="margin:0 0 6px 0;">{_e(t)}</li>' for t in tips)
        + "</ul>"
    )
    html = _layout(
        preheader="A few ways to get started with Sapling.",
        heading=heading,
        body_html=(
            "".join(_p(_e(line)) for line in lines)
            + tips_html
            + _button(app_url, "Open Sapling")
            + _p(_e("Happy studying,") + "<br>" + _e("The Sapling team"))
        ),
        unsubscribe_url=unsubscribe_url,
    )
    text = "\n\n".join([
        heading,
        *lines,
        "\n".join(f"- {t}" for t in tips),
        f"Open Sapling: {app_url}",
        "Happy studying,\nThe Sapling team",
    ]) + _text_footer(unsubscribe_url)
    return subject, html, text


# ── Broadcast ───────────────────────────────────────────────────────────────


def _linkify_escaped(text: str) -> str:
    """HTML-escape `text`, turning bare http(s) URLs into links.

    Matches on the RAW text and escapes each segment separately, so an escaped
    entity can never end up inside (or terminate) a URL."""
    out: list[str] = []
    pos = 0
    for m in _URL_RE.finditer(text):
        url = m.group(0)
        trimmed = url
        while trimmed and trimmed[-1] in _TRAILING_PUNCT:
            # Keep a closing paren that belongs to the URL, e.g. wiki links.
            if trimmed[-1] == ")" and trimmed.count("(") >= trimmed.count(")"):
                break
            trimmed = trimmed[:-1]
        out.append(_e(text[pos:m.start()]))
        out.append(
            f'<a href="{_e(trimmed)}" target="_blank" '
            f'style="color:{BRAND};text-decoration:underline;">{_e(trimmed)}</a>'
        )
        pos = m.start() + len(trimmed)
    out.append(_e(text[pos:]))
    return "".join(out)


def render_plain_text_body(body: str) -> str:
    """Admin plain text → safe HTML paragraphs."""
    normalized = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [p for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    return "".join(
        _p("<br>".join(_linkify_escaped(line) for line in para.strip().split("\n")))
        for para in paragraphs
    )


def broadcast(subject: str, body: str, *, unsubscribe_url: str) -> tuple[str, str, str]:
    clean_subject = " ".join((subject or "").split())
    first_line = next((ln.strip() for ln in (body or "").splitlines() if ln.strip()), "")
    html = _layout(
        preheader=first_line[:140],
        heading=clean_subject,
        body_html=render_plain_text_body(body),
        unsubscribe_url=unsubscribe_url,
    )
    text = (body or "").replace("\r\n", "\n").strip() + _text_footer(unsubscribe_url)
    return clean_subject, html, text
