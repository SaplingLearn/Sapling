"""Email bodies. Pure functions returning `(subject, html, text)`.

The look: a deep forest header with the wordmark, then one of Sapling's growth
illustrations sitting on the seam between that header and the paper card (seed
for the waitlist, sprout on approval, sapling on the first sign-in). The three
lifecycle emails also carry a small growth track (Signed up, Approved, Signed
in) so a student can see where they are. Broadcasts drop the illustration and
read as a letter.

Built for email clients, not browsers: nested tables, inline styles, `bgcolor`
attributes for Outlook, and PNG/JPEG images only (Gmail won't render SVG; the
images are built by scripts/build_email_assets.py and served from
{EMAIL_ASSET_BASE_URL or FRONTEND_URL}/email/). Brand fonts (Aleo, SUSE,
Caveat) load from Google Fonts where the client allows it (Apple Mail, iOS)
and fall back to Georgia / system sans elsewhere (Gmail, Outlook).

Every template carries the recipient's one-click unsubscribe link in its footer
(the same URL rides the List-Unsubscribe header). Nothing here interpolates
unescaped input. Broadcast bodies are admin-written PLAIN TEXT: they are
HTML-escaped, blank-line paragraphs become <p>, and bare http(s) URLs become
links. Raw admin HTML is never injected.
"""

from __future__ import annotations

import re
from html import escape

import config

BRAND = "#445D22"     # brand forest: buttons, links
_FOREST = "#293c0e"   # sap-800: the header band (matches the hero PNGs)
_OUTER = "#e1ecd7"    # sap-100: the page around the card
_PAPER = "#fdfcf9"    # the card (matches the hero PNGs)
_TINT = "#f2f6ee"     # sap-50: the growth track and figure wells
_RULE = "#e3dfd3"
_INK = "#1a1814"
_BODY = "#3f3b31"
_MUTED = "#6f6857"

_SERIF = "Aleo,Georgia,'Times New Roman',serif"
_SANS = "SUSE,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
_HAND = "Caveat,'Bradley Hand','Segoe Print',cursive"
_FONTS_CSS = (
    "https://fonts.googleapis.com/css2?family=Aleo:wght@500;600"
    "&family=SUSE:wght@400;600&family=Caveat:wght@600&display=swap"
)

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?)]}'\""

#: The lifecycle, in order: (growth stage, caption).
_TRACK = (("seed", "Signed up"), ("sprout", "Approved"), ("sapling", "Signed in"))


def _e(value: str) -> str:
    return escape(value or "", quote=True)


def _site() -> str:
    return (getattr(config, "FRONTEND_URL", "") or "").rstrip("/") or "https://saplinglearn.com"


def _asset(name: str) -> str:
    base = (getattr(config, "EMAIL_ASSET_BASE_URL", "") or "").rstrip("/") or _site()
    return f"{base}/email/{name}"


# ── Building blocks ─────────────────────────────────────────────────────────


def _row(inner: str, *, pad: str = "0 48px", align: str = "left") -> str:
    """One row of the paper card. `inner` must already be safe HTML."""
    return (
        f'<tr><td class="px" bgcolor="{_PAPER}" align="{align}" '
        f'style="background:{_PAPER};padding:{pad};">{inner}</td></tr>'
    )


def _headline(text: str, *, align: str = "center") -> str:
    return (
        f'<h1 class="h1" style="margin:0;font-family:{_SERIF};font-size:36px;line-height:1.12;'
        f'font-weight:500;letter-spacing:-0.5px;color:{_INK};text-align:{align};">{_e(text)}</h1>'
    )


def _lede(text: str, *, align: str = "center") -> str:
    return (
        f'<p style="margin:16px 0 0 0;font-family:{_SANS};font-size:17px;line-height:1.6;'
        f'color:{_BODY};text-align:{align};">{_e(text)}</p>'
    )


def _p(inner_html: str) -> str:
    return (
        f'<p style="margin:0 0 16px 0;font-family:{_SANS};font-size:16px;'
        f'line-height:1.65;color:{_BODY};">{inner_html}</p>'
    )


def _button(href: str, label: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" '
        'style="margin:28px auto 0 auto;"><tr>'
        f'<td bgcolor="{BRAND}" style="border-radius:10px;background:{BRAND};">'
        f'<a href="{_e(href)}" target="_blank" '
        f'style="display:inline-block;padding:15px 30px;font-family:{_SANS};font-size:16px;'
        f'font-weight:600;line-height:1;color:#ffffff;text-decoration:none;border-radius:10px;">'
        f"{_e(label)}</a></td></tr></table>"
    )


def _section_title(text: str) -> str:
    return (
        f'<h2 style="margin:0 0 18px 0;font-family:{_SERIF};font-size:21px;line-height:1.25;'
        f'font-weight:500;color:{_INK};">{_e(text)}</h2>'
    )


