/**
 * Turns a thrown API error into copy a person can read.
 *
 * `lib/api.ts` rejects with an `ApiError` whose message is the raw response
 * body — literally `{"detail":"Exam not found."}`. Rendering that with
 * `String(err)` dumps JSON into the UI, which is what these helpers exist to
 * prevent.
 *
 * Everything here accepts `unknown` and degrades rather than throwing: not
 * every rejection in this app is an `ApiError` (a few call sites still throw a
 * bare `Error`, and network failures throw `TypeError`), so nothing may assume
 * a shape.
 */

export interface ErrorDetail {
  /** A server-supplied `detail` string, when the body carried one. */
  detail?: string;
  /**
   * The HTTP status, when it survived the trip — off an `ApiError.status`, a
   * body field, or an `HTTP 404` message. Absent for the call sites that still
   * throw a bare `Error`, and for transport failures that never got a response.
   */
  status?: number;
}

type Body = Record<string, unknown>;

function asRecord(value: unknown): Body | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Body)
    : null;
}

function rawMessage(err: unknown): string {
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message;
  const record = asRecord(err);
  const message = record?.message;
  return typeof message === "string" ? message : "";
}

function parseJson(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

function detailOf(body: Body): string | undefined {
  // The coded envelope wins. Quiz routes answer with
  // `{error: {code, message, request_id}, detail, request_id}` — `error.message`
  // is the student-readable sentence, while top-level `detail` is legacy and,
  // for a 422, a list of Pydantic error dicts (#537 / backend quiz_errors.py).
  const coded = asRecord(body.error)?.message;
  if (typeof coded === "string" && coded.trim()) return coded.trim();

  const detail = body.detail;
  if (typeof detail === "string") return detail.trim() || undefined;
  // FastAPI request-validation failures nest the message under detail[].msg.
  if (Array.isArray(detail)) {
    for (const entry of detail) {
      const msg = asRecord(entry)?.msg;
      if (typeof msg === "string" && msg.trim()) return msg.trim();
    }
  }
  return undefined;
}

const HTTP_STATUS_RE = /\bHTTP\s+(\d{3})\b/;

function isStatus(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 100 && value <= 599;
}

function statusFrom(err: unknown, body: Body | null): number | undefined {
  const attached = asRecord(err);
  for (const candidate of [attached?.status, attached?.statusCode, body?.status, body?.status_code]) {
    if (isStatus(candidate)) return candidate;
  }
  const matched = HTTP_STATUS_RE.exec(rawMessage(err));
  if (matched) {
    const parsed = Number(matched[1]);
    if (isStatus(parsed)) return parsed;
  }
  return undefined;
}

/** Pulls what the server actually told us out of a thrown error. */
export function extractErrorDetail(err: unknown): ErrorDetail {
  // `ApiError.body` is the already-parsed response body (#537). Prefer it over
  // re-parsing `message`, which is the same JSON as text.
  const parsedBody = asRecord(err) && !Array.isArray(err)
    ? asRecord((err as { body?: unknown }).body)
    : null;
  const body = parsedBody
    ?? (err instanceof Error ? null : asRecord(err))
    ?? asRecord(parseJson(rawMessage(err)));
  const out: ErrorDetail = {};
  const detail = body ? detailOf(body) : undefined;
  if (detail) out.detail = detail;
  const status = statusFrom(err, body);
  if (status !== undefined) out.status = status;
  return out;
}

/** The HTTP status behind an error, when one can be recovered. */
export function statusOf(err: unknown): number | undefined {
  return extractErrorDetail(err).status;
}

const NOT_FOUND_TEXT = /\bnot found\b/i;

/**
 * Whether an error means "that thing doesn't exist" rather than "something
 * broke" — the difference between friendly guidance and a red toast.
 *
 * An explicit status decides it. The wording fallback only covers the call
 * sites that still throw a bare `Error` without one; it is a safety net, not
 * the primary path, so rewording a server message can't silently turn
 * guidance back into an error toast.
 */
export function isNotFound(err: unknown): boolean {
  const { detail, status } = extractErrorDetail(err);
  if (status !== undefined) return status === 404;
  return NOT_FOUND_TEXT.test(detail ?? rawMessage(err));
}

const STATUS_COPY: Record<number, string> = {
  400: "That request wasn't valid. Check your selection and try again.",
  401: "Your session expired — sign in again.",
  403: "You don't have access to that.",
  404: "We couldn't find that — it may have been deleted.",
  408: "That took too long. Try again.",
  409: "That changed somewhere else. Reload and try again.",
  429: "Too many requests right now. Wait a moment and try again.",
  500: "Something went wrong on our end. Try again in a moment.",
};

function statusCopy(status: number | undefined): string | undefined {
  if (status === undefined) return undefined;
  if (status in STATUS_COPY) return STATUS_COPY[status];
  if (status >= 500) return "That's temporarily unavailable. Try again in a moment.";
  return undefined;
}

const MAX_DETAIL_LENGTH = 160;

// Brackets, angle brackets and line breaks are the tells of a serialized
// payload, markup, a stack trace or "[object Object]" — none of which belong
// in front of a user.
const UNFRIENDLY = /[{}[\]<>\n\r]|\bTraceback\b/;

function looksHuman(text: string): boolean {
  return (
    text.length > 0
    && text.length <= MAX_DETAIL_LENGTH
    && /[a-z]/i.test(text)
    && !UNFRIENDLY.test(text)
  );
}

/**
 * A short sentence safe to put in a toast. Never returns `[object Object]`,
 * a raw JSON body, or a stack trace — worst case it returns `fallback`.
 */
export function humanizeError(err: unknown, fallback: string): string {
  const { detail, status } = extractErrorDetail(err);
  if (detail && looksHuman(detail)) return detail;
  return statusCopy(status) ?? fallback;
}
