/** Test-only observer. Read a bounded response clone in the browser because
 * Chromium's protocol may never report an SSE request finished to Playwright.
 * The application receives the exact original response and consumes it normally.
 */
import type { Page } from "@playwright/test";

type CapturedTurn = {
  path: string;
  status: number | null;
  is_sse: boolean;
  types: string[];
  done_count: number;
  error_count: number;
  nonempty_reply: boolean;
  reply: string;
  phase: string | null;
  graded: boolean | null;
  unavailable: boolean | null;
  refused: boolean | null;
  eof: boolean;
  finished: boolean;
  inspection_error: string | null;
};

declare global {
  interface Window {
    __saplingTestLoopStreams?: { records: CapturedTurn[]; overflowed: boolean };
  }
}

// Plain script keeps addInitScript independent of transpiler-generated closures.
// Reply text stays bounded in browser memory; readLoopStream exports comparisons
// and protocol metadata only, never tokens, request bodies or raw replies.
export const LOOP_STREAM_CAPTURE_SCRIPT = String.raw`(() => {
  if (window.__saplingTestLoopStreams) return;
  const paths = new Set(['/api/learn/loop/chat/stream', '/api/learn/loop/check/answer/stream']);
  const kinds = new Set(['status','progress','result','error','token','graph_update','done','phase','check','hint_offer','learner_state','budget','retract']);
  const phases = new Set(['probe','plan','teach','check','feedback','close','hint']);
  const state = {records: [], overflowed: false};
  Object.defineProperty(window, '__saplingTestLoopStreams', {value: state});
  const original = window.fetch;
  function fail(kind) { throw {inspectionKind: kind}; }
  async function inspect(response, meta) {
    let reader, timer;
    try {
      try { reader = response.clone().body?.getReader(); }
      catch { fail('clone_failed'); }
      if (!reader) fail('missing_body');
      const read = async () => {
        const decoder = new TextDecoder('utf-8', {fatal: true});
        let pending = '', bytes = 0;
        const frame = text => {
          const names = [], data = [];
          for (const line of text.split('\n')) {
            if (line.startsWith('event:')) names.push(line.slice(6).trim());
            if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
          }
          if (!data.length || !data.join('\n')) return;
          let payload;
          try { payload = JSON.parse(data.join('\n')); }
          catch { fail('invalid_json'); }
          const type = payload?.type;
          if (names.length !== 1 || !kinds.has(type) || names[0] !== type) fail('invalid_envelope');
          if (meta.types.length >= 2048) fail('frame_count_exceeded');
          meta.types.push(type);
          if (type === 'error') meta.error_count += 1;
          if (type === 'done') {
            const result = payload.data;
            if (!result || typeof result !== 'object' || Array.isArray(result)) fail('invalid_envelope');
            meta.done_count += 1;
            meta.nonempty_reply = typeof result.reply === 'string' && !!result.reply.trim();
            if (typeof result.reply === 'string' && result.reply.length > 8192) fail('reply_size_exceeded');
            meta.reply = typeof result.reply === 'string' ? result.reply : '';
            meta.phase = phases.has(result.phase) ? result.phase : null;
            for (const key of ['graded','unavailable','refused']) meta[key] = typeof result[key] === 'boolean' ? result[key] : null;
          }
        };
        while (true) {
          const part = await reader.read();
          if (meta.finished) return;
          if (part.done) break;
          bytes += part.value.byteLength;
          if (bytes > 2_000_000) fail('size_exceeded');
          try { pending += decoder.decode(part.value, {stream: true}); }
          catch { fail('invalid_utf8'); }
          // Keep a trailing CR until its possible LF arrives in the next chunk.
          pending = pending.replace(/\r\n/g, '\n');
          let end;
          while ((end = pending.indexOf('\n\n')) !== -1) {
            frame(pending.slice(0, end));
            pending = pending.slice(end + 2);
          }
        }
        try { pending += decoder.decode(); }
        catch { fail('invalid_utf8'); }
        if (pending.trim()) frame(pending.replace(/\r\n/g, '\n'));
        meta.eof = true;
      };
      await Promise.race([read(), new Promise((_, reject) => {
        timer = setTimeout(() => reject({inspectionKind: 'inspection_timeout'}), 30_000);
      })]);
    } catch (error) {
      meta.inspection_error = ['clone_failed','missing_body','invalid_json','invalid_envelope','size_exceeded','invalid_utf8','frame_count_exceeded','reply_size_exceeded','inspection_timeout'].includes(error?.inspectionKind)
        ? error.inspectionKind : 'read_failed';
      if (reader) reader.cancel().catch(() => {});
    } finally {
      clearTimeout(timer);
      meta.finished = true;
      try { reader?.releaseLock(); } catch {}
    }
  }
  window.fetch = function(input, init) {
    let url, method;
    try {
      url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
      method = (init?.method || input?.method || 'GET').toUpperCase();
    } catch { return original.apply(this, arguments); }
    if (url.origin !== location.origin || !paths.has(url.pathname) || method !== 'POST') return original.apply(this, arguments);
    if (state.records.length >= 32) {
      state.overflowed = true;
      return original.apply(this, arguments);
    }
    const meta = {path: url.pathname, status: null, is_sse: false, types: [], done_count: 0,
      error_count: 0, nonempty_reply: false, reply: '', phase: null, graded: null,
      unavailable: null, refused: null, eof: false, finished: false, inspection_error: null};
    state.records.push(meta);
    return original.apply(this, arguments).then(response => {
      meta.status = response.status;
      meta.is_sse = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase() === 'text/event-stream';
      void inspect(response, meta);
      return response;
    }, error => {
      meta.finished = true;
      meta.inspection_error = 'fetch_failed';
      throw error;
    });
  };
})();`;

