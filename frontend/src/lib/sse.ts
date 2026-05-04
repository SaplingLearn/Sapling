/**
 * Minimal Server-Sent Events consumer for fetch-based requests.
 *
 * The browser's built-in EventSource only does GET with no body, so we
 * can't use it for the multipart-POST upload route. Instead we read the
 * Response body as a stream, parse the SSE wire format manually, and
 * yield typed events as they arrive.
 *
 * Wire format (per https://html.spec.whatwg.org/multipage/server-sent-events.html):
 *   event: <name>
 *   data: <payload>
 *   <blank line>
 *
 * `data:` lines may repeat; the spec says to join them with newlines.
 * `event:` defaults to "message" if absent.
 */

export type SSEEvent<T = unknown> = {
  event: string;
  data: T;
};

/**
 * Stream Server-Sent Events from a fetch response, yielding parsed events.
 *
 * Throws on non-2xx responses or missing body. The generator completes
 * naturally when the server closes the connection.
 */
export async function* streamSSE<T = unknown>(
  url: string,
  init: RequestInit,
): AsyncGenerator<SSEEvent<T>> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(body || `HTTP ${res.status}`);
  }
  if (!res.body) {
    throw new Error("Streaming response has no body.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE blocks are separated by blank lines. Tolerate \r\n.
      let separatorIdx: number;
      while ((separatorIdx = findBlockEnd(buffer)) !== -1) {
        const block = buffer.slice(0, separatorIdx).replace(/\r\n/g, "\n");
        buffer = buffer.slice(separatorIdx + 2);

        const parsed = parseBlock<T>(block);
        if (parsed) yield parsed;
      }
    }
    // Flush a final block if the stream closed without a trailing blank line.
    if (buffer.trim().length > 0) {
      const parsed = parseBlock<T>(buffer.replace(/\r\n/g, "\n"));
      if (parsed) yield parsed;
    }
  } finally {
    reader.releaseLock();
  }
}

function findBlockEnd(buffer: string): number {
  const lf = buffer.indexOf("\n\n");
  const crlf = buffer.indexOf("\r\n\r\n");
  if (lf === -1) return crlf === -1 ? -1 : crlf;
  if (crlf === -1) return lf;
  return Math.min(lf, crlf);
}

function parseBlock<T>(block: string): SSEEvent<T> | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    if (colon === -1) continue;
    const field = line.slice(0, colon);
    const value = line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
    // id / retry are spec'd but we don't use them
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(dataStr) as T };
  } catch {
    // Backend SSE payloads are always JSON; if not, surface the raw string.
    return { event, data: dataStr as unknown as T };
  }
}
