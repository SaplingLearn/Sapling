/**
 * Product analytics (PostHog) — the ONLY module that talks to posthog-js.
 *
 * The model is deliberately small:
 *
 * - **Only signed-in students who have not opted out are captured.** posthog-js
 *   is not even loaded on public/marketing pages, `/auth/*`, or for anyone
 *   signed out. For a signed-in student the UserProvider reads their account
 *   preference (`user_settings.analytics_opt_out`); only an explicit `false`
 *   loads and starts posthog-js. `true`, a missing field, or a failed read
 *   leaves it off for the page load (fail closed).
 * - **The account flag is the single source of truth.** Nothing about the
 *   choice is stored in the browser — not by us, and not by posthog-js
 *   (`persistence: 'memory'`, and posthog-js's own opt-out/opt-in, which
 *   would write localStorage, is never called). Every page load starts from
 *   nothing and asks the account again. The price is no session continuity
 *   across full page loads; that trade is accepted.
 * - **A capture gate** (`gatedBeforeSend`) drops every event unless the
 *   current state is `on`, so opting out mid-page stops capture at once.
 * - **Do Not Track / Global Privacy Control means off**, always.
 * - **Pseudonymous.** `identify` carries the user's UUID and nothing else — no
 *   name, email or person properties — and runs in posthog-js's `loaded` hook,
 *   before its initial `$pageview`, so that one pageview is already the
 *   student's.
 * - **No content.** Autocapture records that a click happened, never what the
 *   element said: `mask_all_text` + `mask_all_element_attributes`. Session
 *   recording, exception autocapture and copied-text capture are off.
 * - **No credentials in URLs.** The `/auth/callback` handoff params are masked
 *   by posthog-js AT THE SOURCE (`custom_personal_data_properties`), and
 *   `before_send` strips every query string and fragment from every URL
 *   value, recursively (heatmap URL keys, web-vitals metrics), as defence in
 *   depth.
 * - **Nothing but events on the wire.** Feature flags are off
 *   (`advanced_disable_flags` — the app uses none; posthog-js then skips its
 *   remote config too), and every remote-UI extension (surveys, product
 *   tours, conversations, web experiments, site apps) is disabled.
 * - **No client IP, no geolocation.** The `/ingest` proxy never forwards the
 *   browser's IP and every event carries `$geoip_disable`; the PostHog
 *   project setting "Discard client IP data" must stay ON
 *   (docs/frontend-audit/07-integrations.md).
 * - **Same-origin transport.** `api_host` is `/ingest`, served by
 *   `src/app/ingest/[...path]/route.ts`, which forwards to PostHog US without
 *   the user's cookies.
 * - **Inert unless configured.** No `NEXT_PUBLIC_POSTHOG_KEY`, local UI mode
 *   (`NEXT_PUBLIC_LOCAL_MODE`) or the E2E/test build (`NEXT_PUBLIC_TEST_MODE`)
 *   → none of the above ever runs.
 *
 * NEXT_PUBLIC_* values are inlined at BUILD time, so each one is read with a
 * literal `process.env.NEXT_PUBLIC_…` expression below.
 */
import type { CaptureResult, PostHog, PostHogConfig } from "posthog-js";

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

/** The same-origin proxy path (src/app/ingest/[...path]/route.ts). */
export const DEFAULT_API_HOST = INGEST_PREFIX;
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
  if (typeof value !== "string" || !/^https?:\/\//i.test(value)) return value;
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
 * Strip URL queries from `value` and from everything nested in it — values
 * AND object keys, because `$heatmap_data` is keyed by page URL. Mutates
 * objects/arrays in place. When two keys collapse onto the same URL their
 * array values are merged, so neither page's data is lost.
 */
export function scrubValue(value: unknown, depth = 0): unknown {
  if (typeof value === "string") return stripUrlQuery(value);
  if (depth >= MAX_SCRUB_DEPTH) return value;
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) value[i] = scrubValue(value[i], depth + 1);
    return value;
  }
  if (!isPlainObject(value)) return value;
  for (const key of Object.keys(value)) {
    const scrubbed = scrubValue(value[key], depth + 1);
    const cleanKey = stripUrlQuery(key) as string;
    if (cleanKey === key) {
      value[key] = scrubbed;
      continue;
    }
    delete value[key];
    const existing = value[cleanKey];
    value[cleanKey] =
      Array.isArray(existing) && Array.isArray(scrubbed) ? [...existing, ...scrubbed] : scrubbed;
  }
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

