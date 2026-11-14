/**
 * `generateGuide` over a stubbed event stream: what each event does, how the
 * stream ends, and what a failure looks like to the reader.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/sse", () => ({ streamSSE: vi.fn() }));

import { streamSSE } from "@/lib/sse";

import { generateGuide, GuideGenerationError } from "./api";
import type { GuideContent, GuideDetail, Section } from "./types";

const stream = vi.mocked(streamSSE);

/** The stream yields these events' payloads in order, then closes. */
function streams(...payloads: unknown[]) {
  stream.mockImplementation(async function* () {
    for (const data of payloads) yield { event: "message", data };
  } as typeof streamSSE);
}

const event = (type: string, step: string, message: string, data?: unknown) => ({ type, step, message, data });

const CONTENT = { title: "Loops", sections: [] } as unknown as GuideContent;
const SECTION = { id: "s1", title: "Loops", status: "written" } as unknown as Section;
const GUIDE = { id: "g1", status: "ready" } as unknown as GuideDetail;
const DONE = event("done", "done", "Guide ready", { guide: GUIDE });

function handlers() {
  return { onStatus: vi.fn(), onOutline: vi.fn(), onSection: vi.fn() };
}

/** The error a run rejects with. */
async function failure(run: Promise<unknown>): Promise<GuideGenerationError> {
  const err = await run.then(
    () => null,
    (reason: unknown) => reason,
  );
  expect(err).toBeInstanceOf(GuideGenerationError);
  return err as GuideGenerationError;
}

beforeEach(() => vi.resetAllMocks());

describe("generateGuide", () => {
  it("posts the mode to the guide's generate route, as the signed-in student", async () => {
    streams(DONE);
    const { signal } = new AbortController();
    await generateGuide("u 1", "g/1", "update", { signal });

    const [url, init, options] = stream.mock.calls[0];
    expect(url).toMatch(/\/api\/study-guide\/u%201\/guides\/g%2F1\/generate$/);
    expect(init).toMatchObject({ method: "POST", credentials: "include", signal });
    expect(JSON.parse(init.body as string)).toEqual({ mode: "update" });
    // A dead stream is cut; a slow one is not.
    expect(options?.idleTimeoutMs).toBeGreaterThanOrEqual(60_000);
  });

  it("hands each event to its handler, in order, and resolves with the finished guide", async () => {
    streams(
      event("status", "read", "Reading your 3 materials", { step: 1, total: 4 }),
      event("progress", "outline", "Outline ready", { content: CONTENT }),
      event("status", "section", "Writing section 1 of 1: Loops", { step: 3, total: 4 }),
      event("progress", "section", "Loops", { section: SECTION }),
      DONE,
    );
    const given = handlers();

    await expect(generateGuide("u1", "g1", "resume", given)).resolves.toBe(GUIDE);

    expect(given.onStatus.mock.calls).toEqual([
      ["Reading your 3 materials", { step: 1, total: 4 }],
      ["Writing section 1 of 1: Loops", { step: 3, total: 4 }],
    ]);
    expect(given.onOutline).toHaveBeenCalledExactlyOnceWith(CONTENT);
    expect(given.onSection).toHaveBeenCalledExactlyOnceWith(SECTION);
    expect(given.onOutline.mock.invocationCallOrder[0]).toBeLessThan(given.onSection.mock.invocationCallOrder[0]);
  });

  it("stops reading at `done`, ignores a progress step it does not know, and needs no handlers", async () => {
    streams(event("progress", "later", "Something newer", { extra: true }), DONE, event("status", "x", "After the end", {}));
    const given = handlers();
    await expect(generateGuide("u1", "g1", "resume", given)).resolves.toBe(GUIDE);
    expect(given.onStatus).not.toHaveBeenCalled();
    expect(given.onOutline).not.toHaveBeenCalled();

    streams(event("status", "read", "Reading", { step: 1, total: 2 }), DONE);
    await expect(generateGuide("u1", "g1", "resume")).resolves.toBe(GUIDE);
  });

  it("resolves with no guide at a `done` without one: the run saved it but could not read it back", async () => {
    streams(event("done", "done", "Guide ready", { guide: null }), event("status", "x", "After the end", {}));
    const given = handlers();
    await expect(generateGuide("u1", "g1", "regenerate", given)).resolves.toBeNull();
    expect(given.onStatus).not.toHaveBeenCalled();
  });

  it("rejects with the stream's error and whether trying again can help", async () => {
    streams(event("error", "error", "You are out of AI credit for today.", { retryable: false }), DONE);
    const refused = await failure(generateGuide("u1", "g1", "regenerate"));
    expect(refused.message).toBe("You are out of AI credit for today.");
    expect(refused.retryable).toBe(false);

    streams(event("error", "error", "The guide could not be written.", { retryable: true }));
    expect((await failure(generateGuide("u1", "g1", "resume"))).retryable).toBe(true);
  });

  it("carries the error's code when the server sends one", async () => {
    streams(event("error", "error", "Another tab is writing this guide.", { retryable: true, code: "busy" }));
    expect((await failure(generateGuide("u1", "g1", "resume"))).code).toBe("busy");

    streams(event("error", "error", "The guide could not be written.", { retryable: true }));
    expect((await failure(generateGuide("u1", "g1", "resume"))).code).toBeNull();
  });

  it("treats an error that does not say as one worth retrying, and words one with no message", async () => {
    streams(event("error", "error", "", null));
    const err = await failure(generateGuide("u1", "g1", "resume"));
    expect(err.retryable).toBe(true);
    expect(err.message).toBe("The guide could not be written.");
  });

  it("rejects when the stream closes without `done`", async () => {
    streams(event("progress", "outline", "Outline ready", { content: CONTENT }));
    const given = handlers();
    const err = await failure(generateGuide("u1", "g1", "resume", given));
    expect(err.message).toBe("The connection dropped before the guide was finished. Retry picks up where it stopped.");
    expect(err.retryable).toBe(true);
    // What arrived before the cut was still handed on.
    expect(given.onOutline).toHaveBeenCalledWith(CONTENT);
  });

  it("lets a refused request through as it was thrown, status and all", async () => {
    // What streamSSE throws for a response that is not 2xx: the reader tells a 409 from a 422 by it.
    const held = Object.assign(new Error('{"detail":"Another request is writing this guide."}'), { status: 409 });
    const refused = { [Symbol.asyncIterator]: () => ({ next: () => Promise.reject(held) }) };
    stream.mockReturnValue(refused as unknown as ReturnType<typeof streamSSE>);
    await expect(generateGuide("u1", "g1", "resume")).rejects.toBe(held);
  });
});
