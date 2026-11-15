"""Public email endpoints: the unsubscribe page. No session, no auth.

Mounted at /api/email, and reached through the frontend's /api/* proxy, which
is why unsubscribe links are built on FRONTEND_URL.

The token in `?t=` is `<recipient_hash>.<hmac>` (email_service.unsubscribe_token),
so possession of the link is the credential and nothing here ever sees an
address. `?scope=` (default `all`) says what the link stops: `all` is every
kind of email but the admin alerts, `ops_alert` (the link in an admin alert)
is those alerts only. The signature binds the scope, so a link cannot be
turned into the other one.

GET never mutates: mail scanners and link previewers prefetch every URL in a
message, so a GET that unsubscribed would unsubscribe people who never clicked.
It renders a page whose button POSTs. POST does the work, and also serves
RFC 8058 one-click unsubscribes (mail clients POST `List-Unsubscribe=One-Click`
as a form body to the List-Unsubscribe URL); the body is not needed, since the
token is already in the URL.
"""

from __future__ import annotations

import logging
from html import escape

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from services import email_service

logger = logging.getLogger(__name__)

router = APIRouter()

_BRAND = "#445D22"
_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
}


#: Each scope's confirm page and done page: (title, message) twice.
_COPY = {
    email_service.SUPPRESSION_SCOPE_ALL: (
        ("Unsubscribe from Sapling emails?",
         "You'll stop receiving Sapling's newsletters, announcements and account updates at this "
         "address. If you get Sapling admin alerts, they have their own unsubscribe link."),
        ("You're unsubscribed",
         "You won't receive any more Sapling newsletters, announcements or account updates at this "
         "address. If you get Sapling admin alerts, they have their own unsubscribe link."),
    ),
    email_service.SUPPRESSION_SCOPE_OPS: (
        ("Stop Sapling admin alerts?",
         "You'll stop receiving Sapling's admin alerts (spend and error spikes) at this address. "
         "Other Sapling email is not affected."),
        ("You're unsubscribed from admin alerts",
         "You won't receive any more Sapling admin alerts at this address."),
    ),
}


def _page(
    title: str, message: str, *, form_token: str | None = None,
    scope: str = email_service.SUPPRESSION_SCOPE_ALL, status_code: int = 200,
) -> HTMLResponse:
    form = ""
    if form_token is not None:
        query = f"t={form_token}"
        if scope != email_service.SUPPRESSION_SCOPE_ALL:
            query += f"&scope={scope}"
        action = escape(f"/api/email/unsubscribe?{query}", quote=True)
        form = (
            f'<form method="post" action="{action}">'
            '<input type="hidden" name="List-Unsubscribe" value="One-Click">'
            '<button type="submit">Unsubscribe</button>'
            "</form>"
        )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{escape(title)} · Sapling</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin:0; background:#f5f3ec; color:#24301a;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  main {{ max-width:440px; margin:12vh auto 0; padding:0 16px; }}
  .card {{ background:#fff; border-radius:12px; border-top:4px solid {_BRAND}; padding:28px 24px; }}
  .brand {{ color:{_BRAND}; font-weight:700; font-size:20px; margin:0 0 16px 4px; }}
  h1 {{ font-size:22px; margin:0 0 12px; }}
  p {{ font-size:15px; line-height:1.6; margin:0 0 20px; }}
  button {{ background:{_BRAND}; color:#fff; border:0; border-radius:8px; padding:12px 22px;
           font-size:15px; font-weight:600; cursor:pointer; }}
  button:focus-visible {{ outline:3px solid #b9c99a; outline-offset:2px; }}
</style>
</head>
<body>
<main>
  <div class="brand">Sapling</div>
  <div class="card">
    <h1>{escape(title)}</h1>
    <p>{escape(message)}</p>
    {form}
  </div>
</main>
</body>
</html>
"""
    return HTMLResponse(html, status_code=status_code, headers=_HEADERS)


def _invalid() -> HTMLResponse:
    return _page(
        "This link doesn't work",
        "This unsubscribe link is invalid or incomplete. Try the link in the most "
        "recent email you received from Sapling.",
        status_code=400,
    )


@router.get("/unsubscribe")
def unsubscribe_page(t: str = Query(""), scope: str = Query(email_service.SUPPRESSION_SCOPE_ALL)):
    if not email_service.verify_unsubscribe_token(t, scope):
        return _invalid()
    (title, message), _done = _COPY[scope]
    return _page(title, message, form_token=t.strip(), scope=scope)


@router.post("/unsubscribe")
def unsubscribe(t: str = Query(""), scope: str = Query(email_service.SUPPRESSION_SCOPE_ALL)):
    rhash = email_service.verify_unsubscribe_token(t, scope)
    if not rhash:
        return _invalid()
    try:
        email_service.suppress(rhash, "unsubscribe", scope=scope)
    except Exception:  # noqa: BLE001
        logger.exception("unsubscribe write failed")
        return _page(
            "Something went wrong",
            "We couldn't process your unsubscribe just now. Please try again in a minute.",
            form_token=t.strip(),
            scope=scope,
            status_code=500,
        )
    _confirm, (title, message) = _COPY[scope]
    return _page(title, message)
