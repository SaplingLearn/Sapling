import { describe, it, expect } from "vitest";
import {
  hasStatsStrip, heroBackground, isPrivateProfile, prettyUrl, sortRolesByPriority, studiesOf,
} from "./profileViewHelpers";
import type { Cosmetic, Role, UserProfile, UserRole } from "@/lib/types";

function banner(over: Partial<Cosmetic>): Cosmetic {
  return { id: "b", type: "banner" as Cosmetic["type"], name: "B", slug: "b", rarity: "rare" as Cosmetic["rarity"], ...over };
}

function userRole(id: string, display_priority: number | undefined): UserRole {
  return {
    role: { id, display_priority } as unknown as Role,
    granted_at: "",
  };
}

type Stats = UserProfile["stats"];

describe("heroBackground", () => {
  it("is the plain panel without a banner, or with a banner lacking an asset", () => {
    expect(heroBackground(undefined)).toBe("var(--bg-panel)");
    expect(heroBackground(banner({ css_value: "red" }))).toBe("var(--bg-panel)");
  });

  it("tints with the banner color, falling back to the accent", () => {
    expect(heroBackground(banner({ asset_url: "/b.png", css_value: "red" }))).toBe(
      "linear-gradient(135deg, color-mix(in oklab, red 35%, var(--bg-panel)) 0%, var(--bg-panel) 100%)",
    );
    expect(heroBackground(banner({ asset_url: "/b.png" }))).toBe(
      "linear-gradient(135deg, color-mix(in oklab, var(--accent) 35%, var(--bg-panel)) 0%, var(--bg-panel) 100%)",
    );
  });
});

describe("sortRolesByPriority", () => {
  it("orders highest priority first, missing as 0, without mutating the input", () => {
    const roles = [userRole("low", 1), userRole("none", undefined), userRole("high", 9), userRole("neg", -1)];
    expect(sortRolesByPriority(roles).map((r) => r.role.id)).toEqual(["high", "low", "none", "neg"]);
    expect(roles.map((r) => r.role.id)).toEqual(["low", "none", "high", "neg"]);
  });

  it("treats missing roles as none", () => {
    expect(sortRolesByPriority(undefined)).toEqual([]);
  });
});

describe("studiesOf", () => {
  it("lists majors then minors, skipping empty or missing groups", () => {
    expect(studiesOf({ majors: ["CS"], minors: ["Music"] })).toEqual([
      { label: "Majors", values: ["CS"] },
      { label: "Minors", values: ["Music"] },
    ]);
    expect(studiesOf({ majors: [], minors: ["Music"] })).toEqual([{ label: "Minors", values: ["Music"] }]);
    expect(studiesOf({ majors: undefined as unknown as string[], minors: [] })).toEqual([]);
  });
});

describe("hasStatsStrip", () => {
  it("needs a streak or session count, even a zero one", () => {
    expect(hasStatsStrip({})).toBe(false);
    expect(hasStatsStrip({ documents_count: 3, achievements_count: 1 })).toBe(false);
    expect(hasStatsStrip({ streak_count: 0 })).toBe(true);
    expect(hasStatsStrip({ session_count: 0 })).toBe(true);
  });
});

describe("isPrivateProfile", () => {
  it("is private when stats are missing or empty", () => {
    expect(isPrivateProfile(undefined)).toBe(true);
    expect(isPrivateProfile(null as unknown as Stats)).toBe(true);
    expect(isPrivateProfile({} as Stats)).toBe(true);
    expect(isPrivateProfile({ session_count: 0 } as Stats)).toBe(false);
  });
});

describe("prettyUrl", () => {
  it("drops the scheme, a leading www. and a bare root path", () => {
    expect(prettyUrl("https://www.example.com/me")).toBe("example.com/me");
    expect(prettyUrl("https://example.com/")).toBe("example.com");
    expect(prettyUrl("http://sub.example.com")).toBe("sub.example.com");
  });

  it("returns an unparsable URL unchanged", () => {
    expect(prettyUrl("not a url")).toBe("not a url");
  });
});