def _track(current: str) -> str:
    """Signed up, Approved, Signed in: steps up to `current` lit, later ones
    washed out. A real sequence, so the connectors earn their place."""
    reached = True
    cells: list[str] = []
    for i, (stage, caption) in enumerate(_TRACK):
        lit = reached
        if stage == current:
            reached = False
        here = stage == current
        if i:
            line = "#a1bc83" if lit else _RULE
            cells.append(
                '<td valign="top" style="padding-top:27px;">'
                f'<div style="height:2px;line-height:2px;font-size:0;background:{line};">&nbsp;</div>'
                "</td>"
            )
        img = f"step-{stage}.png" if lit else f"step-{stage}-dim.png"
        color = _INK if here else (_BODY if lit else _MUTED)
        cells.append(
            '<td width="96" align="center" valign="top" style="width:96px;">'
            f'<img src="{_e(_asset(img))}" width="56" height="56" alt="" '
            'style="display:block;width:56px;height:56px;border:0;margin:0 auto;">'
            f'<div style="margin-top:8px;font-family:{_SANS};font-size:13px;line-height:1.3;'
            f'color:{color};font-weight:{600 if here else 400};">{_e(caption)}</div></td>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_TINT}" style="background:{_TINT};border-radius:14px;">'
        '<tr><td style="padding:20px 16px 18px 16px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        + "".join(cells)
        + "</tr></table></td></tr></table>"
    )


def _steps(items: list[tuple[str, str]]) -> str:
    """A numbered sequence: (bold lead, rest of the sentence)."""
    rows = []
    for n, (lead, rest) in enumerate(items, start=1):
        rows.append(
            "<tr>"
            '<td width="40" valign="top" style="width:40px;padding:0 0 18px 0;">'
            f'<div style="width:28px;height:28px;line-height:28px;border-radius:14px;background:{_TINT};'
            f'border:1px solid #c5d7b2;text-align:center;font-family:{_SERIF};font-size:14px;'
            f'font-weight:600;color:{BRAND};">{n}</div></td>'
            f'<td valign="top" style="padding:3px 0 18px 0;font-family:{_SANS};font-size:16px;'
            f'line-height:1.55;color:{_BODY};">'
            f'<strong style="color:{_INK};font-weight:600;">{_e(lead)}</strong> {_e(rest)}</td>'
            "</tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + "".join(rows)
        + "</table>"
    )


def _leaves(items: list[tuple[str, str]]) -> str:
    """Unordered points, each marked with the Sapling leaf."""
    rows = []
    for title, text in items:
        rows.append(
            "<tr>"
            '<td width="30" valign="top" style="width:30px;padding:4px 0 20px 0;">'
            f'<img src="{_e(_asset("leaf.png"))}" width="18" alt="" '
            'style="display:block;width:18px;height:auto;border:0;"></td>'
            f'<td valign="top" style="padding:0 0 20px 0;font-family:{_SANS};font-size:16px;'
            f'line-height:1.55;color:{_BODY};">'
            f'<div style="font-family:{_SERIF};font-size:18px;line-height:1.3;font-weight:500;'
            f'color:{_INK};margin:0 0 4px 0;">{_e(title)}</div>{_e(text)}</td>'
            "</tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + "".join(rows)
        + "</table>"
    )


def _figure(src: str, alt: str, caption: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_TINT}" style="background:{_TINT};border-radius:14px;">'
        '<tr><td style="padding:10px 10px 0 10px;">'
        f'<img src="{_e(src)}" width="484" alt="{_e(alt)}" '
        'style="display:block;width:100%;max-width:484px;height:auto;border:0;border-radius:9px;">'
        "</td></tr>"
        f'<tr><td style="padding:12px 16px 14px 16px;font-family:{_SANS};font-size:14px;'
        f'line-height:1.5;color:{_MUTED};">{_e(caption)}</td></tr></table>'
    )


def _team() -> str:
    return (
        f'<p style="margin:2px 0 0 0;font-family:{_HAND};font-size:30px;line-height:1.1;'
        f'font-weight:600;color:{BRAND};">The Sapling team</p>'
    )


def _signoff(closing: str) -> str:
    return (
        f'<p style="margin:0;font-family:{_SANS};font-size:16px;line-height:1.5;color:{_BODY};">'
        f"{_e(closing)}</p>" + _team()
    )


def _spacer(px: int) -> str:
    return (
        f'<tr><td bgcolor="{_PAPER}" height="{px}" style="background:{_PAPER};height:{px}px;'
        f'line-height:{px}px;font-size:0;">&nbsp;</td></tr>'
    )


def _rule() -> str:
    return _row(f'<div style="height:1px;line-height:1px;font-size:0;background:{_RULE};">&nbsp;</div>')


