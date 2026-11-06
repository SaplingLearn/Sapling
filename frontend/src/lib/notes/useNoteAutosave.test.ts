// @vitest-environment jsdom
/**
 * The notetaker's autosave state machine (#768).
 *
 * Before this hook, the page kept `saved | unsaved | saving` in one slot:
 *   - a failed PATCH only logged, so the footer stuck on "Saving…" and the
 *     edit was dropped with no retry;
 *   - "Saved" was set when the pending-TIMER map was empty, not when nothing
 *     was in flight, so note A finishing while B's PATCH was in flight lied;
 *   - deleting a note with a queued edit let the flush effect PATCH the
 *     deleted note;
 *   - `flushSave` returned nothing, so generate-quiz / send-to-tutor could not
 *     wait for the latest body to land.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, cleanup } from "@testing-library/react";

vi.mock("@/lib/api", () => ({ patchNote: vi.fn() }));

import { patchNote } from "@/lib/api";
import { useNoteAutosave, AUTOSAVE_DEBOUNCE_MS, retryDelayMs } from "./useNoteAutosave";

const mockedPatch = vi.mocked(patchNote);

type Deferred = { resolve: () => void; reject: (e: unknown) => void };

/** Every PATCH call parks here until the test settles it. */
let calls: Deferred[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  mockedPatch.mockImplementation(
    () =>
      new Promise((resolve, reject) => {
        calls.push({ resolve: () => resolve({} as never), reject });
      }),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  mockedPatch.mockReset();
});

const setup = () => renderHook(() => useNoteAutosave("u1"));

async function settle(i: number, ok: boolean) {
  await act(async () => {
    if (ok) calls[i].resolve();
    else calls[i].reject(new Error("500"));
  });
}

