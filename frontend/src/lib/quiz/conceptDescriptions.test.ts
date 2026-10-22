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
    expect(cachedDescription("Recursion", "CS101")).toBeNull();

    await expect(loadDescription("u1", "Recursion", "CS101")).resolves.toBe("Recursion is self-reference.");
    expect(cachedDescription("recursion", "cs101")).toBe("Recursion is self-reference.");

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
    expect(cachedDescription("Kernel", "MATH210")).toBe("Null space.");
    expect(cachedDescription("Kernel", "CS350")).toBe("OS core.");
  });

  it("rejects a blank answer and remembers nothing, so the next ask retries", async () => {
    api.describeConcept.mockResolvedValueOnce("   ").mockResolvedValueOnce("Second try.");
    await expect(loadDescription("u1", "Vectors")).rejects.toThrow();
    expect(cachedDescription("Vectors")).toBeNull();
    await expect(loadDescription("u1", "Vectors")).resolves.toBe("Second try.");
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
