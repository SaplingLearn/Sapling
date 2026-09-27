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
 *   `custom_personal_data_properties` — in `$current_url`,
 *   `$initial_current_url`, and what `before_send` only sees nested (heatmap
 *   URL keys, web-vitals metrics). `before_send` then strips every query
 *   string and fragment from every URL value, recursively, as defence in
 *   depth.
 * - **Nothing but events and remote config on the wire.** Feature flags are
 *   off (`advanced_disable_flags` — the app uses none, so no `/flags` request
 *   ever carries a distinct id or person properties), and so is every
 *   remote-UI extension: surveys, product tours, conversations, web
 *   experiments, site apps. With flags off posthog-js also skips its remote
 *   config fetch, so the only requests left are the gated events (observed
 *   in Chromium against the OpenNext worker).
 * - **No client IP, no geolocation.** The proxy never forwards the browser's
 *   IP (PostHog only ever sees the Worker's), posthog-js has no IP switch of
 *   its own (its `ip` option is a documented no-op), and every event carries
 *   `$geoip_disable` so ingestion skips GeoIP enrichment. The PostHog project
 *   setting "Discard client IP data" must stay ON — see
 *   docs/frontend-audit/07-integrations.md.
 * - **Nothing is captured until we know whose page this is.** Every event
 *   goes through a capture gate (`gatedBeforeSend`) that starts CLOSED on
 *   page load. The UserProvider opens it once identity settles: straight away
 *   for an anonymous visitor (`releaseAnonymousAnalytics`); for a signed-in
 *   student only after their account preference (`user_settings.
 *   analytics_opt_out`) has been read and applied (`resolveAccountAnalytics`),
 *   so an opt-out made on one browser holds on every other — even on a new
 *   device's first page. If that read fails the gate stays shut for the rest
 *   of the page load (fail closed). The page's initial `$pageview`, dropped
 *   while the gate was shut, is re-sent when it opens.
 * - **The opt-out is decided per student, here.** The account value
 *   (`analytics_opt_out`) is authoritative and re-derived on every page load;
 *   it is never written down locally. The only local record
 *   (`OPT_OUT_RECORDS_KEY`) is a per-user-id note of an opt-out the student
 *   made in THIS browser — `pending` until the account has it, `saved`
 *   after — which covers the window before the account answers, a backend
 *   that predates the column, and a save that failed. An account `false`
 *   supersedes a `saved` note (so an opt-in on laptop B reaches laptop A), and
 *   no student ever inherits another's: on a shared browser the next
 *   sign-in re-derives consent for THAT user. posthog-js's own consent is
 *   only ever set to match this decision, and Do Not Track / GPC (which every
 *   posthog-js consent getter folds in) is never mistaken for, or stored as,
 *   the student's choice. An opted-out student is never `identify`d.
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

/**
 * The full init config. Exported so tests can pin the privacy posture.
 * `optOutByDefault` is whether the signed-in student this browser remembers
 * has a recorded opt-out here — applied before init's first capture.
 */
export function buildPosthogConfig(
  env: AnalyticsEnv,
  { optOutByDefault = false }: { optOutByDefault?: boolean } = {},
): Partial<PostHogConfig> {
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
    opt_out_capturing_by_default: optOutByDefault,
    before_send: gatedBeforeSend,
  };
}

// ── module state ────────────────────────────────────────────────────────────

/** The live client once initialised; null while inert or still loading. */
let client: PostHog | null = null;
let starting = false;
/** A sign-out (`resetAnalytics`) requested before the client finished loading. */
let pendingReset = false;
/** An account answer that arrived before the client finished loading. */
let pendingResolution: { userId: string; account: unknown } | null = null;

/** The signed-in student consent was last resolved for, and the decision. */
let currentUser: string | null = null;
let currentOptOut = false;

/**
 * The capture gate (see the header). Closed from page load until the
 * UserProvider has settled who is here — and, for a signed-in student, what
 * their preference is. `droppedPageview` / `pageviewSent` let the page's
 * pageview be re-sent once it opens.
 */
let gateOpen = false;
let droppedPageview = false;
let pageviewSent = false;

/** A Settings choice whose account save is still in flight. */
let choiceInFlight = false;

/**
 * `before_send`: drop everything while the gate is closed, otherwise scrub.
 * Returning null is posthog-js's documented way to discard an event, and it
 * runs before the event is queued, so a dropped event never reaches the wire.
 */
