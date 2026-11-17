/**
 * Pure helpers behind the admin "Email" tab (./EmailBroadcasts): labels,
 * chip classes and the send gate, kept out of the component so each branch
 * is unit-testable on its own.
 */
import type {
  EmailAudience, EmailAudienceKey, EmailBroadcast, EmailBroadcastPreview, EmailStatus, EmailVariable,
} from "@/lib/types";

const BROADCAST_CHIP: Record<EmailBroadcast["status"], string> = {
  sending: "chip chip--info",
  sent: "chip chip--accent",
  partial: "chip chip--warn",
  skipped: "chip",
  failed: "chip chip--warn",
};

/** The draft a preview was rendered for: Send waits until it is the current one. */
const draftKey = (subject: string, body: string) => JSON.stringify([subject, body]);

export function people(n: number) {
  return `${n} ${n === 1 ? "person" : "people"}`;
}

export const token = (key: string) => `{{${key}}}`;

/** The history chip's class; an unknown status gets the plain chip. */
export function broadcastChipClass(status: EmailBroadcast["status"]): string {
  return BROADCAST_CHIP[status] ?? "chip";
}

/** A run the server marks `stale` (no heartbeat) shows as "stalled". */
export function broadcastStatusLabel(b: Pick<EmailBroadcast, "status" | "stale">): string {
  return b.stale ? "stalled" : b.status;
}

/** When the history row says it went out: sent, or else created. */
export function broadcastDate(b: Pick<EmailBroadcast, "sent_at" | "created_at">): string {
  return new Date(b.sent_at ?? b.created_at).toLocaleString();
}

/** An audience key's label, or the raw key when it isn't a known audience. */
export function audienceLabel(audiences: EmailAudience[], key: string): string {
  return audiences.find((a) => a.key === key)?.label ?? key;
}

/** Poll the history only while something is still going out (a stale run isn't). */
export function isAnySending(broadcasts: EmailBroadcast[]): boolean {
  return broadcasts.some((b) => b.status === "sending" && !b.stale);
}

/** A Personalize chip's tooltip: the token, plus its button label or fallback. */
export function variableTitle(v: EmailVariable): string {
  if (v.button) {
    return `${token(v.key)}\nOn its own line it's a "${v.button}" button. {{${v.key}|Your label}} changes the label.`;
  }
  return v.fallback ? `${token(v.key)}\nIf unknown: ${v.fallback}` : token(v.key);
}

/** The typed confirmation: the recipient count, or SEND. */
export function confirmMatches(text: string, n: number): boolean {
  return text.trim() === String(n) || text.trim() === "SEND";
}

/** Insert `text` over the field's selection (caret at the end when unknown). */
export function spliceAtSelection(
  value: string,
  el: { selectionStart: number | null; selectionEnd: number | null } | null,
  text: string,
): { start: number; next: string } {
  const start = Math.min(el?.selectionStart ?? value.length, value.length);
  const end = Math.max(start, Math.min(el?.selectionEnd ?? start, value.length));
  return { start, next: value.slice(0, start) + text + value.slice(end) };
}

export interface SendGateInput {
  audiences: EmailAudience[];
  audience: EmailAudienceKey | null;
  subject: string;
  body: string;
  preview: EmailBroadcastPreview | null;
  previewFor: { subject: string; body: string } | null;
  status: EmailStatus | null;
  sending: boolean;
  confirmText: string;
}

/**
 * Whether the shown preview was rendered for the current (trimmed) draft:
 * otherwise its `unknown_variables` may describe old text.
 */
function isPreviewCurrent(i: SendGateInput): boolean {
  return i.preview !== null && i.previewFor !== null &&
    draftKey(i.previewFor.subject, i.previewFor.body) === draftKey(i.subject.trim(), i.body.trim());
}

/** Everything the compose actions and the confirm dialog derive from state. */
export function deriveSendGate(i: SendGateInput) {
  const selectedAudience = i.audiences.find((a) => a.key === i.audience) ?? null;
  const n = selectedAudience?.count ?? 0;
  const hasDraft = i.subject.trim().length > 0 && i.body.trim().length > 0;
  const previewCurrent = isPreviewCurrent(i);
  const unknownVars = i.preview?.unknown_variables ?? [];
  const hasUnknown = unknownVars.length > 0;
  const canSend =
    hasDraft && previewCurrent && !hasUnknown && selectedAudience !== null && n > 0 && !i.sending;
  const notConfigured = i.status !== null && !i.status.configured;
  const confirmOk = confirmMatches(i.confirmText, n);
  return { selectedAudience, n, hasDraft, previewCurrent, unknownVars, hasUnknown, canSend, notConfigured, confirmOk };
}
