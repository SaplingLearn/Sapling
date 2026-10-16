/**
 * Product analytics (PostHog), browser side — the ONLY module that talks to
 * posthog-js, and the owner of the student's account preference as this page
 * knows it.
 *
 * Two senders share ONE account preference (`user_settings.analytics_opt_out`):
 * this module's pageviews, and the backend's mirror (#677: product events,
 * `$ai_generation` records and server error reports — backend
 * services/posthog_client.py), which reads the same column on its own. So the
 * Settings switch governs BOTH, and is usable whenever the account answer is
 * known — whether or not this build sends pageviews.
 *
 * The model is deliberately small:
 *
 * - **Pageviews only from signed-in students who have not opted out, only
 *   inside the app shell.** posthog-js is not even loaded on public/marketing
 *   pages, `/auth/*`, onboarding, or for anyone signed out. The account
 *   preference is read through `lib/accountSettings.ts` (one shared GET per
 *   student, used by both the UserProvider and the Settings screen); only an
 *   explicit `false` loads and starts posthog-js. `true`, a missing field, or
 *   a failed read leaves it off (fail closed). The capture gate also checks
 *   the LIVE route (lib/appRoutes.ts), so a navigation out of the shell sends
 *   nothing.
 * - **Pageviews only.** `$pageview` + `$pageleave`. Click autocapture,
 *   rageclicks, dead clicks, heatmaps, web vitals, session recording,
 *   exception capture — all OFF. Product usage comes from backend events.
 * - **The account flag is the single source of truth.** Nothing about the
 *   choice is stored in the browser — not by us, and not by posthog-js
 *   (`persistence: 'memory'`, and posthog-js's own opt-out/opt-in, which
 *   would write localStorage, is never called). Every page load starts from
 *   nothing and asks the account again. The price is no session continuity
 *   across full page loads; that trade is accepted.
 * - **A capture gate** (`gatedBeforeSend`) drops every event unless capture
 *   is allowed right now, so opting out or leaving the shell stops it at once.
 * - **An admin switch gates the pageviews.** `setProductAnalyticsFlag`
 *   (called by `FlagsProvider` off `GET /api/flags`'s `product_analytics`
 *   flag, #620/ADR 0029 — the same flag the backend mirror checks per
 *   student) must be on before posthog-js starts, or before the UserProvider
 *   reads the preference for it. It defaults to off, so a page that hasn't
 *   heard from `/api/flags` yet — or never will — sends no pageviews: the
 *   same fail-closed posture as the account preference.
 * - **Do Not Track / Global Privacy Control means no pageviews**, always.
 * - **Identified by the Sapling account id, nothing else.** `identify`
 *   carries `users.id` — `user_<Google account id>`, an account identifier,
 *   not a random or per-service one — and no name, email or person
 *   properties. It runs in posthog-js's `loaded` hook, before its initial
 *   `$pageview`, so that one pageview is already the student's.
 * - **No credentials in URLs.** The `/auth/callback` handoff params are masked
 *   by posthog-js AT THE SOURCE (`custom_personal_data_properties`), and
 *   `before_send` strips every query string and fragment from every URL
 *   value (absolute or relative), recursively, as defence in depth.
 * - **Nothing but events on the wire, unbatched and uncompressed.** Feature
 *   flags are off (`advanced_disable_flags` — the app uses none; posthog-js
 *   then skips its remote config too), every remote-UI extension (surveys,
 *   product tours, conversations, web experiments, site apps) is disabled,
 *   each event is sent as it happens (`request_batching: false`, so a
 *   sign-out never strands a queued batch), and bodies are plain JSON
 *   (`disable_compression`, so the `/ingest` proxy can check the project key
 *   without decompressing anything).
 * - **No client IP, no geolocation.** The `/ingest` proxy never forwards the
 *   browser's IP and every event carries `$geoip_disable`; the PostHog
 *   project setting "Discard client IP data" must stay ON
 *   (docs/frontend-audit/07-integrations.md).
 * - **Same-origin transport only.** `api_host` is `/ingest`, served by
 *   `src/app/ingest/[...path]/route.ts`. `NEXT_PUBLIC_POSTHOG_HOST` may only
 *   move it to another same-origin path — never to an external host that
 *   would bypass the proxy.
 * - **Pageviews inert unless configured.** No `NEXT_PUBLIC_POSTHOG_KEY`,
 *   local UI mode (`NEXT_PUBLIC_LOCAL_MODE`) or the E2E/test build
 *   (`NEXT_PUBLIC_TEST_MODE`) → posthog-js never loads and the UserProvider
 *   reads nothing for it. The account preference — and so the Settings
 *   switch — still works, because it governs the backend mirror too.
 *
 * NEXT_PUBLIC_* values are inlined at BUILD time, so each one is read with a
 * literal `process.env.NEXT_PUBLIC_…` expression below.
 */
