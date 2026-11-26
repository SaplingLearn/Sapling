/**
 * Where a quiz was entered from, and how to get back.
 *
 * Before #537 the quiz screen exited to a hardcoded `/learn` no matter how it
 * was reached — Cancel, mid-quiz Exit and Done all pushed the same route, and
 * nothing carried the origin at all (R5 §C.1). `source` is that missing thread:
 * every entry point encodes it in the URL, `parseEntry` reads it back, and
 * `exits.ts` turns it into a destination.
 *
 * The `return` param is a same-origin PATH and nothing else. Anything carrying a
 * scheme or a host is dropped rather than sanitised — an attacker-supplied
 * `?return=` is otherwise an open redirect off a link a student would trust.
 */

import { START_PARAM } from "@/lib/toolHrefs";
import { QUEUE_MAX } from "./session";
import type { QuizSource, SourceKind } from "./types";

export interface EntryRequest {
  /** A concept node id — the precise deep link. */
  concept?: string;
  /** A concept NAME — the fuzzy legacy deep link; resolved against the graph. */
  topic?: string;
  /** An abstract course id — "practice on this course". */
  course?: string;
  /** The only scope value: "review everything due". */
  scope?: "due";
  /**
   * W3.3c: explicit concept ids for a `scope=due` cue stream (Practice what's
   * due). Cap `QUEUE_MAX`. When set, the home uses this queue instead of the
   * semester-wide due set. Ignored unless `scope` is `"due"`.
   */
  queue?: string[];
  /** An attempt id to resume. */
  attempt?: string;
  /** `?start=1`: start the named concept / course / due queue on arrival rather
   *  than offering it on the home (the Study hub's Quiz buttons). */
  start?: boolean;
  source: QuizSource;
}

/**
 * Trim, dedupe, and cap concept ids for a due Practice queue (R-4 `QUEUE_MAX`).
 * Shared by href builders and `parseEntry`.
 */
export function practiceDueQueue(ids: readonly string[] | null | undefined): string[] {
  if (!ids?.length) return [];
  const out: string[] = [];
  for (const raw of ids) {
    const id = raw.trim();
    if (!id || out.includes(id)) continue;
    out.push(id);
    if (out.length >= QUEUE_MAX) break;
  }
  return out;
}

/** `?queue=id1,id2` — empty / whitespace tokens dropped. */
function queueFromParam(value: string | null | undefined): string[] {
  if (!value?.trim()) return [];
  return practiceDueQueue(value.split(","));
}

const SOURCE_KINDS: readonly SourceKind[] = [
  "tree",
  "dashboard",
  "notes",
  "nav",
  "link",
  "quiz",
];

function isSourceKind(value: string | null): value is SourceKind {
  return value !== null && (SOURCE_KINDS as readonly string[]).includes(value);
}

/**
 * A same-origin path we are willing to `router.push`.
 *
 * Must start with a single `/`. `//evil.com` is protocol-relative and leaves the
 * origin; `/\evil.com` is the same trick with a backslash, which some parsers
 * normalise; anything with a scheme is obviously external. Control characters
 * are rejected because they can hide the rest of the string from a naive check.
 */
export function isSafeReturnPath(value: string | null | undefined): value is string {
  if (!value) return false;
  if (!value.startsWith("/")) return false;
  if (value.startsWith("//") || value.startsWith("/\\")) return false;
  if (/[\u0000-\u001f\u007f]/.test(value)) return false;
  return true;
}

function trimmed(params: URLSearchParams, key: string): string | undefined {
  const value = params.get(key)?.trim();
  return value ? value : undefined;
}

type EntryTarget = Pick<EntryRequest, "concept" | "topic" | "course" | "scope" | "attempt">;

/** What the link asks to be quizzed on: the target params that are present. */
function entryTarget(params: URLSearchParams): EntryTarget {
  const target: EntryTarget = {};
  for (const key of ["concept", "topic", "course"] as const) {
    const value = trimmed(params, key);
    if (value) target[key] = value;
  }
  if (trimmed(params, "scope") === "due") target.scope = "due";
  const attempt = trimmed(params, "attempt");
  if (attempt) target.attempt = attempt;
  return target;
}

/** Where the link came from. A link with a target but no `from` is a legacy
 *  deep link (`{kind: "link"}`, §6); a bare `/quiz` is nav. */
function entrySource(params: URLSearchParams, target: EntryTarget): QuizSource {
  const from = params.get("from");
  const fallback: SourceKind = Object.keys(target).length > 0 ? "link" : "nav";
  const source: QuizSource = { kind: isSourceKind(from) ? from : fallback };
  const returnTo = trimmed(params, "return");
  if (isSafeReturnPath(returnTo)) source.returnTo = returnTo;
  if (target.concept) source.conceptId = target.concept;
  const noteId = trimmed(params, "note");
  if (noteId) source.noteId = noteId;
  return source;
}

/**
 * Reads the quiz entry out of the URL.
 *
 * `from`/`return`/`note` describe the origin; `concept`/`topic`/`course`/
 * `scope`/`attempt` describe the target. A link with a target but no `from` is
 * a legacy deep link (`{kind: "link"}`, §6); a bare `/quiz` is nav.
 */
export function parseEntry(params: URLSearchParams): EntryRequest {
  const target = entryTarget(params);
  const entry: EntryRequest = { source: entrySource(params, target), ...target };
  if (trimmed(params, START_PARAM) === "1") entry.start = true;
  // Explicit due cue-stream ids (W3.3c) — only with `scope=due`.
  if (entry.scope === "due") {
    const queue = queueFromParam(params.get("queue"));
    if (queue.length > 0) entry.queue = queue;
  }
  return entry;
}

/** The href every inbound caller links to (§6). Exactly one target field is
 *  meaningful; the rest are ignored in the order below. `topic` is a concept
 *  NAME (fuzzy resolve); prefer `concept` (node id) when the caller has one.
 *  `queue` is ancillary to `scope=due` (Practice cue stream), not a target. */
export function buildQuizHref(
  target: {
    concept?: string;
    topic?: string;
    course?: string;
    scope?: "due";
    /** With `scope: "due"`: multi-concept Practice queue (learner_next due[]). */
    queue?: readonly string[];
    attempt?: string;
  },
  source: QuizSource,
  opts: { start?: boolean } = {},
): string {
  const params = new URLSearchParams();
  if (target.concept) params.set("concept", target.concept);
  else if (target.topic) params.set("topic", target.topic);
  else if (target.course) params.set("course", target.course);
  else if (target.scope) {
    params.set("scope", target.scope);
    const queue = practiceDueQueue(target.queue);
    if (queue.length > 0) params.set("queue", queue.join(","));
  } else if (target.attempt) params.set("attempt", target.attempt);

  params.set("from", source.kind);
  if (isSafeReturnPath(source.returnTo)) params.set("return", source.returnTo);
  if (source.noteId) params.set("note", source.noteId);
  if (opts.start) params.set(START_PARAM, "1");

  return `/quiz?${params.toString()}`;
}