/** The full init config. Exported so tests can pin the privacy posture. */
export function buildPosthogConfig(env: AnalyticsEnv): Partial<PostHogConfig> {
  return {
    api_host: (env.NEXT_PUBLIC_POSTHOG_HOST ?? "").trim() || DEFAULT_API_HOST,
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
    // Autocapture stays on, but content-free.
    autocapture: { capture_copied_text: false },
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
 * What the Settings switch shows, and what the gate lets through:
 * - `unavailable`: this build runs no analytics (no key, local/test mode)
 * - `browser_blocked`: Do Not Track / Global Privacy Control is on
 * - `unknown`: nobody signed in, or their account answer has not arrived (or
 *   the read failed) — nothing is captured, the switch is disabled
 * - `on` / `off`: the signed-in student's account preference
 */
export type AnalyticsState = "unavailable" | "browser_blocked" | "unknown" | "on" | "off";

let env: AnalyticsEnv = readAnalyticsEnv();
export type PosthogLoader = () => Promise<PostHog>;
const defaultLoader: PosthogLoader = () => import("posthog-js").then((m) => m.default);
let load: PosthogLoader = defaultLoader;

/** The account answer for `currentUser` on this page load. */
let account: "unknown" | "on" | "off" = "unknown";
let currentUser: string | null = null;
/**
 * Bumped by every new account read, toggle and sign-out. An account read
 * that started under an older generation is stale and ignored, so a slow
 * GET /settings can never undo a toggle made after it started.
 */
let generation = 0;
/** A Settings toggle whose account save is still in flight. */
let toggleInFlight = false;

/** The live client, once loaded and initialised. */
let client: PostHog | null = null;
let loading: Promise<PostHog | null> | null = null;

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

/**
 * Whether this build runs analytics at all (a key, not local/test mode).
 * Callers use it to skip work — like reading the account preference — that
 * only matters when it does.
 */
export function isAnalyticsConfigured(): boolean {
  return analyticsDisabledReason(env) === null;
}

export function getAnalyticsState(): AnalyticsState {
  if (!isAnalyticsConfigured()) return "unavailable";
  if (browserSignalsDoNotTrack()) return "browser_blocked";
  return account;
}

/** The server render never knows the browser's state. */
export function getServerAnalyticsState(): AnalyticsState {
  return "unavailable";
}

export function subscribeAnalytics(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * `before_send`: drop everything unless the state is `on`, otherwise scrub.
 * Returning null is posthog-js's documented way to discard an event; it runs
 * before the event is queued, so a dropped event never reaches the wire.
 */
export function gatedBeforeSend(event: CaptureResult | null): CaptureResult | null {
  if (!event) return event;
  if (getAnalyticsState() !== "on") return null;
  return scrubEvent(event);
}

/**
 * Load + init posthog-js once, identifying `currentUser` in the `loaded`
 * hook — which runs before posthog-js captures its initial `$pageview`, so
 * that single pageview is already the student's.
 */
function ensureStarted(): void {
  if (client) {
    identify();
    return;
  }
  if (loading) return;
  loading = load()
    .then((ph) => {
      ph.init((env.NEXT_PUBLIC_POSTHOG_KEY ?? "").trim(), {
        ...buildPosthogConfig(env),
        loaded: () => {
          client = ph;
          identify();
        },
      });
      client = ph;
      return ph;
    })
    .catch((err) => {
      // An analytics failure (blocked chunk, extension) must never break the app.
      console.warn("[analytics] PostHog failed to initialise; continuing without it", err);
      return null;
    });
}

/** identify(uuid) — only while `on`, and resetting first if someone else was. */
function identify(): void {
  if (!client || !currentUser || getAnalyticsState() !== "on") return;
  const current = client.get_distinct_id();
  if (current === currentUser) return;
  if (client.get_property("$user_state") === "identified") client.reset();
  client.identify(currentUser);
}

// ── the UserProvider's side ─────────────────────────────────────────────────

/**
 * A signed-in student is here and their account preference is about to be
 * read. Returns the generation to hand back to applyAccountAnalytics.
 */
export function beginAccountRead(userId: string): number {
  generation += 1;
  if (currentUser !== userId) account = "unknown";
  currentUser = userId;
  notify();
  return generation;
}

/**
 * The account answered. Ignored if anything (a toggle, a sign-out, another
 * read) happened since `gen` was issued. Only an explicit `false` turns
 * analytics on; `true` is off; anything else (a missing field) stays unknown.
 */
export function applyAccountAnalytics(gen: number, userId: string, optOut: unknown): void {
  if (gen !== generation || userId !== currentUser) return;
  account = optOut === false ? "on" : optOut === true ? "off" : "unknown";
  if (account === "on" && getAnalyticsState() === "on") ensureStarted();
  notify();
}

/** Nobody is signed in (anonymous page, sign-out, dead session): off. */
export function stopAnalytics(): void {
  generation += 1;
  account = "unknown";
  currentUser = null;
  // Forget the in-memory identity, so a later sign-in on this same page is a
  // different person, never merged. Nothing persisted to forget.
  if (client && client.get_property("$user_state") === "identified") client.reset();
  notify();
}

// ── the Settings switch's side ──────────────────────────────────────────────

/**
 * A choice made on the Settings switch. Opting OUT stops capture at once,
 * then saves `analytics_opt_out: true`; if that save fails capture stays
 * off for this page load. Opting IN saves `false` FIRST and only then
 * starts capture. One toggle at a time (`busy` otherwise), and every toggle
 * invalidates account reads already in flight.
 */
export async function chooseAnalytics(
  userId: string,
  enabled: boolean,
  save: (optOut: boolean) => Promise<unknown>,
): Promise<"saved" | "failed" | "busy"> {
  if (!isAnalyticsConfigured() || browserSignalsDoNotTrack() || userId !== currentUser) return "failed";
  if (account === "unknown") return "failed";
  if (toggleInFlight) return "busy";
  toggleInFlight = true;
  generation += 1;
  notify();
  try {
    if (!enabled) {
      account = "off";
      notify();
      try {
        await save(true);
        return "saved";
      } catch {
        return "failed"; // stays off for this page load
      }
    }
    try {
      await save(false);
    } catch {
      return "failed";
    }
    if (userId !== currentUser) return "failed"; // signed out meanwhile
    account = "on";
    ensureStarted();
    return "saved";
  } finally {
    toggleInFlight = false;
    notify();
  }
}

/** Test-only: forget module state and swap the env / loader. */
export function __resetAnalyticsForTests(
  opts: { env?: AnalyticsEnv; load?: PosthogLoader } = {},
): void {
  env = opts.env ?? {};
  load = opts.load ?? defaultLoader;
  account = "unknown";
  currentUser = null;
  generation = 0;
  toggleInFlight = false;
  client = null;
  loading = null;
  listeners.clear();
}

/** Test-only: resolves once a pending posthog-js load has finished. */
export async function __analyticsLoadedForTests(): Promise<PostHog | null> {
  return loading ? loading : client;
}
