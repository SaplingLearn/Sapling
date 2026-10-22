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
 * A description depends only on the concept and its course label, never on
 * the student, so the key is just those two. localStorage is a per-viewer
 * convenience here: unavailable or full, the module falls back to fetching,
 * exactly as it did before it existed.
 */

import { describeConcept } from "./api";

const STORAGE_KEY = "sapling_concept_descriptions_v1";
/** Oldest entries are dropped past this, so the store stays small. */
const MAX_ENTRIES = 300;

type Store = Record<string, string>;

function keyFor(concept: string, courseLabel?: string): string {
  return `${(courseLabel ?? "").toLowerCase()}|${concept.toLowerCase()}`;
}

function readStore(): Store {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? (parsed as Store) : {};
  } catch {
    return {};
  }
}

function writeEntry(key: string, text: string): void {
  try {
    const store = readStore();
    delete store[key]; // re-insert at the end: insertion order is the age order
    store[key] = text;
    const keys = Object.keys(store);
    for (const stale of keys.slice(0, Math.max(0, keys.length - MAX_ENTRIES))) delete store[stale];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Private window, quota, blocked storage: the description still shows,
    // it just won't be remembered.
  }
}

/** The remembered description, or `null`. Synchronous: safe in render. */
export function cachedDescription(concept: string, courseLabel?: string): string | null {
  if (typeof window === "undefined") return null;
  return readStore()[keyFor(concept, courseLabel)] ?? null;
}

const inFlight = new Map<string, Promise<string>>();

/**
 * The description, from the store when it is there, else fetched once
 * (concurrent callers share the request) and remembered. Rejects when the
 * fetch fails or comes back blank.
 */
export function loadDescription(userId: string, concept: string, courseLabel?: string): Promise<string> {
  const key = keyFor(concept, courseLabel);
  const hit = cachedDescription(concept, courseLabel);
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
