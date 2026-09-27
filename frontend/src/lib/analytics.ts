/**
 * Product analytics (PostHog) — the ONLY module that talks to posthog-js.
 *
 * Every other file goes through the helpers below, so the privacy posture
 * lives in one place:
 *
 * - **Inert unless configured.** No `NEXT_PUBLIC_POSTHOG_KEY` → posthog-js is
 *   never even loaded (it is a lazy `import()`), so nothing is sent. The same
 *   holds in local UI mode (`NEXT_PUBLIC_LOCAL_MODE`) and in the E2E/test
 *   build (`NEXT_PUBLIC_TEST_MODE`, baked by `npm run build:test`), which must
 *   send nothing even if a key leaks in through a `.env*` file.
 * - **Pseudonymous.** `identify` carries the user's UUID and nothing else — no
 *   name, email or person properties. `person_profiles: 'identified_only'`
 *   means anonymous visitors never get a person profile at all.
 * - **No content.** Autocapture records that a click happened, never what the
 *   element said: `mask_all_text` + `mask_all_element_attributes` drop the text
 *   and attributes (notes, chat messages, document names, hrefs) the UI
 *   renders. Session recording, exception autocapture and copied-text capture
 *   are off.
 * - **No credentials in URLs.** `/auth/callback?auth_token=…&user_id=…&avatar=…`
 *   is the sign-in handoff, so its parameters are masked AT THE SOURCE via
 *   `custom_personal_data_properties`. That reaches what `before_send` never
 *   sees (the `/flags` request body) and what it only sees nested (heatmap
 *   URL keys, web-vitals metrics), as well as `$current_url` and
 *   `$initial_current_url`. `before_send` then strips every query string and
 *   fragment from every URL value, recursively, as defence in depth.
 * - **No client IP, no geolocation.** The proxy never forwards the browser's
 *   IP (PostHog only ever sees the Worker's), posthog-js has no IP switch of
 *   its own (its `ip` option is a documented no-op), and every event carries
 *   `$geoip_disable` so ingestion skips GeoIP enrichment. The PostHog project
 *   setting "Discard client IP data" must stay ON — see
 *   docs/frontend-audit/07-integrations.md.
 * - **The opt-out follows the account.** `user_settings.analytics_opt_out` is
 *   applied on sign-in (`applyAccountAnalyticsPreference`) before `identify`,
 *   so an opt-out made on one browser holds on every other.
 * - **Same-origin transport.** `api_host` is `/ingest`, served by the route
 *   handler in `src/app/ingest/[...path]/route.ts`, which forwards to PostHog
 *   US without the user's cookies (see that file for why this is not a
 *   next.config rewrite).
 *
 * NEXT_PUBLIC_* values are inlined at BUILD time, so each one is read with a
 * literal `process.env.NEXT_PUBLIC_…` expression below — a dynamic lookup would
 * not be inlined and would read `undefined` in the browser.
 */
import type { CaptureResult, PostHog, PostHogConfig } from "posthog-js";

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
export const DEFAULT_API_HOST = "/ingest";
/** PostHog US app — where toolbar / "view in PostHog" links point. */
export const UI_HOST = "https://us.posthog.com";

function truthyFlag(v: string | undefined): boolean {
  const s = (v ?? "").trim().toLowerCase();
  return s === "1" || s === "true";
}

/** Why analytics is off, or null when it should initialise. */
export function analyticsDisabledReason(
  env: AnalyticsEnv,
): "no_key" | "local_mode" | "test_mode" | null {
  if (truthyFlag(env.NEXT_PUBLIC_TEST_MODE)) return "test_mode";
  if (truthyFlag(env.NEXT_PUBLIC_LOCAL_MODE)) return "local_mode";
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
    // builds, including the ones before_send cannot reach — see the header.
    mask_personal_data_properties: true,
    custom_personal_data_properties: [...PERSONAL_DATA_QUERY_PARAMS],
    // Nothing here routes on the fragment; don't record it.
    disable_capture_url_hashes: true,
    before_send: scrubEvent,
  };
}

// ── module state ────────────────────────────────────────────────────────────

/** The live client once initialised; null while inert or still loading. */
let client: PostHog | null = null;
let starting = false;
/**
 * An identity requested before the client finished loading: a user id to
 * identify, `null` for "reset", `undefined` for nothing pending. The
 * UserProvider hydrates from localStorage on mount, which can beat the lazy
 * chunk, so the latest request is replayed once the client is ready.
 */
let pendingIdentity: string | null | undefined;
/** An account-level opt-out that arrived before the client finished loading. */
let pendingAccountOptOut = false;

export type PosthogLoader = () => Promise<PostHog>;
const defaultLoader: PosthogLoader = () => import("posthog-js").then((m) => m.default);

/**
 * Initialise posthog-js iff the build is configured for it. Idempotent.
 * Resolves to whether analytics is active. Called from instrumentation-client.ts.
 */