export function gatedBeforeSend(event: CaptureResult | null): CaptureResult | null {
  if (!event) return event;
  if (!gateOpen) {
    if (event.event === "$pageview") droppedPageview = true;
    return null;
  }
  if (event.event === "$pageview") pageviewSent = true;
  return scrubEvent(event);
}

function openGate(): void {
  gateOpen = true;
  if (!client || currentOptOut) return;
  if (!droppedPageview && pageviewSent) return;
  droppedPageview = false;
  // A no-op when opted out (or under DNT/GPC): posthog-js checks consent.
  client.capture("$pageview");
}

// ── the per-user local record ───────────────────────────────────────────────

/**
 * localStorage: `{ [userId]: "pending" | "saved" }` — opt-outs a student made
 * in THIS browser. `pending` until the account save succeeds. Never written
 * for an account-derived opt-out (that is re-derived from the account every
 * load). Storage failures (private mode, blocked site data) read as empty.
 */
export const OPT_OUT_RECORDS_KEY = "sapling_analytics_opt_outs";
type LocalRecord = "pending" | "saved";

function readRecords(): Record<string, LocalRecord> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(OPT_OUT_RECORDS_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, LocalRecord>) : {};
  } catch {
    return {};
  }
}

function writeRecord(userId: string, value: LocalRecord | null): void {
  try {
    const records = readRecords();
    if (value) records[userId] = value;
    else delete records[userId];
    window.localStorage.setItem(OPT_OUT_RECORDS_KEY, JSON.stringify(records));
  } catch {
    // best effort — see OPT_OUT_RECORDS_KEY
  }
}

/** The user id the UserProvider will hydrate from (its localStorage copy). */
function rememberedUserId(): string | null {
  try {
    const saved = JSON.parse(window.localStorage.getItem("sapling_user") ?? "null") as { id?: unknown } | null;
    return typeof saved?.id === "string" && saved.id ? saved.id : null;
  } catch {
    return null;
  }
}

/** Whether the student this browser remembers opted out here. Read at init. */
export function recordedOptOutForRememberedUser(): boolean {
  const id = rememberedUserId();
  return id !== null && readRecords()[id] !== undefined;
}

/**
 * The decision for `userId` given the account's answer — the one place the
 * rules live:
 * - account `true` → out (not recorded locally; re-derived next load);
 * - account `false` → in, and a `saved` note is superseded (cleared) — unless
 *   the note is still `pending`: an opt-out made here that the account never
 *   received stands;
 * - no answer (a backend without the column) → this browser's note decides.
 */
function decideOptOut(userId: string, account: unknown): boolean {
  const note = readRecords()[userId];
  if (account === true) return true;
  if (account === false) {
    if (note === "pending") return true;
    if (note) writeRecord(userId, null);
    return false;
  }
  return note !== undefined;
}

/** Make posthog-js's own consent match the decision (it is browser-wide). */
function applyConsent(optOut: boolean): void {
  if (!client) return;
  if (optOut) {
    client.opt_out_capturing();
  } else if (client.get_explicit_consent_status() !== "granted") {
    // No `$opt_in` event: this is a re-derivation, not a new choice.
    client.opt_in_capturing({ captureEventName: false });
  }
}

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
    ph.init(
      (env.NEXT_PUBLIC_POSTHOG_KEY ?? "").trim(),
      buildPosthogConfig(env, { optOutByDefault: recordedOptOutForRememberedUser() }),
    );
    client = ph;
  } catch (err) {
    // An analytics failure (blocked chunk, extension) must never break the app.
    console.warn("[analytics] PostHog failed to initialise; continuing without it", err);
    return false;
  } finally {
    starting = false;
  }
  if (pendingReset) {
    pendingReset = false;
    resetAnalytics();
  }
  const pending = pendingResolution;
  pendingResolution = null;
  if (pending) resolveAccountAnalytics(pending.userId, pending.account);
  else if (gateOpen) openGate(); // re-send a pageview swallowed during init
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
 * Never for an opted-out student (nor under DNT/GPC): `identify` is itself an
 * event, and it links this browser's history to the account.
 *
 * posthog-js's `identify()` on a browser already identified as someone else
 * does not switch people: it links the new id to the old one and MERGES the
 * two students into a single person. So a different identified user is reset
 * first.
 */
