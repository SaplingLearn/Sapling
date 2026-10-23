# Email (Resend)

Sapling sends four kinds of email, all through `backend/services/email_service.py`
(the only module that talks to Resend):

| kind | when | dedupe (never twice) |
| --- | --- | --- |
| `waitlist_confirmation` | someone joins the waitlist (`POST /api/newsletter/subscribe`) | per address |
| `waitlist_approved` | an admin approves a waitlist email (Admin → Allowlist, single or bulk) | per address, so a revoke and re-approve doesn't re-send |
| `welcome` | an account's first approved sign-in (`users.welcomed_at` claim) | per account |
| `broadcast` | Admin → Email, sent to a chosen audience | per broadcast × address |

**Kill switch:** with `RESEND_API_KEY` unset, nothing is sent. Each send is
recorded as `skipped`, and the admin portal shows a "not configured" banner.
Tests, E2E and local dev run this way. A `skipped` or `failed` send can be
re-claimed later, so re-approving someone after the key is set does send their
"you're in". A welcome claimed while unconfigured is not retried.

**Privacy:** the email tables (`email_sends`, `email_suppressions`,
`email_broadcasts`) never store an address, only `recipient_hash`, an HMAC
keyed off `SESSION_SECRET`. **Rotating `SESSION_SECRET` orphans every
suppression and invalidates every unsubscribe link**, so don't rotate it
casually.

**Unsubscribe:** every email carries a footer link and RFC 8058 one-click
headers (`List-Unsubscribe` / `List-Unsubscribe-Post`). The link is
`{FRONTEND_URL}/api/email/unsubscribe?t=…`, which the frontend proxies to the
backend. GET shows a confirm page and POST suppresses, because mail scanners
prefetch GETs. A suppressed address gets no email of any kind.

## Design and images

`services/email_templates.py` builds every email: a forest header with the
wordmark on a white card, Aleo headlines and SUSE body text, all
left-aligned. The three lifecycle emails show a Signed up / Approved / Signed in
progress line; the "you're in" email adds a knowledge-tree screenshot.
Broadcasts are the same card without the progress line. Aleo and SUSE load from
Google Fonts where the client allows it (Apple Mail, iOS); Gmail and Outlook
fall back to Georgia and the system sans.

The two images are PNG/JPEG (Gmail won't show SVG) in `frontend/public/email/`,
built by `backend/scripts/build_email_assets.py` (needs `rsvg-convert` and
ImageMagick). They load from `{EMAIL_ASSET_BASE_URL or FRONTEND_URL}/email/`,
so they only work once the frontend serving them is deployed. Admin → Email
previews the real server-rendered broadcast
(`POST /api/admin/email/broadcasts/preview`).

## Hooking up Resend

1. **Domain.** In Resend → Domains, add the sending domain (`saplinglearn.com`,
   or a subdomain like `mail.saplinglearn.com` to keep its reputation separate).
   Add every DNS record Resend lists (the DKIM TXT, plus the MX and SPF TXT for
   its bounce subdomain) in Cloudflare DNS, set to **DNS only, not proxied**.
   Wait for Resend to show the domain as Verified.
2. **DMARC** (if the domain has none yet): a TXT record at `_dmarc` with
   `v=DMARC1; p=none; rua=mailto:<you>`. Gmail and Yahoo require DMARC for bulk
   senders.
3. **API key.** In Resend → API Keys, create a key with **Sending access**,
   restricted to that domain. Use one key per environment.
4. **Railway env vars**, on the backend service for staging and prod:
   - `RESEND_API_KEY=re_…`
   - `EMAIL_FROM="Sapling <hello@saplinglearn.com>"` (the address must be on the
     verified domain)
   - `EMAIL_REPLY_TO=` (optional; where replies go)
   - `EMAIL_ASSET_BASE_URL=https://saplinglearn.com` on **staging** only: its
     frontend is behind Cloudflare Access, so recipients couldn't load images
     from it. Prod leaves it unset (it defaults to `FRONTEND_URL`).
5. **Migrations** (before deploying the code): `20261022062444_newsletter_joined.sql`
   and `20261022063145_email.sql`. The second backfills `users.welcomed_at` for
   every account that's already approved, so the deploy doesn't welcome
   existing students.
6. **Smoke test.** Go to Admin → Email, check the banner is gone, and use "Send
   test to me". The history and `email_sends` show the result; a failure's
   `error` column says why, with the address scrubbed.

Staging caveat: staging's frontend is behind Cloudflare Access, so unsubscribe
links in staging emails land on the Access login. Prod is unaffected.

## Known gaps (follow-ups)

- No Resend bounce/complaint webhook yet. Resend suppresses hard bounces on its
  side, but `email_suppressions` only learns about unsubscribes.
- A broadcast runs as one in-process background task at about 2 emails per
  second. A restart mid-send leaves it `sending` with no resume.
- `POST /api/newsletter/subscribe` is public and has no rate limit or bot
  check. Dedupe caps it at one confirmation per address, but adding Turnstile
  there would stop it being used to mail strangers.
- Admin → Users can remove someone's access (they go back on the Allowlist as a
  signup) but sends no email; approving them again on the Allowlist doesn't
  re-send "you're in", since that's deduped per address.