import type { CaptureResult, PostHog, PostHogConfig } from "posthog-js";

import { isAppShellRoute } from "./appRoutes";
import { INGEST_PREFIX } from "./ingestProxy";
import { isTruthyBuildFlag } from "./testMode";

/** Build-time env bag the gate reads. Injectable for tests. */
export interface AnalyticsEnv {
  NEXT_PUBLIC_POSTHOG_KEY?: string;
  NEXT_PUBLIC_POSTHOG_HOST?: string;
  NEXT_PUBLIC_LOCAL_MODE?: string;
  NEXT_PUBLIC_TEST_MODE?: string;
}

export function readAnalyticsEnv(): AnalyticsEnv {
  return {
    NEXT_PUBLIC_POSTHOG_KEY: process.env.NEXT_PUBLIC_POSTHOG_KEY,
    NEXT_PUBLIC_POSTHOG_HOST: process.env.NEXT_PUBLIC_POSTHOG_HOST,
    NEXT_PUBLIC_LOCAL_MODE: process.env.NEXT_PUBLIC_LOCAL_MODE,
    NEXT_PUBLIC_TEST_MODE: process.env.NEXT_PUBLIC_TEST_MODE,
  };
}

/** PostHog US app — where toolbar / "view in PostHog" links point. */
export const UI_HOST = "https://us.posthog.com";

/** Why analytics is off, or null when it should initialise. */
export function analyticsDisabledReason(
  env: AnalyticsEnv,
): "no_key" | "local_mode" | "test_mode" | null {
  // One definition of "test build" for the whole app (lib/testMode.ts).
  if (isTruthyBuildFlag(env.NEXT_PUBLIC_TEST_MODE)) return "test_mode";
  if (isTruthyBuildFlag(env.NEXT_PUBLIC_LOCAL_MODE)) return "local_mode";
  if (!(env.NEXT_PUBLIC_POSTHOG_KEY ?? "").trim()) return "no_key";
  return null;
}

/**
 * URL query parameters posthog-js replaces with `<MASKED>` at the source, on
 * top of its built-in ad-click ids — everything a frontend URL can carry that
 * is a credential, an identity, or student-authored text:
 * - the `/auth/callback` sign-in handoff (backend/routes/auth.py
 *   `google_callback`): `auth_token`, `user_id`, `avatar`, `popup_id`,
 *   `is_approved`;
 * - generic OAuth / token names, should one ever land on a frontend URL:
 *   `code`, `state`, `token`, `access_token`, `id_token`, `email`;
 * - `topic`, which deep links (`/learn?topic=…`) fill with a concept label
 *   taken from the student's own notes.
 * Params that only name a row (`note`, `course`, `session`, …) are left
 * alone; `before_send` drops every query string anyway.
 */
export const PERSONAL_DATA_QUERY_PARAMS = [
  "auth_token",
  "user_id",
  "avatar",
  "popup_id",
  "is_approved",
  "code",
  "state",
  "token",
  "access_token",
  "id_token",
  "email",
  "topic",
] as const;

/**
 * Strip `?query` and `#fragment` from an absolute URL; anything else is
 * returned unchanged. Query strings here can carry the OAuth handoff token
 * (`/auth/callback?auth_token=…`) and the Google avatar URL.
 */
export function stripUrlQuery(value: unknown): unknown {
  // Absolute (`https://…`), protocol-relative (`//…`) and root-relative
  // (`/path?…`) URLs alike: a relative href can carry a query too.
  if (typeof value !== "string" || !/^(https?:\/\/|\/)/i.test(value)) return value;
  const cut = value.search(/[?#]/);
  return cut === -1 ? value : value.slice(0, cut);
}

/** Deeper than any posthog-js payload; also the stop for a cyclic object. */
const MAX_SCRUB_DEPTH = 8;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  if (v === null || typeof v !== "object") return false;
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

/**
 * Strip URL queries from every string in `value`, however deeply nested.
 * Mutates objects/arrays in place.
 */
export function scrubValue(value: unknown, depth = 0): unknown {
  if (typeof value === "string") return stripUrlQuery(value);
  if (depth >= MAX_SCRUB_DEPTH) return value;
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) value[i] = scrubValue(value[i], depth + 1);
    return value;
  }
  if (!isPlainObject(value)) return value;
  for (const key of Object.keys(value)) value[key] = scrubValue(value[key], depth + 1);
  return value;
}