describe("useNoteAutosave", () => {
  it("debounces edits into one merged PATCH and walks unsaved → saving → saved", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { title: "T" }));
    act(() => result.current.queue("a", { body: "B" }));
    expect(result.current.status).toBe("unsaved");
    expect(mockedPatch).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    expect(mockedPatch).toHaveBeenCalledTimes(1);
    expect(mockedPatch).toHaveBeenCalledWith("a", "u1", { title: "T", body: "B" }, { keepalive: false });
    expect(result.current.status).toBe("saving");

    await settle(0, true);
    expect(result.current.status).toBe("saved");
  });

  it("a failed save surfaces an error, keeps the edit, and retries it with backoff", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "keep me" }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    await settle(0, false);
    expect(result.current.status).toBe("error");

    // Nothing is re-sent before the backoff elapses…
    act(() => vi.advanceTimersByTime(retryDelayMs(1) - 1));
    expect(mockedPatch).toHaveBeenCalledTimes(1);
    // …then the SAME body is retried.
    act(() => vi.advanceTimersByTime(1));
    expect(mockedPatch).toHaveBeenCalledTimes(2);
    expect(mockedPatch.mock.calls[1][2]).toEqual({ body: "keep me" });
    expect(result.current.status).toBe("saving");

    await settle(1, true);
    expect(result.current.status).toBe("saved");
  });

  it("backoff grows and is capped", () => {
    expect(retryDelayMs(2)).toBeGreaterThan(retryDelayMs(1));
    expect(retryDelayMs(50)).toBe(retryDelayMs(51));
  });

  it("a newer edit made while a save was failing wins over the failed patch", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { title: "old", body: "old" }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    // Edit while the first PATCH is in flight.
    act(() => result.current.queue("a", { body: "new" }));
    await settle(0, false);

    // The next edit retries on the debounce, not the (longer) backoff.
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    expect(mockedPatch).toHaveBeenCalledTimes(2);
    expect(mockedPatch.mock.calls[1][2]).toEqual({ title: "old", body: "new" });
  });

  it("manual retry re-sends errored notes immediately", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "x" }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    await settle(0, false);
    expect(result.current.status).toBe("error");

    act(() => result.current.retry());
    expect(mockedPatch).toHaveBeenCalledTimes(2);
    await settle(1, true);
    expect(result.current.status).toBe("saved");
  });

  it("does not claim Saved while another note's save is still in flight", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "a" }));
    act(() => result.current.queue("b", { body: "b" }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    expect(mockedPatch).toHaveBeenCalledTimes(2);

    await settle(0, true); // A done, B still in flight.
    expect(result.current.status).toBe("saving");
    await settle(1, true);
    expect(result.current.status).toBe("saved");
  });

  it("an error on one note is not masked by another note saving fine", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "a" }));
    act(() => result.current.queue("b", { body: "b" }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    await settle(0, false);
    await settle(1, true);
    expect(result.current.status).toBe("error");
  });

  it("cancel drops a queued save so a deleted note is never PATCHed", () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "x" }));
    act(() => result.current.cancel("a"));
    expect(result.current.status).toBe("saved");
    act(() => vi.advanceTimersByTime(60_000));
    act(() => {
      void result.current.flush("a");
    });
    expect(mockedPatch).not.toHaveBeenCalled();
  });

  it("cancel returns the dropped patch so a failed delete can re-queue it", () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "x" }));
    let dropped: unknown;
    act(() => {
      dropped = result.current.cancel("a");
    });
    expect(dropped).toEqual({ body: "x" });
    act(() => result.current.queue("a", dropped as { body: string }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    expect(mockedPatch).toHaveBeenCalledWith("a", "u1", { body: "x" }, { keepalive: false });
  });

  it("cancel ignores the outcome of a save already in flight (no error, no retry)", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "x" }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    act(() => result.current.cancel("a"));
    await settle(0, false); // the 404 from PATCHing a deleted note
    expect(result.current.status).toBe("saved");
    act(() => vi.advanceTimersByTime(60_000));
    expect(mockedPatch).toHaveBeenCalledTimes(1);
  });

  it("flush sends now and resolves true once the PATCH lands", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "latest" }));
    let done: boolean | undefined;
    act(() => {
      void result.current.flush("a").then((ok) => (done = ok));
    });
    expect(mockedPatch).toHaveBeenCalledTimes(1);
    expect(done).toBeUndefined();
    await settle(0, true);
    expect(done).toBe(true);
  });

  it("flush resolves false when the save fails", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "latest" }));
    let done: boolean | undefined;
    act(() => {
      void result.current.flush("a").then((ok) => (done = ok));
    });
    await settle(0, false);
    expect(done).toBe(false);
  });

  it("flush waits for an in-flight save, then sends edits queued behind it", async () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "one" }));
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    act(() => result.current.queue("a", { body: "two" }));
    let done: boolean | undefined;
    act(() => {
      void result.current.flush("a").then((ok) => (done = ok));
    });
    // Never two PATCHes for one note in flight at once.
    expect(mockedPatch).toHaveBeenCalledTimes(1);
    await settle(0, true);
    expect(mockedPatch).toHaveBeenCalledTimes(2);
    expect(mockedPatch.mock.calls[1][2]).toEqual({ body: "two" });
    expect(done).toBeUndefined();
    await settle(1, true);
    expect(done).toBe(true);
  });

  it("flush with nothing queued resolves true without a request", async () => {
    const { result } = setup();
    await expect(result.current.flush("a")).resolves.toBe(true);
    expect(mockedPatch).not.toHaveBeenCalled();
  });

  it("flushAll passes keepalive through (pagehide)", () => {
    const { result } = setup();
    act(() => result.current.queue("a", { body: "x" }));
    act(() => {
      void result.current.flushAll(true);
    });
    expect(mockedPatch).toHaveBeenCalledWith("a", "u1", { body: "x" }, { keepalive: true });
  });

  it("a failure after unmount does not schedule background retries", async () => {
    const { result, unmount } = setup();
    act(() => result.current.queue("a", { body: "x" }));
    act(() => {
      void result.current.flushAll();
    });
    unmount();
    await act(async () => calls[0].reject(new Error("500")));
    vi.advanceTimersByTime(120_000);
    expect(mockedPatch).toHaveBeenCalledTimes(1);
  });
});
