/**
 * The error every failed API response is thrown as (`ApiError`), and the
 * parsing that builds it, shared by `fetchJSON` (lib/api.ts) and the SSE
 * client (lib/sse.ts) so a streamed route's error answer carries exactly what
 * a JSON route's does: the status, the coded envelope's fields, `Retry-After`
 * and the parsed body (where a crisis card rides on an error,
 * `crisisSupportInError`).
 *
 * A failed API response carries the HTTP status alongside the body text so
 * callers can branch on the status instead of pattern-matching the message —
 * `lib/errorMessage.ts` reads `status` off the thrown value.
 *
 * `message` stays the raw body for backward compatibility: callers that
 * stringify the error, or read `.message`, behave exactly as they did before.
 *
 * Since #537 it also carries what the coded envelope told us. Quiz routes
 * answer with `{error: {code, message, request_id}, detail, request_id}`
 * (backend/services/quiz_errors.py::quiz_error_body) plus a `Retry-After`
 * header on 429; `code`/`requestId`/`retryAfterSec`/`body` surface that so
 * `lib/quiz/errors.ts` can tell a rate limit from a daily cap from a generation
 * timeout. All four are optional — routes outside the quiz router still answer
 * with the legacy `{detail, request_id}` shape and leave them undefined.
 */
export interface ApiErrorFields {
  /** `error.code` off the coded envelope, when the route sent one. */
  code?: string;
  /** `error.request_id` / top-level `request_id` — the support handle. */
  requestId?: string;
  /** Whole-seconds `Retry-After`, when the response carried the header. */
  retryAfterSec?: number;
  /** The parsed JSON body, when the body was JSON. */
  body?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly requestId?: string;
  readonly retryAfterSec?: number;
  readonly body?: unknown;

  constructor(message: string, status: number, fields: ApiErrorFields = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = fields.code;
    this.requestId = fields.requestId;
    this.retryAfterSec = fields.retryAfterSec;
    this.body = fields.body;
  }
}

export function parseErrorBody(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed.startsWith('{')) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return undefined;
  }
}

/** `Retry-After` is either whole seconds or an HTTP date. Only the numeric form
 *  is honoured — a date needs clock-skew handling nobody here wants, and the one
 *  route that sets the header (quiz.py:1238) always sends seconds. */
export function parseRetryAfter(header: string | null | undefined): number | undefined {
  if (!header) return undefined;
  const trimmed = header.trim();
  if (!trimmed) return undefined;
  const seconds = Number(trimmed);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.round(seconds) : undefined;
}

/** Pulls the coded-envelope fields out of a parsed error body, tolerating both
 *  the quiz shape and the legacy `{detail, request_id}` one. */
export function errorFieldsFrom(body: unknown): { code?: string; requestId?: string } {
  if (body === null || typeof body !== 'object') return {};
  const record = body as Record<string, unknown>;
  const nested = record.error;
  const error = nested !== null && typeof nested === 'object'
    ? (nested as Record<string, unknown>)
    : null;
  const code = error && typeof error.code === 'string' ? error.code : undefined;
  const requestId = [error?.request_id, record.request_id].find(
    (v): v is string => typeof v === 'string' && v.length > 0,
  );
  return { code, requestId };
}

/** The `ApiError` a failed response (`res`, its body read as `text`) is thrown
 *  as: the raw text as the message, every field the body and headers carry. */
export function apiErrorOf(res: Response, text: string): ApiError {
  const body = parseErrorBody(text);
  return new ApiError(text || `HTTP ${res.status}`, res.status, {
    ...errorFieldsFrom(body),
    retryAfterSec: parseRetryAfter(res.headers?.get('Retry-After')),
    body,
  });
}
