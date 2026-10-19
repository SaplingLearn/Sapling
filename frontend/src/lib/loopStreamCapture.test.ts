/** Synthetic fetch/streams only: no browser, server, model, DB, or real learner. */
import { runInNewContext } from "node:vm";
import type { Page } from "@playwright/test";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LOOP_STREAM_CAPTURE_SCRIPT, loopStreamCompleted, markLoopStream, readLoopStream } from "../../e2e/support/loop-streams";

const PATH = "/api/learn/loop/chat/stream";
const frame = (type: string, data: unknown = {}) => `event: ${type}\r\ndata: ${JSON.stringify({ type, data })}\r\n\r\n`;
const reply = "SYNTHETIC_PRIVATE_REPLY";
const done = () => frame("done", { reply, phase: "feedback", graded: true, unavailable: false, refused: false });
type State = NonNullable<Window["__saplingTestLoopStreams"]>;
type Surface = { fetch: typeof fetch; __saplingTestLoopStreams?: State };

function install(original: typeof fetch, timers = { setTimeout, clearTimeout }) {
  const surface: Surface = { fetch: original };
  const scope = { window: surface, location: { href: "https://synthetic.test/learn", origin: "https://synthetic.test" }, URL, TextDecoder, ...timers };
  runInNewContext(LOOP_STREAM_CAPTURE_SCRIPT, scope);
  return { surface, scope, state: surface.__saplingTestLoopStreams! };
}

function response(body: string, status = 200, contentType = "text/event-stream; charset=utf-8") {
  return new Response(body, { status, headers: { "Content-Type": contentType } });
}

async function settle(state: State) {
  for (let index = 0; index < 200 && state.records.some((record) => !record.finished); index++) await new Promise(setImmediate);
  expect(state.records.every((record) => record.finished)).toBe(true);
}

afterEach(() => vi.unstubAllGlobals());