def _header(stage: str | None) -> str:
    site = _site()
    mark = (
        f'<a href="{_e(site)}" target="_blank"><img src="{_e(_asset("wordmark-light.png"))}" '
        'width="104" height="28" alt="Sapling" style="display:block;width:104px;height:28px;border:0;"></a>'
    )
    if not stage:
        return (
            f'<tr><td class="px" bgcolor="{_FOREST}" style="background:{_FOREST};padding:28px 48px 0 48px;">'
            f"{mark}</td></tr>"
            '<tr><td style="font-size:0;line-height:0;">'
            f'<img src="{_e(_asset("band.png"))}" width="600" alt="" '
            f'style="display:block;width:100%;max-width:600px;height:auto;border:0;background:{_FOREST};">'
            "</td></tr>" + _spacer(44)
        )
    # The hero PNG's top half is the same forest as this cell, so the band runs
    # straight into it and the illustration sits on the seam.
    return (
        f'<tr><td class="px" bgcolor="{_FOREST}" style="background:{_FOREST};padding:28px 48px 6px 48px;">'
        f"{mark}</td></tr>"
        '<tr><td style="font-size:0;line-height:0;">'
        f'<img src="{_e(_asset(f"hero-{stage}.png"))}" width="600" alt="" '
        f'style="display:block;width:100%;max-width:600px;height:auto;border:0;background:{_FOREST};">'
        "</td></tr>"
    )


