/**
 * The crisis-support card's payload (docs/safety/crisis-support.md).
 *
 * A student-facing AI route whose screen fired on what the student TYPED
 * answers with `crisis_support` (this shape) plus `reply` (the same copy as
 * text) INSTEAD of its normal result: no model ran and nothing of the turn
 * was recorded. A notes action whose NOTE matched answers with its normal
 * result and the card ALONGSIDE it (`crisis_support_alongside: true`), and an
 * error answer it gives (a 429) carries the card in its body. Every string
 * in the payload comes from backend/services/crisis_support_copy.py — the
 * card has no copy of its own, so that file is the one place the wording
 * lives.
 */

export interface CrisisSupportAction {
  kind: "call" | "text" | "link";
  label: string;
  href: string;
}

export interface CrisisSupportResource {
  id: string;
  name: string;
  detail: string;
  actions: CrisisSupportAction[];
}

export interface CrisisSupport {
  version: string;
  title: string;
  intro: string[];
  resources_heading: string;
  resources: CrisisSupportResource[];
  closing: string[];
  dismiss_label: string;
}

/** What a response may carry when the crisis screen fired. */
export interface WithCrisisSupport {
  crisis_support?: CrisisSupport | null;
  /** The card sits beside a normal result instead of replacing it. */
  crisis_support_alongside?: boolean;
}

/** Only these open anything: a phone call, a text, or an https page. */
const SAFE_HREF = /^(tel:|sms:|https:\/\/)/i;

const isString = (v: unknown): v is string => typeof v === "string";
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter(isString) : []);

function actionOf(v: unknown): CrisisSupportAction | null {
  const a = v as Partial<CrisisSupportAction> | null;
  if (!a || !isString(a.label) || !isString(a.href) || !SAFE_HREF.test(a.href)) return null;
  const kind = a.kind === "call" || a.kind === "text" || a.kind === "link" ? a.kind : "link";
  return { kind, label: a.label, href: a.href };
}

function resourceOf(v: unknown): CrisisSupportResource | null {
  const r = v as Partial<CrisisSupportResource> | null;
  if (!r || !isString(r.id) || !isString(r.name) || !isString(r.detail)) return null;
  const actions = (Array.isArray(r.actions) ? r.actions : [])
    .map(actionOf)
    .filter((a): a is CrisisSupportAction => a !== null);
  return { id: r.id, name: r.name, detail: r.detail, actions };
}

/**
 * The card a response carries, validated — or null when it carries none.
 * A link whose scheme is not tel:/sms:/https: is dropped, never rendered.
 */
export function crisisSupportOf(value: unknown): CrisisSupport | null {
  const v = value as Partial<CrisisSupport> | null | undefined;
  if (!v || typeof v !== "object" || !isString(v.title)) return null;
  const resources = (Array.isArray(v.resources) ? v.resources : [])
    .map(resourceOf)
    .filter((r): r is CrisisSupportResource => r !== null);
  if (resources.length === 0) return null;
  return {
    version: isString(v.version) ? v.version : "",
    title: v.title,
    intro: strings(v.intro),
    resources_heading: isString(v.resources_heading) ? v.resources_heading : "",
    resources,
    closing: strings(v.closing),
    dismiss_label: isString(v.dismiss_label) ? v.dismiss_label : "",
  };
}

/** `crisisSupportOf` on a whole response body (`res.crisis_support`). */
export function crisisSupportIn(response: unknown): CrisisSupport | null {
  if (!response || typeof response !== "object") return null;
  return crisisSupportOf((response as WithCrisisSupport).crisis_support);
}

/** The card an error answer carries in its body (an `ApiError`'s `body`), or null. */
export function crisisSupportInError(error: unknown): CrisisSupport | null {
  if (!error || typeof error !== "object") return null;
  return crisisSupportIn((error as { body?: unknown }).body);
}

/**
 * Send to tutor showed the card beside its result and then opens /learn on the
 * note's title; the start there answers with the same card beside the session
 * (docs/safety/crisis-support.md). `markNoteCardShown` records that the card
 * for `noteId` was just shown and closed; `takeNoteCardShown`, at that start,
 * says whether it was, so the card does not pop up a second time. One-shot (a
 * take spends the mark), per tab, and only for `CARD_SHOWN_TTL_MS`: every
 * doubt (no storage, another note, a stale or unreadable mark) shows the card.
 */
const CARD_SHOWN_KEY = "sapling_crisis_card_shown_note";
export const CARD_SHOWN_TTL_MS = 10 * 60 * 1000;

export function markNoteCardShown(noteId: string, now: number = Date.now()): void {
  try {
    sessionStorage.setItem(CARD_SHOWN_KEY, JSON.stringify({ noteId, at: now }));
  } catch {
    // No storage: the start shows the card again, which is the safe side.
  }
}

export function takeNoteCardShown(noteId: string, now: number = Date.now()): boolean {
  try {
    const raw = sessionStorage.getItem(CARD_SHOWN_KEY);
    if (raw === null) return false;
    sessionStorage.removeItem(CARD_SHOWN_KEY);
    const mark = JSON.parse(raw) as { noteId?: unknown; at?: unknown } | null;
    if (!mark || mark.noteId !== noteId || typeof mark.at !== "number") return false;
    const age = now - mark.at;
    return age >= 0 && age <= CARD_SHOWN_TTL_MS;
  } catch {
    return false;
  }
}