export function identifyUser(userId: string): void {
  if (!userId || !client) return;
  if (currentOptOut || client.has_opted_out_capturing()) return;
  if (client.get_distinct_id() === userId) return;
  if (client.get_property("$user_state") === "identified") resetAnalytics();
  client.identify(userId);
}

/**
 * Close the capture gate: a signed-in student has appeared and their
 * preference is not known yet. Nothing is sent until resolveAccountAnalytics.
 * If that never comes (the settings read failed), nothing is sent for the
 * rest of this page load.
 */
export function holdAnalytics(): void {
  gateOpen = false;
}

/** Open the gate for a visitor with no session: nothing to wait for. */
export function releaseAnonymousAnalytics(): void {
  currentUser = null;
  openGate();
}

/**
 * The signed-in student's account preference (`user_settings.
 * analytics_opt_out`) has arrived: decide (decideOptOut), make posthog-js
 * match, open the gate, and identify only if they are not opted out. A
 * different student previously identified on this browser is reset first,
 * so nothing — identity or consent — carries over between them.
 */
export function resolveAccountAnalytics(userId: string, account: unknown): void {
  if (!client) {
    // The gate stays shut until initAnalytics replays this.
    if (starting) pendingResolution = { userId, account };
    return;
  }
  const optOut = decideOptOut(userId, account);
  if (client.get_distinct_id() !== userId && client.get_property("$user_state") === "identified") {
    client.reset();
  }
  currentUser = userId;
  currentOptOut = optOut;
  applyConsent(optOut);
  if (optOut) {
    droppedPageview = false; // an opted-out student's pageview stays dropped
    gateOpen = true; // nothing passes consent now
  } else {
    // Open BEFORE identifying: `$identify` is an event too.
    gateOpen = true;
    identifyUser(userId);
    openGate(); // then re-send the pageview swallowed while waiting
  }
  notify();
}

/**
 * A choice made on the Settings switch. Opting OUT is local-first: this
 * browser stops at once (recorded `pending`), then `save(true)` tells the
 * account (`saved` on success). Opting IN is account-first: `save(false)`
 * must succeed before capture resumes, so the account and this browser can
 * never disagree. One choice at a time: a second call while one is in flight
 * is ignored (`busy`).
 */
export async function chooseAnalytics(
  userId: string,
  enabled: boolean,
  save: (optOut: boolean) => Promise<unknown>,
): Promise<"saved" | "local_only" | "failed" | "busy"> {
  if (!client || !userId) return "failed";
  if (choiceInFlight) return "busy";
  choiceInFlight = true;
  try {
    if (!enabled) {
      writeRecord(userId, "pending");
      if (currentUser === userId) currentOptOut = true;
      client.opt_out_capturing();
      notify();
      try {
        await save(true);
      } catch {
        return "local_only";
      }
      if (readRecords()[userId] === "pending") writeRecord(userId, "saved");
      return "saved";
    }
    try {
      await save(false);
    } catch {
      return "failed";
    }
    writeRecord(userId, null);
    // The account now says "not opted out": resolve as if it had just
    // answered — opens a gate a failed read left shut, and identifies.
    currentUser = userId;
    currentOptOut = false;
    client.opt_in_capturing();
    gateOpen = true;
    identifyUser(userId);
    openGate();
    notify();
    return "saved";
  } finally {
    choiceInFlight = false;
  }
}

/**
 * Forget the identity (sign-out, account deletion, dead session).
 *
 * posthog-js's `reset()` also wipes its stored consent. The decision for the
 * student signing out is carried across — from our own state, never from a
 * posthog-js getter, which folds DNT/GPC in — so the signed-out browser stays
 * off for an opted-out student; the next sign-in re-derives it for whoever
 * that is.
 */
export function resetAnalytics(): void {
  if (!client) {
    if (starting) {
      pendingReset = true;
      pendingResolution = null;
    }
    return;
  }
  const carry = currentOptOut;
  client.reset();
  if (carry) client.opt_out_capturing();
  currentUser = null;
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

/** Test-only: forget module state between cases. */
export function __resetAnalyticsForTests(): void {
  client = null;
  starting = false;
  pendingReset = false;
  pendingResolution = null;
  currentUser = null;
  currentOptOut = false;
  gateOpen = false;
  droppedPageview = false;
  pageviewSent = false;
  choiceInFlight = false;
  listeners.clear();
}
