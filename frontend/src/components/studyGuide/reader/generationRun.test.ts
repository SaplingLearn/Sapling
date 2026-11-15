/**
 * writeGuide's waits on a guide another run holds: each one leaves nothing
 * on the run's signal once it is over. The flows themselves are pinned
 * through the reader in GuideReader.generation.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/studyGuide/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/studyGuide/api")>()),
  generateGuide: vi.fn(),
  getGuide: vi.fn(),
}));

import { generateGuide, getGuide } from "@/lib/studyGuide/api";

import { RETRY_MS, writeGuide } from "./generationRun";
import { fixtureGuide } from "./readerFixture";

const held = () => Object.assign(new Error("Another run is writing this guide."), { status: 409 });
const abortListeners = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.filter(([type]) => type === "abort").length;

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("waiting on a guide another run holds", () => {
  it("takes its abort listener off the signal when each wait ends", async () => {
    const finished = fixtureGuide();
    vi.mocked(generateGuide).mockRejectedValueOnce(held()).mockRejectedValueOnce(held()).mockResolvedValueOnce(finished);
    vi.mocked(getGuide).mockResolvedValue(fixtureGuide({ status: "generating" }));
    const { signal } = new AbortController();
    const added = vi.spyOn(signal, "addEventListener");
    const removed = vi.spyOn(signal, "removeEventListener");

    const run = writeGuide({ userId: "u1", guideId: "g1", mode: "resume", handlers: { signal }, onHeld: () => {} });
    await vi.advanceTimersByTimeAsync(RETRY_MS * 2);

    await expect(run).resolves.toBe(finished);
    expect(abortListeners(added)).toBe(2);
    expect(abortListeners(removed)).toBe(2);
  });

  it("still stops at once when the run is aborted while it waits", async () => {
    vi.mocked(generateGuide).mockRejectedValue(held());
    vi.mocked(getGuide).mockResolvedValue(fixtureGuide({ status: "generating" }));
    const controller = new AbortController();

    const run = writeGuide({ userId: "u1", guideId: "g1", mode: "resume", handlers: { signal: controller.signal }, onHeld: () => {} });
    const outcome = run.then(() => "resolved", () => "rejected");
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();

    await expect(outcome).resolves.toBe("rejected");
    expect(generateGuide).toHaveBeenCalledTimes(1);
  });
});