describe("test-only fetch clone completion observer", () => {
  it("returns the exact original response immediately and preserves complete application bytes", async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const first = frame("token", { delta: "SYNTHETIC_PRIVATE_TOKEN" });
    const body = first + done();
    const originalResponse = new Response(new ReadableStream<Uint8Array>({
      async start(controller) {
        const bytes = new TextEncoder().encode(body);
        // Split between CR and LF to exercise incremental framing.
        const split = first.length - 1;
        controller.enqueue(bytes.slice(0, split));
        await held;
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    }), { headers: { "Content-Type": "text/event-stream" } });
    const original = vi.fn().mockResolvedValue(originalResponse);
    const { surface, state } = install(original);
    const options = { method: "POST" };
    const received = await surface.fetch(PATH, options);
    expect(received).toBe(originalResponse);
    expect(original).toHaveBeenCalledExactlyOnceWith(PATH, options);
    expect(state.records[0].finished).toBe(false);
    const applicationBody = received.text();
    release();
    expect(await applicationBody).toBe(body);
    await settle(state);
    expect(state.records[0]).toMatchObject({ types: ["token", "done"], done_count: 1, error_count: 0, nonempty_reply: true, eof: true, finished: true, inspection_error: null, graded: true, unavailable: false, refused: false, phase: "feedback" });
    expect(loopStreamCompleted({ ...state.records[0], reply_matches: [true] }, 1)).toBe(true);
  });

  it.each([
    ["HTTP200 error", frame("error", { message: "SYNTHETIC_PRIVATE_ERROR" }), { error_count: 1, done_count: 0 }],
    ["truncated without done", frame("token", { delta: "partial" }), { error_count: 0, done_count: 0 }],
    ["duplicate done", done() + done(), { done_count: 2 }],
    ["event after done", done() + frame("token", { delta: "late" }), { types: ["done", "token"] }],
    ["error after done", done() + frame("error"), { done_count: 1, error_count: 1 }],
    ["empty reply", frame("done", { reply: "   " }), { nonempty_reply: false }],
    ["missing reply", frame("done", {}), { nonempty_reply: false }],
  ])("faithfully exposes %s instead of certifying HTTP success", async (_name, body, fields) => {
    const { surface, state } = install(vi.fn().mockResolvedValue(response(body as string)));
    await (await surface.fetch(PATH, { method: "POST" })).text();
    await settle(state);
    expect(state.records[0]).toMatchObject(fields);
    expect(loopStreamCompleted({ ...state.records[0], reply_matches: [true] }, 1)).toBe(false);
  });

  it.each([
    ["JSON", "event: done\ndata: NOT_JSON\n\n", "invalid_json"],
    ["mismatched event", "event: done\ndata: {\"type\":\"token\"}\n\n", "invalid_envelope"],
    ["missing event", "data: {\"type\":\"done\",\"data\":{}}\n\n", "invalid_envelope"],
    ["unknown event", frame("invented"), "invalid_envelope"],
    ["invalid done data", frame("done", []), "invalid_envelope"],
    ["reply bound", frame("done", { reply: "x".repeat(8193) }), "reply_size_exceeded"],
    ["byte bound", "x".repeat(2_000_001), "size_exceeded"],
    ["frame bound", frame("token").repeat(2049), "frame_count_exceeded"],
  ])("fails malformed or oversized inspection without changing application data (%s)", async (_name, body, error) => {
    const { surface, state } = install(vi.fn().mockResolvedValue(response(body)));
    expect(await (await surface.fetch(PATH, { method: "POST" })).text()).toBe(body);
    await settle(state);
    expect(state.records[0].inspection_error).toBe(error);
    expect(state.records[0].eof).toBe(false);
    expect(loopStreamCompleted({ ...state.records[0], reply_matches: [true] }, 1)).toBe(false);
  });

  it("rejects invalid UTF8 while leaving the application response untouched", async () => {
    const bytes = new Uint8Array([0xff, 0xfe]);
    const originalResponse = new Response(bytes);
    const { surface, state } = install(vi.fn().mockResolvedValue(originalResponse));
    expect(new Uint8Array(await (await surface.fetch(PATH, { method: "POST" })).arrayBuffer())).toEqual(bytes);
    await settle(state);
    expect(state.records[0].inspection_error).toBe("invalid_utf8");
  });

  it("decodes a UTF8 reply split across individual bytes and recognizes the check-answer path", async () => {
    const body = frame("done", { reply: "SYNTHETIC naïve 数", graded: true });
    const bytes = new TextEncoder().encode(body);
    const originalResponse = new Response(new ReadableStream<Uint8Array>({
      start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close(); },
    }), { headers: { "Content-Type": "text/event-stream" } });
    const original = vi.fn().mockResolvedValue(originalResponse);
    const { surface, state } = install(original);
    const request = new Request("https://synthetic.test/api/learn/loop/check/answer/stream", { method: "POST", body: "SYNTHETIC_REQUEST_NOT_INSPECTED" });
    expect(await (await surface.fetch(request)).text()).toBe(body);
    await settle(state);
    expect(original).toHaveBeenCalledExactlyOnceWith(request);
    expect(state.records[0]).toMatchObject({ path: "/api/learn/loop/check/answer/stream", eof: true, nonempty_reply: true, inspection_error: null });
    expect(JSON.stringify(state)).not.toContain("SYNTHETIC_REQUEST_NOT_INSPECTED");
  });

  it("exposes an underlying stream read failure without replacing the app's error", async () => {
    const error = new Error("SYNTHETIC_PRIVATE_READ_ERROR");
    const originalResponse = new Response(new ReadableStream({ start(controller) { controller.error(error); } }));
    const { surface, state } = install(vi.fn().mockResolvedValue(originalResponse));
    const received = await surface.fetch(PATH, { method: "POST" });
    expect(received).toBe(originalResponse);
    await expect(received.text()).rejects.toBe(error);
    await settle(state);
    expect(state.records[0]).toMatchObject({ eof: false, inspection_error: "read_failed" });
    expect(JSON.stringify(state)).not.toContain(error.message);
  });

  it("requires actual EOF even if a valid done frame arrived", async () => {
    let finish!: () => void;
    const originalResponse = new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(done()));
        finish = () => controller.close();
      },
    }), { headers: { "Content-Type": "text/event-stream" } });
    const { surface, state } = install(vi.fn().mockResolvedValue(originalResponse));
    const original = await surface.fetch(PATH, { method: "POST" });
    for (let index = 0; index < 200 && state.records[0].done_count === 0; index++) await new Promise(setImmediate);
    expect(state.records[0]).toMatchObject({ done_count: 1, eof: false, finished: false });
    expect(loopStreamCompleted({ ...state.records[0], reply_matches: [true] }, 1)).toBe(false);
    finish();
    await original.text();
    await settle(state);
    expect(state.records[0].eof).toBe(true);
  });

  it("bounds a stalled clone and cancels only its branch", async () => {
    let timedOut!: () => void;
    let finish!: () => void;
    const originalResponse = new Response(new ReadableStream<Uint8Array>({
      start(controller) { finish = () => { controller.enqueue(new TextEncoder().encode(done())); controller.close(); }; },
    }), { headers: { "Content-Type": "text/event-stream" } });
    const timers = { setTimeout: ((callback: () => void) => { timedOut = callback; return 1; }) as unknown as typeof setTimeout, clearTimeout: vi.fn() as unknown as typeof clearTimeout };
    const { surface, state } = install(vi.fn().mockResolvedValue(originalResponse), timers);
    const received = await surface.fetch(PATH, { method: "POST" });
    timedOut();
    await settle(state);
    expect(state.records[0]).toMatchObject({ inspection_error: "inspection_timeout", eof: false });
    finish();
    expect(await received.text()).toBe(done());
    expect(state.records[0].eof).toBe(false); // Late clone settlement cannot turn a timeout into success.
  });

  it.each([
    ["https://elsewhere.test" + PATH, "POST"],
    ["https://synthetic.test.evil.test" + PATH, "POST"],
    ["/api/learn/loop/close", "POST"],
    [PATH + "/extra", "POST"],
    [PATH, "GET"],
  ])("ignores unrelated origin/path/method %s %s", async (url, method) => {
    const originalResponse = response(done());
    const original = vi.fn().mockResolvedValue(originalResponse);
    const { surface, state } = install(original);
    expect(await surface.fetch(url, { method })).toBe(originalResponse);
    expect(state.records).toEqual([]);
    expect(original).toHaveBeenCalledTimes(1);
  });

  it("preserves a fetch rejection identity and records a failed inspection", async () => {
    const error = new Error("SYNTHETIC_PRIVATE_FETCH_ERROR");
    const { surface, state } = install(vi.fn().mockRejectedValue(error));
    await expect(surface.fetch(PATH, { method: "POST" })).rejects.toBe(error);
    expect(state.records[0]).toMatchObject({ finished: true, eof: false, inspection_error: "fetch_failed" });
    expect(JSON.stringify(state)).not.toContain(error.message);
  });

  it("records HTTP/content type failure and rejects a missing body", async () => {
    const { surface, state } = install(vi.fn().mockResolvedValue(response(done(), 503, "application/json")));
    await (await surface.fetch(PATH, { method: "POST" })).text();
    await settle(state);
    expect(state.records[0]).toMatchObject({ status: 503, is_sse: false });
    const missing = install(vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await missing.surface.fetch(PATH, { method: "POST" });
    await settle(missing.state);
    expect(missing.state.records[0].inspection_error).toBe("missing_body");
  });

  it("installs once and bounds capture count without blocking original requests", async () => {
    const original = vi.fn().mockImplementation(async () => response(done()));
    const { surface, state, scope } = install(original);
    const wrapped = surface.fetch;
    runInNewContext(LOOP_STREAM_CAPTURE_SCRIPT, scope);
    expect(surface.fetch).toBe(wrapped);
    for (let index = 0; index < 33; index++) await (await surface.fetch(PATH, { method: "POST" })).text();
    await settle(state);
    expect(original).toHaveBeenCalledTimes(33);
    expect(state.records).toHaveLength(32);
    expect(state.overflowed).toBe(true);
  });

  it("exports strict metadata/reply comparisons without protocol response calls or raw text", async () => {
    const { surface, state } = install(vi.fn().mockResolvedValue(response(done())));
    vi.stubGlobal("window", surface);
    const fakePage = {
      evaluate: async (fn: (arg: unknown) => unknown, arg: unknown) => fn(arg),
      waitForFunction: async (fn: (arg: unknown) => unknown, arg: unknown) => { await settle(state); expect(fn(arg)).toBe(true); },
    } as unknown as Page;
    const ticket = await markLoopStream(fakePage, PATH);
    await (await surface.fetch(PATH, { method: "POST" })).text();
    const metadata = await readLoopStream(fakePage, ticket, [reply, "absent"]);
    expect(metadata).toMatchObject({ eof: true, done_count: 1, graded: true, reply_matches: [true, false] });
    expect(JSON.stringify(metadata)).not.toContain(reply);
    expect(metadata).not.toHaveProperty("reply");
    expect(loopStreamCompleted(metadata, 2)).toBe(false); // One expected reply part did not match.
  });
});
