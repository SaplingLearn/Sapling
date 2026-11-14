/**
 * The crisis-support card's payload (docs/safety/crisis-support.md).
 *
 * A student-facing AI route whose screen fired answers with `crisis_support`
 * (this shape) plus `reply` (the same copy as text) INSTEAD of its normal
 * result: no model ran and nothing of the turn was recorded. Every string in
 * the payload comes from backend/services/crisis_support_copy.py — the card
 * has no copy of its own, so that file is the one place the wording lives.
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