/**
 * `before_send` hook: remove query strings/fragments from every URL value,
 * however deeply nested, and opt the event out of GeoIP enrichment.
 */
export function scrubEvent(event: CaptureResult | null): CaptureResult | null {
  if (!event) return event;
  if (event.properties) {
    scrubValue(event.properties);
    event.properties.$geoip_disable = true;
  }
  if (event.$set) scrubValue(event.$set);
  if (event.$set_once) scrubValue(event.$set_once);
  return event;
}

/**
 * `NEXT_PUBLIC_POSTHOG_HOST` may move the proxy to another SAME-ORIGIN path
 * ("/something"), nothing else: an absolute or protocol-relative URL would
 * send events straight to a third party, around the proxy's cookie/IP
 * stripping, relay guards and project-key check. Anything else → /ingest.
 */
export function sameOriginApiHost(override: string | undefined): string {
  const v = (override ?? "").trim().replace(/\/+$/, "");
  return /^\/[A-Za-z0-9._~\-/]*$/.test(v) && !v.startsWith("//") ? v : INGEST_PREFIX;
}

/** The full init config. Exported so tests can pin the privacy posture. */
export function buildPosthogConfig(env: AnalyticsEnv): Partial<PostHogConfig> {
  return {
    // The same-origin proxy (src/app/ingest/[...path]/route.ts).
    api_host: sameOriginApiHost(env.NEXT_PUBLIC_POSTHOG_HOST),
    ui_host: UI_HOST,
    defaults: "2026-01-30",
    // Nothing in cookies or localStorage: identity, session and super
    // properties live in memory for this page load only.
    persistence: "memory",
    person_profiles: "identified_only",
    // App Router navigations are client-side history changes.
    capture_pageview: "history_change",
    capture_pageleave: true,
    respect_dnt: true,
    // No replay — the screen is full of student content.
    disable_session_recording: true,
    enable_recording_console_log: false,
    // Error messages can quote user content; keep them out.
    capture_exceptions: false,
    // Pageviews + pageleave only. No autocapture (its element chains carry
    // hrefs, relative ones included), no rageclicks, dead clicks, heatmaps
    // or web vitals: product usage comes from backend events instead.
    autocapture: false,
    rageclick: false,
    capture_dead_clicks: false,
    enable_heatmaps: false,
    capture_heatmaps: false,
    capture_performance: false,
    // Belt and braces, should any of the above ever be switched back on.
    mask_all_text: true,
    mask_all_element_attributes: true,
    // Mask the sign-in handoff (and friends) inside every URL posthog-js
    // builds, including the ones before_send only sees nested.
    mask_personal_data_properties: true,
    custom_personal_data_properties: [...PERSONAL_DATA_QUERY_PARAMS],
    // Nothing here routes on the fragment; don't record it.
    disable_capture_url_hashes: true,
    // The app uses no feature flags: no /flags request at init or after
    // identify, so no distinct id or person properties leave that way.
    advanced_disable_flags: true,
    // Each event goes out as it happens (pageviews are rare): no queue for a
    // sign-out to strand — the /ingest proxy 403s once the session cookie is
    // gone, and posthog-js never retries a 4xx.
    request_batching: false,
    // Plain-JSON bodies, so the /ingest proxy can check the project key
    // without decompressing attacker-supplied input.
    disable_compression: true,
    // No remote-UI extension may render anything into the app.
    disable_surveys: true,
    disable_surveys_automatic_display: true,
    disable_product_tours: true,
    disable_conversations: true,
    disable_web_experiments: true,
    opt_in_site_apps: false,
    before_send: gatedBeforeSend,
  };
}

// ── state ───────────────────────────────────────────────────────────────────

