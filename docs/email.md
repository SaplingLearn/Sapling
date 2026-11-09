# Email (Resend)

Sapling sends four kinds of email, all through `backend/services/email_service.py`
(the only module that talks to Resend):

| kind | category | when | dedupe (never twice) |
| --- | --- | --- | --- |
| `waitlist_confirmation` | transactional | someone joins the waitlist (`POST /api/newsletter/subscribe`) | per address |
| `waitlist_approved` | transactional | an admin approves a waitlist email (Admin → Allowlist, single or bulk) | per address, so a revoke and re-approve doesn't re-send |
| `welcome` | transactional | an account's first approved sign-in while `users.welcomed_at` is NULL | per account |
| `broadcast` | notification | Admin → Email, sent to a chosen audience | per broadcast × address |

The category lives in one place, `email_service.EMAIL_CATEGORIES` (a kind
missing from it counts as notification). **Notification** mail is not sent to
an account whose Settings → Notifications → Email (`user_settings.notification_email`)
is off: the send returns `opted_out` and records nothing, and broadcast
audiences leave those accounts out of their counts. The setting is matched by
address hash, so it also covers that person's waitlist address, and a toggle
reaches a running send within a minute. **Transactional** mail (waitlist,
"you're in", welcome) ignores that setting. Only the suppression list stops it.

**Kill switch:** with `RESEND_API_KEY` unset, nothing is sent. Each send is
recorded as `skipped`, and the admin portal shows a "not configured" banner.
Tests, E2E and local dev run this way. A `skipped` or `failed` send can be
re-claimed later, so re-approving someone after the key is set does send their
"you're in". The welcome works the same way: `users.welcomed_at` is stamped
only once a welcome is actually `sent`, so a welcome that was skipped or
failed goes out on that person's next sign-in. If the welcome went out but
the stamp failed, the next sign-in's send comes back `duplicate`. Its ledger
row says `sent`, so `welcomed_at` is stamped then.

**Send ledger (`email_sends`).** A send claims its dedupe key as `queued`
(with `claimed_at`) before it talks to Resend, then records `sent`, `failed`
or `skipped`. A key that is `sent`, or `queued` less than 15 minutes ago, is
never sent again. Anything else can be re-claimed by the next send of that key:
`skipped`, `failed`, `suppressed` (once an admin removes the suppression), and
a `queued` row older than 15 minutes, which means the process died mid-send or
couldn't write the outcome. A failed outcome write is retried once, then
logged at ERROR.

**Idempotency.** Each send carries a Resend `Idempotency-Key`. The first
attempt uses the dedupe key itself. Whether the next attempt reuses it depends
on what happened last time:

| last outcome | next attempt's key |
| --- | --- |
| unknown: transport error or timeout, a crash before the status write, or a 409 `invalid_idempotent_request` (the payload changed, e.g. a first name learned in between) | the **same** key, so if that attempt reached Resend, Resend returns its stored result instead of delivering again |
| definitive: Resend answered with any other non-2xx (4xx, 5xx, a 429 after the retry) | a **new** key, `<dedupe key>#<n>` (`email_sends.idempotency_gen`), so the retry is a real retry and not a replay of the cached failure |

A 409 `concurrent_idempotent_requests` means another attempt with the same key
is still in flight at Resend, for example a re-claim of a stale `queued` row
racing a live send. That attempt owns the outcome, so this one returns
`duplicate` and leaves the row alone. Resend keeps keys for **24 hours**, which
leaves one residual risk: if an attempt's outcome is never learned and the key
is re-claimed more than 24 hours later, that address can get the email twice.

Resend's docs don't say whether a failed response is stored against a key,
which is why a definitive failure moves to a new key.

**Privacy:** the email tables (`email_sends`, `email_suppressions`,
`email_broadcasts`) never store an address, only `recipient_hash`, an HMAC
keyed off `SESSION_SECRET`. **Rotating `SESSION_SECRET` orphans every
suppression and invalidates every unsubscribe link**, so don't rotate it
casually.

**Unsubscribe:** every email carries a footer link and RFC 8058 one-click
headers (`List-Unsubscribe` / `List-Unsubscribe-Post`). The link is
`{FRONTEND_URL}/api/email/unsubscribe?t=…`, which the frontend proxies to the
backend. GET shows a confirm page and POST suppresses, because mail scanners
prefetch GETs. A suppressed address gets no email of any kind; a send to it
returns and records `suppressed`, including over an earlier `skipped`/`failed`
row for the same key.

**Undoing a suppression:** `POST /api/admin/email/suppressions/remove` with
`{"email": "…"}` (admin only) takes the address off the list and returns
`{"removed": true|false}`. The audit log records the hash, never the address.
There is no admin UI for it yet.

## Broadcasts