export async function initAnalytics(
  env: AnalyticsEnv = readAnalyticsEnv(),
  load: PosthogLoader = defaultLoader,
): Promise<boolean> {
  if (client) return true;
  if (starting) return false;
  if (typeof window === "undefined") return false;
  if (analyticsDisabledReason(env) !== null) return false;
  starting = true;
  try {
    const ph = await load();
    ph.init((env.NEXT_PUBLIC_POSTHOG_KEY ?? "").trim(), buildPosthogConfig(env));
    client = ph;
  } catch (err) {
    // An analytics failure (blocked chunk, extension) must never break the app.
    console.warn("[analytics] PostHog failed to initialise; continuing without it", err);
    return false;
  } finally {
    starting = false;
  }
  // The account's opt-out first, so a replayed identify never goes out for a
  // student who opted out on another browser.
  if (pendingAccountOptOut) applyAccountAnalyticsPreference(true);
  pendingAccountOptOut = false;
  const pending = pendingIdentity;
  pendingIdentity = undefined;
  if (pending === null) resetAnalytics();
  else if (pending) identifyUser(pending);
  notify();
  return true;
}

export function isAnalyticsActive(): boolean {
  return client !== null;
}

/**
 * Whether this build runs analytics at all (a key, not local/test mode) —
 * true before posthog-js has finished loading. Callers use it to skip work,
 * like fetching the account preference, that only matters when it does.
 */
export function isAnalyticsConfigured(env: AnalyticsEnv = readAnalyticsEnv()): boolean {
  return analyticsDisabledReason(env) === null;
}

/**
 * Associate subsequent events with the user's UUID — and nothing else.
 *
 * posthog-js's `identify()` on a browser already identified as someone else
 * does not switch people: it links the new id to the old one and MERGES the
 * two students into a single person. That happens whenever one browser moves
 * between accounts without `resetAnalytics()` in between (a stale
 * localStorage identity replaced by a fresh sign-in, a session that expired
 * server-side). So a different identified user is reset first — with the
 * opt-out carried across, exactly as sign-out does.
 */
export function identifyUser(userId: string): void {
  if (!userId) return;
  if (!client) {
    if (starting) pendingIdentity = userId;
    return;
  }
  if (client.get_distinct_id() === userId) return;
  if (client.get_property("$user_state") === "identified") resetAnalytics();
  client.identify(userId);
}

/**
 * Apply the account-level preference (`user_settings.analytics_opt_out`) to
 * this browser. Only an opt-out is applied: `false` — or the field missing,
 * as it is on a backend that predates it — leaves this browser's own choice
 * alone, so a local opt-out always wins and the account can only ever turn
 * collection OFF, never silently back on.
 */
export function applyAccountAnalyticsPreference(optOut: unknown): void {
  if (optOut !== true) return;
  if (!client) {
    if (starting) pendingAccountOptOut = true;
    return;
  }
  if (client.has_opted_out_capturing()) return;
  client.opt_out_capturing();
  notify();
}

/**
 * Forget the identity (sign-out, account deletion, dead session).
 *
 * posthog-js's `reset()` also wipes the stored consent, which would silently
 * turn a student's opt-out back ON at sign-out — so the opt-out is carried
 * across the reset explicitly.
 */
export function resetAnalytics(): void {
  if (!client) {
    if (starting) pendingIdentity = null;
    return;
  }
  const optedOut = client.has_opted_out_capturing();
  client.reset();
  if (optedOut) client.opt_out_capturing();
}

// ── opt-out state, as a tiny external store for useSyncExternalStore ────────

/**
 * - `unavailable`: not initialised (no key, local/test build, or server render)
 * - `browser_blocked`: Do Not Track / Global Privacy Control is on; posthog-js
 *   honours it (`respect_dnt`) regardless of the in-app choice
 * - `on` / `off`: the student's in-app choice for this browser
 */
export type AnalyticsState = "unavailable" | "browser_blocked" | "on" | "off";

function browserSignalsDoNotTrack(): boolean {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean; msDoNotTrack?: string };
  const win = (typeof window !== "undefined" ? window : {}) as { doNotTrack?: string };
  return [nav.doNotTrack, nav.msDoNotTrack, win.doNotTrack, nav.globalPrivacyControl].some(
    (v) => v === true || v === "1" || v === "yes",
  );
}

const listeners = new Set<() => void>();
function notify(): void {
  for (const l of listeners) l();
}

export function subscribeAnalytics(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getAnalyticsState(): AnalyticsState {
  if (!client) return "unavailable";
  if (browserSignalsDoNotTrack()) return "browser_blocked";
  return client.has_opted_out_capturing() ? "off" : "on";
}

/** The server render never knows the browser's consent state. */
export function getServerAnalyticsState(): AnalyticsState {
  return "unavailable";
}

/**
 * This browser's choice, persisted by posthog-js (its own consent storage).
 * Settings also PATCHes it to the account (`analytics_opt_out`) so it follows
 * the student to other browsers — see applyAccountAnalyticsPreference.
 */
export function setAnalyticsEnabled(enabled: boolean): void {
  if (!client) return;
  if (enabled) client.opt_in_capturing();
  else client.opt_out_capturing();
  notify();
}

/** Test-only: forget module state between cases. */
export function __resetAnalyticsForTests(): void {
  client = null;
  starting = false;
  pendingIdentity = undefined;
  pendingAccountOptOut = false;
  listeners.clear();
}
