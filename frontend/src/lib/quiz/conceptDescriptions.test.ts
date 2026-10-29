// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ describeConcept: vi.fn() }));
vi.mock("./api", () => api);

import { cachedDescription, loadDescription } from "./conceptDescriptions";

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("conceptDescriptions", () => {
  it("fetches once, remembers, and answers from memory after", async () => {
    api.describeConcept.mockResolvedValue("  Recursion is self-reference.  ");
    expect(cachedDescription("u1", "Recursion", "CS101")).toBeNull();

    await expect(loadDescription("u1", "Recursion", "CS101")).resolves.toBe("Recursion is self-reference.");
    expect(cachedDescription("u1", "recursion", "cs101")).toBe("Recursion is self-reference.");

    await loadDescription("u1", "Recursion", "CS101");
    expect(api.describeConcept).toHaveBeenCalledTimes(1);
  });

  it("shares one request between concurrent asks", async () => {
    let resolve!: (t: string) => void;
    api.describeConcept.mockReturnValue(new Promise<string>(r => (resolve = r)));
    const a = loadDescription("u1", "Matrices", "MATH210");
    const b = loadDescription("u1", "Matrices", "MATH210");
    resolve("Rectangular arrays.");
    await expect(Promise.all([a, b])).resolves.toEqual(["Rectangular arrays.", "Rectangular arrays."]);
    expect(api.describeConcept).toHaveBeenCalledTimes(1);
  });

  it("keys on the course label too", async () => {
    api.describeConcept.mockResolvedValueOnce("Null space.").mockResolvedValueOnce("OS core.");
    await loadDescription("u1", "Kernel", "MATH210");
    await loadDescription("u1", "Kernel", "CS350");
    expect(cachedDescription("u1", "Kernel", "MATH210")).toBe("Null space.");
    expect(cachedDescription("u1", "Kernel", "CS350")).toBe("OS core.");
  });

  it("rejects a blank answer and remembers nothing, so the next ask retries", async () => {
    api.describeConcept.mockResolvedValueOnce("   ").mockResolvedValueOnce("Second try.");
    await expect(loadDescription("u1", "Vectors")).rejects.toThrow();
    expect(cachedDescription("u1", "Vectors")).toBeNull();
    await expect(loadDescription("u1", "Vectors")).resolves.toBe("Second try.");
  });

  it("keeps one student's descriptions out of another's", async () => {
    api.describeConcept.mockResolvedValue("Private course note.");
    await loadDescription("u1", "Thesis topic", "HIST400");
    expect(cachedDescription("u1", "Thesis topic", "HIST400")).toBe("Private course note.");
    expect(cachedDescription("u2", "Thesis topic", "HIST400")).toBeNull();
  });

  it("forgets a description after 30 days", async () => {
    api.describeConcept.mockResolvedValue("Fresh.");
    await loadDescription("u1", "Entropy", "PHYS101");
    const now = Date.now();
    const spy = vi.spyOn(Date, "now").mockReturnValue(now + 31 * 24 * 60 * 60 * 1000);
    expect(cachedDescription("u1", "Entropy", "PHYS101")).toBeNull();
    spy.mockRestore();
  });

  it("clears the old unkeyed store", async () => {
    // Module state: the first read of this test file already cleared it, so
    // this pins the end state rather than the moment of removal.
    window.localStorage.setItem("sapling_concept_descriptions_v1", "{}");
    vi.resetModules();
    const fresh = await import("./conceptDescriptions");
    fresh.cachedDescription("u1", "Anything");
    expect(window.localStorage.getItem("sapling_concept_descriptions_v1")).toBeNull();
  });

  it("still describes when storage is unavailable", async () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    api.describeConcept.mockResolvedValue("Works anyway.");
    await expect(loadDescription("u1", "Algorithms")).resolves.toBe("Works anyway.");
    spy.mockRestore();
  });
});
