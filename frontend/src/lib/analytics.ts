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
 *   are off. `before_send` strips query strings and fragments from every URL
 *   property, because `/auth/callback?auth_token=…&avatar=…` would otherwise
 *   ship the sign-in handoff token on the first pageview.
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
 * Strip `?query` and `#fragment` from an absolute URL; anything else is
 * returned unchanged. Query strings here can carry the OAuth handoff token
 * (`/auth/callback?auth_token=…`) and the Google avatar URL.
 */
export function stripUrlQuery(value: unknown): unknown {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value)) return value;
  const cut = value.search(/[?#]/);
  return cut === -1 ? value : value.slice(0, cut);
}

function scrubProps(props: Record<string, unknown> | undefined): void {
  if (!props) return;
  for (const key of Object.keys(props)) {
    props[key] = stripUrlQuery(props[key]);
  }
}

/** `before_send` hook: remove query strings/fragments from every URL value. */
export function scrubEvent(event: CaptureResult | null): CaptureResult | null {
  if (!event) return event;
  scrubProps(event.properties as Record<string, unknown> | undefined);
  scrubProps(event.$set as Record<string, unknown> | undefined);
  scrubProps(event.$set_once as Record<string, unknown> | undefined);
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
    mask_personal_data_properties: true,
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

/** Associate subsequent events with the user's UUID — and nothing else. */
export function identifyUser(userId: string): void {
  if (!userId) return;
  if (!client) {
    if (starting) pendingIdentity = userId;
    return;
  }
  if (client.get_distinct_id() === userId) return;
  client.identify(userId);
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

/** Persisted per browser by posthog-js (its own consent cookie). */
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
  listeners.clear();
}
