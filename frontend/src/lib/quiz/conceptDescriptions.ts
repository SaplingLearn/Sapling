/**
 * Concept descriptions (R-8's one-sentence definition), remembered.
 *
 * `graph_nodes` has no `description` column, so a description is an LLM call
 * (`POST /api/graph/{user}/concept-description`). The backend caches it across
 * students when Redis is configured; this module is the browser's half: a
 * description seen once is kept in localStorage and comes back instantly on
 * every later visit, and concurrent asks for the same concept share one
 * request (a row's hover prefetch and the card's own fetch, say).
 *
 * Entries are keyed per student as well as by concept and course label: the
 * concept names come from the student's own uploads, so on a shared device
 * one student's list must not be readable from another's session. They
 * expire after 30 days, and the store is parsed only when its text changes
 * (render reads are a string compare). localStorage is a per-viewer
 * convenience here: unavailable or full, the module falls back to fetching,
 * exactly as it did before it existed.
 */

import { describeConcept } from "./api";

const STORAGE_KEY = "sapling_concept_descriptions_v2";
/** The first, unkeyed store: removed on first use, so the per-student keying
 *  also covers what was already on a shared device. */
const LEGACY_KEYS = ["sapling_concept_descriptions_v1"];
let legacyCleared = false;
/** Oldest entries are dropped past this, so the store stays small. */
const MAX_ENTRIES = 300;
/** A remembered description is re-fetched after this long. */
const TTL_MS = 30 * 24 * 60 * 60 * 1000;

/** `t`: when it was stored (ms); `d`: the description. */
type Store = Record<string, { t: number; d: string }>;

function keyFor(userId: string, concept: string, courseLabel?: string): string {
  return `${userId}|${(courseLabel ?? "").toLowerCase()}|${concept.toLowerCase()}`;
}

/** The last text read and what it parsed to: a render-time read is a string
 *  compare unless something wrote in between. */
let parsedCache: { raw: string | null; store: Store } = { raw: null, store: {} };

function readStore(): Store {
  try {
    if (!legacyCleared) {
      legacyCleared = true;
      for (const key of LEGACY_KEYS) window.localStorage.removeItem(key);
    }
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === parsedCache.raw) return parsedCache.store;
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    const store = parsed && typeof parsed === "object" ? (parsed as Store) : {};
    parsedCache = { raw, store };
    return store;
  } catch {
    return {};
  }
}

function writeEntry(key: string, text: string): void {
  try {
    const store = { ...readStore() };
    delete store[key]; // re-insert at the end: insertion order is the age order
    store[key] = { t: Date.now(), d: text };
    const keys = Object.keys(store);
    for (const stale of keys.slice(0, Math.max(0, keys.length - MAX_ENTRIES))) delete store[stale];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Private window, quota, blocked storage: the description still shows,
    // it just won't be remembered.
  }
}

/** The remembered, unexpired description, or `null`. Synchronous: safe in render. */
export function cachedDescription(userId: string, concept: string, courseLabel?: string): string | null {
  if (typeof window === "undefined") return null;
  const entry = readStore()[keyFor(userId, concept, courseLabel)];
  if (!entry || typeof entry.d !== "string" || Date.now() - entry.t > TTL_MS) return null;
  return entry.d;
}

const inFlight = new Map<string, Promise<string>>();

/**
 * The description, from the store when it is there, else fetched once
 * (concurrent callers share the request) and remembered. Rejects when the
 * fetch fails or comes back blank.
 */
export function loadDescription(userId: string, concept: string, courseLabel?: string): Promise<string> {
  const key = keyFor(userId, concept, courseLabel);
  const hit = cachedDescription(userId, concept, courseLabel);
  if (hit) return Promise.resolve(hit);
  const pending = inFlight.get(key);
  if (pending) return pending;
  const request = describeConcept(userId, concept, courseLabel)
    .then(description => {
      const text = description.trim();
      if (!text) throw new Error("empty description");
      writeEntry(key, text);
      return text;
    })
    .finally(() => inFlight.delete(key));
  inFlight.set(key, request);
  return request;
}