def _layout(
    *,
    title: str,
    preheader: str,
    stage: str | None,
    rows: list[str],
    reason: str,
    unsubscribe_url: str,
) -> str:
    """The shared shell. Every entry of `rows` must already be safe HTML rows."""
    site = _site()
    return f"""<!doctype html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<title>{_e(title)}</title>
<link href="{_e(_FONTS_CSS)}" rel="stylesheet">
<style>
  body {{ margin:0; padding:0; -webkit-text-size-adjust:100%; }}
  a {{ color:{BRAND}; }}
  @media (max-width: 620px) {{
    .px {{ padding-left:24px !important; padding-right:24px !important; }}
    .h1 {{ font-size:30px !important; }}
  }}
</style>
</head>
<body bgcolor="{_OUTER}" style="margin:0;padding:0;background:{_OUTER};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{_e(preheader)}&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{_OUTER}" style="background:{_OUTER};">
<tr><td align="center" style="padding:32px 12px 40px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;border-radius:18px;overflow:hidden;background:{_PAPER};">
{_header(stage)}
{"".join(rows)}
{_spacer(44)}
</table>
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">
<tr><td align="center" style="padding:24px 32px 0 32px;font-family:{_SANS};font-size:13px;line-height:1.7;color:{_MUTED};">
{_e(reason)}<br>
<a href="{_e(unsubscribe_url)}" style="color:{_MUTED};text-decoration:underline;">Unsubscribe</a> from Sapling emails.
</td></tr>
<tr><td align="center" style="padding:14px 32px 0 32px;font-family:{_SERIF};font-size:15px;color:{BRAND};">
<a href="{_e(site)}" style="color:{BRAND};text-decoration:none;">Sapling</a>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def _text(*blocks: str, unsubscribe_url: str, reason: str) -> str:
    body = "\n\n".join(b.strip("\n") for b in blocks if b)
    return f"{body}\n\n--\n{reason}\nUnsubscribe: {unsubscribe_url}\n"


def _text_steps(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"{n}. {lead} {rest}" for n, (lead, rest) in enumerate(items, start=1))


# ── Transactional ───────────────────────────────────────────────────────────

_WAITLIST_REASON = "You're getting this because you joined the Sapling waitlist with this address."


def waitlist_confirmation(*, unsubscribe_url: str) -> tuple[str, str, str]:
    subject = "You're on the Sapling waitlist"
    heading = "You're on the list"
    lede = (
        "Thanks for signing up. Sapling turns your course materials into a tutor, "
        "practice quizzes and a map of what you know, and we're opening it to "
        "students a few at a time."
    )
    steps = [
        ("We open spots in small groups,", "so every new student gets a good first week."),
        ("When yours opens, you'll get an email", "with a link to sign in. Keep an eye out for it."),
        ("Sign in with your school Google account", "and add your courses. That's all the setup there is."),
    ]
    rows = [
        _row(_headline(heading) + _lede(lede), pad="10px 48px 0 48px"),
        _spacer(32),
        _row(_track("seed"), pad="0 40px"),
        _spacer(36),
        _row(_section_title("What happens next") + _steps(steps)),
        _rule(),
        _spacer(28),
        _row(_signoff("See you soon,")),
    ]
    html = _layout(
        title=subject, preheader="We'll email you the moment your spot opens.",
        stage="seed", rows=rows, reason=_WAITLIST_REASON, unsubscribe_url=unsubscribe_url,
    )
    text = _text(
        heading, lede, "What happens next\n" + _text_steps(steps), "See you soon,\nThe Sapling team",
        unsubscribe_url=unsubscribe_url, reason=_WAITLIST_REASON,
    )
    return subject, html, text


def waitlist_approved(*, signin_url: str, unsubscribe_url: str) -> tuple[str, str, str]:
    subject = "Your Sapling spot is ready"
    heading = "Your spot is ready"
    lede = (
        "You're off the waitlist. Sign in with your school Google account and "
        "Sapling will walk you through setting up your courses."
    )
    steps = [
        ("Sign in and pick your courses.", "Onboarding takes about two minutes."),
        ("Upload a syllabus or lecture notes.", "Sapling pulls out the concepts for the whole term."),
        ("Ask the tutor about what's coming up next.", "It works from your course materials, not the whole internet."),
    ]
    caption = (
        "Your knowledge tree: every course becomes a cluster of concepts that fills "
        "in as you study, quiz and ask questions."
    )
    rows = [
        _row(
            _headline(heading) + _lede(lede) + _button(signin_url, "Sign in to Sapling"),
            pad="10px 48px 0 48px",
        ),
        _spacer(36),
        _row(_track("sprout"), pad="0 40px"),
        _spacer(36),
        _row(_section_title("Your first ten minutes") + _steps(steps)),
        _spacer(8),
        _row(_figure(_asset("tree-map.jpg"), "A Sapling knowledge tree with concepts grouped by course", caption)),
        _spacer(32),
        _rule(),
        _spacer(28),
        _row(_signoff("Happy studying,")),
    ]
    html = _layout(
        title=subject, preheader="You're off the waitlist. Sign in to get started.",
        stage="sprout", rows=rows, reason=_WAITLIST_REASON, unsubscribe_url=unsubscribe_url,
    )
    text = _text(
        heading, lede, f"Sign in to Sapling: {signin_url}",
        "Your first ten minutes\n" + _text_steps(steps), "Happy studying,\nThe Sapling team",
        unsubscribe_url=unsubscribe_url, reason=_WAITLIST_REASON,
    )
    return subject, html, text


def welcome(first_name: str | None, *, app_url: str, unsubscribe_url: str) -> tuple[str, str, str]:
    name = " ".join((first_name or "").split())
    subject = "Welcome to Sapling"
    heading = f"Welcome, {name}" if name else "Welcome to Sapling"
    lede = (
        "Your account is set up. Here's how students get the most out of their "
        "first week with Sapling."
    )
    tips = [
        ("Start with a syllabus",
         "Upload it in Library and Sapling maps the concepts for the whole term, "
         "so the tutor and quizzes know what's coming."),
        ("Ask the tutor anything",
         "It reads your course materials, so its answers line up with what your "
         "professor actually covers."),
        ("Quiz yourself before the exam",
         "Short quizzes go after what you're shakiest on and update your tree as you answer."),
        ("Watch your tree fill in",
         "Green is mastered, orange is getting there, red is worth another look. "
         "Grey is still to explore."),
    ]
    reason = "You're getting this because you just signed in to Sapling for the first time."
    rows = [
        _row(_headline(heading) + _lede(lede) + _button(app_url, "Open Sapling"), pad="10px 48px 0 48px"),
        _spacer(36),
        _row(_track("sapling"), pad="0 40px"),
        _spacer(36),
        _row(_section_title("Four things to try this week") + _leaves(tips)),
        _rule(),
        _spacer(28),
        _row(_signoff("Happy studying,")),
    ]
    html = _layout(
        title=subject, preheader="How to get the most out of your first week.",
        stage="sapling", rows=rows, reason=reason, unsubscribe_url=unsubscribe_url,
    )
    text = _text(
        heading, lede, f"Open Sapling: {app_url}",
        "Four things to try this week\n" + "\n".join(f"- {t}: {d}" for t, d in tips),
        "Happy studying,\nThe Sapling team",
        unsubscribe_url=unsubscribe_url, reason=reason,
    )
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
    reason = "You're getting this because you signed up for Sapling."
    rows = [
        _row(_headline(clean_subject, align="left"), pad="0 48px 26px 48px"),
        _row(render_plain_text_body(body)),
        _spacer(12),
        _row(_team()),
    ]
    html = _layout(
        title=clean_subject, preheader=first_line[:140], stage=None,
        rows=rows, reason=reason, unsubscribe_url=unsubscribe_url,
    )
    text = (body or "").replace("\r\n", "\n").strip()
    text = f"{text}\n\n--\n{reason}\nUnsubscribe: {unsubscribe_url}\n"
    return clean_subject, html, text
