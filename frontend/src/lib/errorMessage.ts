/**
 * Turns a thrown API error into copy a person can read.
 *
 * `lib/api.ts` rejects with `new Error(await res.text())`, so a FastAPI failure
 * arrives as an Error whose message is the raw response body — literally
 * `{"detail":"Exam not found."}`. Rendering that with `String(err)` dumps JSON
 * into the UI, which is what these helpers exist to prevent.
 */

export interface ErrorDetail {
  /** A server-supplied `detail` string, when the body carried one. */
  detail?: string;
  /**
   * The HTTP status, when it survived the trip. `fetchJSON` only spells the
   * status out (`HTTP 404`) for an empty response body, so a FastAPI failure —
   * which always carries a JSON body — usually arrives without one.
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
  const body = (err instanceof Error ? null : asRecord(err))
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
