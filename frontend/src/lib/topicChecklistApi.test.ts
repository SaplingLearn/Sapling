import { afterEach, describe, expect, it, vi } from "vitest";
import { getTopicChecklist, refreshTopicChecklist, setTopicReviewed } from "./topicChecklistApi";

afterEach(() => vi.unstubAllGlobals());

describe("topic checklist requests", () => {
  it("uses the existing same-origin session transport and encodes identifiers/semester", async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    await getTopicChecklist("user/a", "CAS CS 111", "Fall 2026");
    expect(fetch).toHaveBeenLastCalledWith("/api/topic-checklist/user%2Fa/courses/CAS%20CS%20111?semester=Fall+2026", expect.objectContaining({ credentials: "include" }));
    await refreshTopicChecklist("u", "c", "Spring 2026");
    expect(fetch).toHaveBeenLastCalledWith("/api/topic-checklist/u/courses/c/refresh?semester=Spring+2026", expect.objectContaining({ method: "POST" }));
    await setTopicReviewed("u", "c", "topic/a", false, "Spring 2026");
    expect(fetch).toHaveBeenLastCalledWith("/api/topic-checklist/u/courses/c/topics/topic%2Fa?semester=Spring+2026", expect.objectContaining({ method: "PATCH", body: '{"checked":false}' }));
  });
});
