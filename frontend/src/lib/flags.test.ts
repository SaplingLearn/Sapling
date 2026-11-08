import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchJSON = vi.fn();
vi.mock("@/lib/api", () => ({ fetchJSON: (...a: unknown[]) => fetchJSON(...a) }));

import { fetchFlags } from "./flags";

describe("fetchFlags", () => {
  beforeEach(() => fetchJSON.mockReset());

  it("returns the flag map", async () => {
    fetchJSON.mockResolvedValue({ flags: { hide_quiz: "on" } });
    await expect(fetchFlags()).resolves.toEqual({ hide_quiz: "on" });
  });

  it("throws on a degraded answer, whose all-'off' map would un-hide features (#771)", async () => {
    fetchJSON.mockResolvedValue({ flags: { hide_quiz: "off" }, degraded: true });
    await expect(fetchFlags()).rejects.toThrow();
  });
});