A broadcast resolves its audience when it's sent and mails it from a
background task, writing progress (and a `heartbeat_at`) every 25 recipients or
30 seconds. When it finishes, its status is one of:

| status | meaning |
| --- | --- |
| `sent` | everything that went anywhere went out |
| `partial` | some went out and some failed, or the run died part-way |
| `failed` | nothing went out and something failed |
| `skipped` | nothing went out and nothing failed: no `RESEND_API_KEY`, everyone suppressed or opted out, or an empty audience |

A run killed by a deploy or restart stays `sending`. Once its heartbeat is 10
minutes old, Admin → Email shows it as **stalled**. Stalled, `failed` and
`partial` broadcasts have a **Resume** button
(`POST /api/admin/email/broadcasts/{id}/resume`). Resuming re-resolves the
audience as it is now, because addresses are never stored, so the original
list can't be replayed. Every recipient then goes back through the
per-broadcast dedupe: anyone already mailed is skipped, failed sends are
retried, and anyone who joined the audience since gets it too. A resumed run
takes its sent count from `email_sends`. Two clicks start one run.

## Design and images

`services/email_templates.py` builds every email: the landing page hero
(pale ground, point cloud) with the navbar's hand-drawn wordmark, as a header image
over a white card, then Aleo headlines and SUSE body text, all left-aligned.
The three lifecycle emails show a Signed up / Approved / Signed in progress
line; broadcasts are the same card without it. The "you're in" and welcome
emails greet the person by first name when it's known. Aleo and SUSE load from
Google Fonts where the client allows it (Apple Mail, iOS); Gmail and Outlook
fall back to Georgia and the system sans.

The header is one JPEG, `frontend/public/email/header.jpg`, rendered by a real
browser from the hero's palette and cloud and the approved wordmark SVG:
`cd frontend && node scripts/build-email-header.mjs` (uses Playwright's
Chromium). It loads from `{EMAIL_ASSET_BASE_URL or FRONTEND_URL}/email/`, so it
only shows once the frontend serving it is deployed. Admin → Email previews
the real server-rendered broadcast (`POST /api/admin/email/broadcasts/preview`).

## Personalizing broadcasts

Broadcast subjects and bodies can use variables, filled in per recipient:

| variable | value | if unknown |
| --- | --- | --- |
| `{{first_name}}` | the account's first name, or the first name a /pending waitlist join stored | `there` |
| `{{name}}` | the account's full name (else the first name) | `there` |
| `{{email}}` | the address it's sent to | |
| `{{app_link}}` | `{FRONTEND_URL}/dashboard`, as an "Open Sapling" link | |
| `{{signin_link}}` | `{FRONTEND_URL}` (its Sign in button starts Google OAuth), as a "Sign in to Sapling" link | |

`{{first_name|friend}}` sets your own fallback. For the two links the text
after `|` is the label instead. A link alone on its line becomes a button like
the ones in the other emails (`{{signin_link|Join the beta}}`); inside a
sentence it becomes a link on that label (`You can {{app_link|open your
dashboard}} any time.`). The plain-text part gets the URL. Landing-form waitlist signups
gave only an email, so they get the fallback. An unknown variable (a typo like
`{{frist_name}}`) is rejected before anything sends; the composer flags it
from the preview. Preview and "Send test to me" fill in your own details.
Values are inserted into the plain text before it's escaped, so a name can't
inject markup. Defined in `backend/services/email_variables.py`.

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
   existing students. `20261106055333_state_machines_audit.sql`
   adds `email_sends.claimed_at`, `email_broadcasts.heartbeat_at` and the
   `partial`/`skipped` broadcast statuses, and
   `20261106055333_state_machines_audit.sql` adds
   `email_sends.idempotency_gen`. Apply both before the code that writes them.
6. **Smoke test.** Go to Admin → Email, check the banner is gone, and use "Send
   test to me". The history and `email_sends` show the result; a failure's
   `error` column says why, with the address scrubbed.

Staging caveat: staging's frontend is behind Cloudflare Access, so unsubscribe
links in staging emails land on the Access login. Prod is unaffected.

## Known gaps (follow-ups)

- No Resend bounce/complaint webhook yet. Resend suppresses hard bounces on its
  side, but `email_suppressions` only learns about unsubscribes.
- A broadcast runs as one in-process background task at about 2 emails per
  second. A restart mid-send stops it until an admin resumes it (see
  Broadcasts); nothing resumes it automatically.
- `POST /api/newsletter/subscribe` is public and has no rate limit or bot
  check. Dedupe caps it at one confirmation per address, but adding Turnstile
  there would stop it being used to mail strangers.
- Admin → Users can remove someone's access (they go back on the Allowlist as a
  signup) but sends no email; approving them again on the Allowlist doesn't
  re-send "you're in", since that's deduped per address.