/**
 * What the Settings switch shows. The account preference governs both this
 * browser's pageviews AND the backend's mirror (product events, AI-generation
 * records, error reports), so the switch follows the ACCOUNT, not whether
 * this build sends pageviews:
 * - `unknown`: nobody signed in, or their account answer has not arrived yet
 *   — the switch is disabled (it would otherwise guess)
 * - `unreadable`: the last account read failed — disabled; the read is
 *   retried (lib/accountSettings.ts, the UserProvider)
 * - `unset`: the account answered without the field (a backend that predates
 *   it) — nothing starts here (fail closed), but the switch is usable, shown
 *   off, so choosing saves an explicit answer; the field is not re-read
 * - `on` / `off`: the signed-in student's account preference
 * - `on_browser_blocked`: on, but Do Not Track / Global Privacy Control is
 *   set, so this browser sends no pageviews
 * - `on_not_running`: on, pageviews should run here, but posthog-js could
 *   not be loaded or initialised (a blocker, a failed chunk)
 * - `off_unsaved`: the student switched it off, but saving that to their
 *   account failed — off in this browser for this visit only, retry offered
 */
export type AnalyticsState =
  | "unknown"
  | "unreadable"
  | "unset"
  | "on"
  | "on_browser_blocked"
  | "on_not_running"
  | "off"
  | "off_unsaved";

/**
 * #620: the admin `product_analytics` switch (FlagsProvider →
 * setProductAnalyticsFlag). Off until `/api/flags` answers, so pageviews
 * fail closed for the whole page load until the flag is known.
 */
let productAnalyticsFlag = false;

export function setProductAnalyticsFlag(on: boolean): void {
  productAnalyticsFlag = on;
  if (on) ensureStarted();
  notify();
}

let env: AnalyticsEnv = readAnalyticsEnv();
export type PosthogLoader = () => Promise<PostHog>;
const defaultLoader: PosthogLoader = () => import("posthog-js").then((m) => m.default);
let load: PosthogLoader = defaultLoader;

/**
 * The account answer for `currentUser` on this page load: not read yet (or
 * being read), the last read failed, answered without the field, or the
 * preference itself.
 */
let account: "unknown" | "unreadable" | "unset" | "on" | "off" = "unknown";
/** An opt-out whose account save failed: off for this visit only. */
let offUnsaved = false;
let currentUser: string | null = null;
/**
 * Failed account reads for `currentUser` since its last answer. The
 * UserProvider retries a failed read on later shell navigations only while
 * this is under MAX_ACCOUNT_READ_FAILURES — bounded, never a loop. (Settings
 * always reads on mount, so opening it is one more try regardless.)
 */
let failedReads = 0;
export const MAX_ACCOUNT_READ_FAILURES = 3;
/**
 * Bumped by every new account read, sign-out, and a toggle both before AND
 * after its save. An account read issued under an older generation is stale
 * and ignored, so a slow GET /settings can never undo a toggle.
 */
let generation = 0;
/** A Settings toggle whose account save is still in flight. */
let toggleInFlight = false;

/** The live client, once loaded and initialised. */
let client: PostHog | null = null;
let loading: Promise<PostHog | null> | null = null;
/**
 * The last load attempt failed: the chunk was blocked, init threw, or init
 * returned without ever calling `loaded`.
 */
let loadFailed = false;

/** Where capture may happen: the signed-in app shell only. Injectable for tests. */
let isAppRoute: (pathname: string) => boolean = isAppShellRoute;

const listeners = new Set<() => void>();
function notify(): void {
  for (const l of listeners) l();
}

function browserSignalsDoNotTrack(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean; msDoNotTrack?: string };
  const win = (typeof window !== "undefined" ? window : {}) as { doNotTrack?: string };
  return [nav.doNotTrack, nav.msDoNotTrack, win.doNotTrack, nav.globalPrivacyControl].some(
    (v) => v === true || v === "1" || v === "yes",
  );
}

function currentPathIsAppRoute(): boolean {
  return typeof window !== "undefined" && isAppRoute(window.location.pathname);
}

/** Whether this build sends pageviews at all (a key, not local/test mode). */
export function isAnalyticsConfigured(): boolean {
  return analyticsDisabledReason(env) === null;
}

/**
 * Whether this browser would send pageviews for a student whose account says
 * on: configured, the admin flag on, no DNT/GPC. The UserProvider reads the
 * account preference for analytics only while this holds (Settings reads it
 * for itself either way).
 */
export function pageviewsMayRun(): boolean {
  return isAnalyticsConfigured() && productAnalyticsFlag && !browserSignalsDoNotTrack();
}