export type LoopStreamTicket = { index: number; path: string };
export type LoopStreamMetadata = Omit<CapturedTurn, "reply"> & { reply_matches: boolean[] };

/** Shared strict gate, also exercised against synthetic failures in unit tests. */
export function loopStreamCompleted(row: LoopStreamMetadata, expectedReplyParts: number): boolean {
  return row.status === 200 && row.is_sse && row.finished && row.eof && row.inspection_error === null &&
    row.done_count === 1 && row.types.filter((type) => type === "done").length === 1 &&
    row.types.at(-1) === "done" && row.error_count === 0 && !row.types.includes("error") &&
    row.nonempty_reply && expectedReplyParts > 0 && row.reply_matches.length === expectedReplyParts && row.reply_matches.every(Boolean);
}

/** Take the next capture index before the ordinary UI action. */
export async function markLoopStream(page: Page, path: string): Promise<LoopStreamTicket> {
  const index = await page.evaluate(() => {
    const state = window.__saplingTestLoopStreams;
    if (!state || state.overflowed || state.records.length >= 32) throw new Error("Loop stream observer is unavailable or full");
    return state.records.length;
  });
  return { index, path };
}

/** No Response.finished/body/text/CDP calls: the clone must reach actual EOF. */
export async function readLoopStream(page: Page, ticket: LoopStreamTicket, replyParts: string[]) {
  await page.waitForFunction(({ index }) => {
    const state = window.__saplingTestLoopStreams;
    return state?.overflowed || state?.records[index]?.finished;
  }, ticket, { timeout: 30_000 });
  return page.evaluate(({ index, path, replyParts }) => {
    const state = window.__saplingTestLoopStreams;
    const row = state?.records[index];
    if (!state || state.overflowed || !row || row.path !== path) throw new Error("Missing or mismatched loop stream capture");
    const { reply, ...metadata } = row;
    return { ...metadata, reply_matches: replyParts.map((part) => reply.includes(part)) };
  }, { ...ticket, replyParts });
}