export function getAnalyticsState(): AnalyticsState {
  if (currentUser === null) return "unknown";
  if (account === "off") return offUnsaved ? "off_unsaved" : "off";
  if (account !== "on") return account;
  if (browserSignalsDoNotTrack()) return "on_browser_blocked";
  if (pageviewsMayRun() && loadFailed && !client) return "on_not_running";
  return "on";
}

/** The server render never knows the browser's state. */
export function getServerAnalyticsState(): AnalyticsState {
  return "unknown";
}

export function subscribeAnalytics(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Capture is allowed right now: admin flag on, configured, no DNT/GPC, account on, on an app route. */
function captureAllowed(): boolean {
  return pageviewsMayRun() && account === "on" && currentPathIsAppRoute();
}

/**
 * `before_send`: drop everything unless capture is allowed, otherwise scrub.
 * The route is read LIVE (window.location) at capture time, so a history
 * change out of the shell — Settings → /privacy — is dropped even though
 * posthog-js fires its `$pageview` before React has re-rendered. Returning
 * null is posthog-js's documented way to discard an event; it runs before
 * the event is queued, so a dropped event never reaches the wire.
 */
export function gatedBeforeSend(event: CaptureResult | null): CaptureResult | null {
  if (!event) return event;
  if (!captureAllowed()) return null;
  // posthog-js links each pageview to the previous one ($prev_pageview_*).
  // If that previous page was outside the shell — its own pageview was
  // dropped above — don't let the next one say where the student had been.
  const props = event.properties as Record<string, unknown> | undefined;
  const prev = props?.$prev_pageview_pathname;
  if (props && typeof prev === "string" && !isAppRoute(prev)) {
    for (const key of Object.keys(props)) if (key.startsWith("$prev_pageview_")) delete props[key];
  }
  return scrubEvent(event);
}

/**
 * Load + init posthog-js once, identifying `currentUser` in the `loaded`
 * hook — which runs before posthog-js captures its initial `$pageview`, so
 * that single pageview is already the student's. Only ever started on an
 * app route with the account on. A failed load is not retried here; the
 * next call (the next time the student enters the shell) tries again — one
 * attempt per call, never a loop.
 *
 * posthog-js runs `loaded` synchronously inside `init`. If `init` returns
 * without having run it (an SDK that declined to initialise, an instance
 * already initialised elsewhere), there is no client to capture with: that is
 * a failed start — `loading` is cleared and the state says `on_not_running`
 * — never a permanent "on" with nothing behind it.
 */
function ensureStarted(): void {
  if (!captureAllowed()) return;
  if (client) {
    identify();
    return;
  }
  if (loading) return;
  loadFailed = false;
  loading = load()
    .then((ph) => {
      ph.init((env.NEXT_PUBLIC_POSTHOG_KEY ?? "").trim(), {
        ...buildPosthogConfig(env),
        loaded: () => {
          client = ph;
          identify();
        },
      });
      if (client !== ph) throw new Error("posthog-js init returned without calling `loaded`");
      loading = null; // settled: `client` is the guard from here on
      notify();
      return ph;
    })
    .catch((err) => {
      // An analytics failure (blocked chunk, extension) must never break the app.
      console.warn("[analytics] PostHog failed to initialise; continuing without it", err);
      loadFailed = true;
      loading = null; // so a later ensureStarted can try again
      notify();
      return null;
    });
}

/** identify(account id) — only while capture is allowed, resetting first if someone else was. */
function identify(): void {
  if (!client || !currentUser || !captureAllowed()) return;
  if (client.get_distinct_id() === currentUser) return;
  if (client.get_property("$user_state") === "identified") client.reset();
  client.identify(currentUser);
}

// ── the account reads' side (lib/accountSettings.ts) ────────────────────────

/**
 * Whether the UserProvider should (re)read `userId`'s account preference: not
 * read yet this page load, or the last read failed and the retry budget
 * (MAX_ACCOUNT_READ_FAILURES) is not spent. An answer — including one
 * without the field (`unset`) — is never re-read.
 */
export function needsAccountRead(userId: string): boolean {
  if (currentUser !== userId || account === "unknown") return true;
  return account === "unreadable" && failedReads < MAX_ACCOUNT_READ_FAILURES;
}

/**
 * `userId`'s account preference is about to be read. Returns the generation
 * to hand back to applyAccountAnalytics / failAccountRead.
 */
export function beginAccountRead(userId: string): number {
  generation += 1;
  if (currentUser !== userId) {
    account = "unknown";
    offUnsaved = false;
    failedReads = 0;
  } else if (account === "unreadable") {
    account = "unknown"; // retrying: "loading", not "failed"
  }
  currentUser = userId;
  notify();
  return generation;
}

/**
 * The account answered. Ignored if anything (a toggle, a sign-out, another
 * read) happened since `gen` was issued. Only an explicit `false` turns
 * pageviews on; `true` is off; a missing field is `unset` — off here, but an
 * answer (the switch is usable and it is not re-read).
 */
export function applyAccountAnalytics(gen: number, userId: string, optOut: unknown): void {
  if (gen !== generation || userId !== currentUser) return;
  account = optOut === false ? "on" : optOut === true ? "off" : "unset";
  offUnsaved = false;
  failedReads = 0;
  ensureStarted();
  notify();
}

/** The read issued as `gen` failed: `unreadable`, and one more spent retry. */
export function failAccountRead(gen: number, userId: string): void {
  if (gen !== generation || userId !== currentUser) return;
  account = "unreadable";
  failedReads += 1;
  notify();
}

/** Back on an app route with the answer already known: start if not running. */
export function resumeAnalytics(): void {
  ensureStarted();
  notify();
}

/** Nobody is signed in (anonymous page, sign-out, dead session): off. */
export function stopAnalytics(): void {
  generation += 1;
  account = "unknown";
  offUnsaved = false;
  failedReads = 0;
  currentUser = null;
  // Forget the in-memory identity, so a later sign-in on this same page is a
  // different person, never merged. Nothing persisted to forget.
  if (client && client.get_property("$user_state") === "identified") client.reset();
  notify();
}

// ── the Settings switch's side ──────────────────────────────────────────────

/**
 * A choice made on the Settings switch. It is saved to the account whether
 * or not this browser sends pageviews (no key, the admin flag off, DNT/GPC):
 * the same `analytics_opt_out` governs the backend mirror. Opting OUT stops
 * capture here at once, then saves `analytics_opt_out: true`; if that save
 * fails capture stays off here for this visit (`off_unsaved`, retry offered).
 * Opting IN saves `false` FIRST and only then starts capture (where it may
 * run) — and reports `saved` whenever the save succeeded, but applies it only
 * if the same student is still signed in. Refused until the account has
 * answered (the switch is disabled then). One toggle at a time (`busy`
 * otherwise); the generation is bumped before and after the save, so no
 * account read begun before or during the toggle can overwrite its result.
 */
export async function chooseAnalytics(
  userId: string,
  enabled: boolean,
  save: (optOut: boolean) => Promise<unknown>,
): Promise<"saved" | "failed" | "busy"> {
  if (userId !== currentUser) return "failed";
  if (account === "unknown" || account === "unreadable") return "failed";
  if (toggleInFlight) return "busy";
  toggleInFlight = true;
  generation += 1;
  notify();
  try {
    if (!enabled) {
      account = "off";
      offUnsaved = false;
      notify();
      try {
        await save(true);
        return "saved";
      } catch {
        if (currentUser === userId) offUnsaved = true; // off for this visit only
        return "failed";
      }
    }
    try {
      await save(false);
    } catch {
      return "failed";
    }
    if (currentUser === userId) {
      account = "on";
      offUnsaved = false;
      ensureStarted();
    }
    return "saved";
  } finally {
    generation += 1;
    toggleInFlight = false;
    notify();
  }
}

/** Test-only: forget module state and swap the env / loader / route rule. */
export function __resetAnalyticsForTests(
  opts: { env?: AnalyticsEnv; load?: PosthogLoader; isAppRoute?: (pathname: string) => boolean } = {},
): void {
  env = opts.env ?? {};
  load = opts.load ?? defaultLoader;
  isAppRoute = opts.isAppRoute ?? isAppShellRoute;
  productAnalyticsFlag = false;
  account = "unknown";
  offUnsaved = false;
  failedReads = 0;
  currentUser = null;
  generation = 0;
  toggleInFlight = false;
  client = null;
  loading = null;
  loadFailed = false;
  listeners.clear();
}

/** Test-only: resolves once a pending posthog-js load has finished. */
export async function __analyticsLoadedForTests(): Promise<PostHog | null> {
  return loading ? loading : client;
}
