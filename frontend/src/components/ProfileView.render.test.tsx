// @vitest-environment jsdom
/**
 * Characterization of `ProfileView`'s rendered output (everything except the
 * add-friend action, which ProfileView.friends.test.tsx owns): the hero
 * (name/username/roles/bio/meta/website, banner background), the stats
 * strip, fields of study, featured achievements, the private notice and the
 * embedded padding. The viewer is the profile's owner, so AddFriendAction
 * renders nothing and fetches nothing.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1" }),
}));
vi.mock("./ToastProvider", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("./Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));
vi.mock("@/lib/api", () => ({
  fetchFriends: vi.fn(),
  fetchFriendRequests: vi.fn(),
  sendFriendRequest: vi.fn(),
  acceptFriendRequest: vi.fn(),
  cancelFriendRequest: vi.fn(),
}));

import { ProfileView } from "./ProfileView";
import { fetchFriends } from "@/lib/api";
import type { Achievement, Cosmetic, Role, UserProfile } from "@/lib/types";

function role(id: string, name: string, display_priority: number): Role {
  return {
    id, name, slug: id, color: "#123456", icon: null, description: null,
    is_staff_assigned: false, is_earnable: false, display_priority,
  };
}

function achievement(id: string, name: string, rarity: string, icon: string | null): Achievement {
  return {
    id, name, slug: id, description: null, icon, category: "learning" as Achievement["category"],
    rarity: rarity as Achievement["rarity"], is_secret: false, xp_reward: 0, icon_url: null,
    sort_order: 0, status: "live",
  };
}

function cosmetic(over: Partial<Cosmetic>): Cosmetic {
  return { id: "c1", type: "banner" as Cosmetic["type"], name: "C", slug: "c", rarity: "common" as Cosmetic["rarity"], ...over };
}

function minimal(over: Partial<UserProfile> = {}): UserProfile {
  return {
    id: "u1", name: "", username: null, bio: null, location: null, website: null,
    avatar_url: null, created_at: null, year: null, majors: [], minors: [], school: null,
    roles: [], featured_achievements: [], equipped_cosmetics: {},
    stats: undefined as unknown as UserProfile["stats"],
    ...over,
  };
}

function full(over: Partial<UserProfile> = {}): UserProfile {
  return minimal({
    name: "Ada Lovelace",
    username: "ada",
    bio: "Counting engines.",
    school: "BU",
    year: "Junior",
    location: "Boston",
    website: "https://www.example.com/me",
    avatar_url: "https://img/ada.png",
    majors: ["CS", "Math"],
    minors: ["Music"],
    roles: [
      { role: role("r-low", "Low", 1), granted_at: "" },
      { role: role("r-none", "NoPriority", undefined as unknown as number), granted_at: "" },
      { role: role("r-high", "High", 9), granted_at: "" },
    ],
    featured_achievements: [
      { achievement: achievement("a1", "First Steps", "epic", "🔥"), earned_at: "", is_featured: true },
      { achievement: achievement("a2", "No Icon", "common", null), earned_at: "", is_featured: true },
    ],
    stats: { streak_count: 4, session_count: 12, documents_count: 3, achievements_count: 7 },
    ...over,
  });
}

function heroSection(container: HTMLElement) {
  return container.querySelector("section") as HTMLElement;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ProfileView rendering", () => {
  it("renders the hero: name heading, @username, bio and meta in order", () => {
    const { container } = render(<ProfileView profile={full()} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Ada Lovelace");
    expect(screen.getByText("@ada")).toBeTruthy();
    expect(screen.getByText("Counting engines.")).toBeTruthy();
    const icons = Array.from(heroSection(container).querySelectorAll("[data-testid^='icon-']"))
      .map((el) => el.getAttribute("data-testid"));
    expect(icons).toEqual(["icon-tree", "icon-star", "icon-home", "icon-send"]);
    expect(screen.getByText("BU")).toBeTruthy();
    expect(screen.getByText("Junior")).toBeTruthy();
    expect(screen.getByText("Boston")).toBeTruthy();
    // The owner's own profile: no add-friend action, no status fetch.
    expect(screen.queryByTestId("profile-add-friend")).toBeNull();
    expect(fetchFriends).not.toHaveBeenCalled();
  });

  it("links the website with a prettified label", () => {
    render(<ProfileView profile={full()} />);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("https://www.example.com/me");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noreferrer");
    expect(link.textContent).toBe(" example.com/me");
  });

  it("drops a bare root path from the website label, and shows an unparsable one raw", () => {
    const { unmount } = render(<ProfileView profile={full({ website: "https://example.com/" })} />);
    expect(screen.getByRole("link").textContent).toBe(" example.com");
    unmount();
    render(<ProfileView profile={full({ website: "not a url" })} />);
    expect(screen.getByRole("link").textContent).toBe(" not a url");
  });

  it("orders roles by display priority, highest first, missing priority as 0", () => {
    const profile = full();
    const before = profile.roles.map((r) => r.role.id);
    render(<ProfileView profile={profile} />);
    const names = ["High", "Low", "NoPriority"].map((n) => screen.getByText(n));
    expect(names[0].compareDocumentPosition(names[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(names[1].compareDocumentPosition(names[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The profile's own array is not mutated.
    expect(profile.roles.map((r) => r.role.id)).toEqual(before);
  });

  it("omits optional hero fields and falls back to Unnamed", () => {
    const { container } = render(<ProfileView profile={minimal()} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Unnamed");
    expect(screen.queryByRole("link")).toBeNull();
    expect(heroSection(container).querySelectorAll("[data-testid^='icon-']")).toHaveLength(0);
    expect(heroSection(container).querySelector("p")).toBeNull();
    expect(container.textContent).not.toContain("@");
  });

  it("tolerates missing equipped_cosmetics and roles", () => {
    const profile = minimal({
      equipped_cosmetics: undefined as unknown as UserProfile["equipped_cosmetics"],
      roles: undefined as unknown as UserProfile["roles"],
    });
    render(<ProfileView profile={profile} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Unnamed");
  });

  it("paints the hero from the banner only when it has an asset", () => {
    const plain = render(<ProfileView profile={minimal()} />);
    expect(heroSection(plain.container).getAttribute("style")).toContain("background: var(--bg-panel)");
    plain.unmount();

    const noAsset = render(<ProfileView profile={minimal({
      equipped_cosmetics: { banner: cosmetic({ css_value: "red" }) },
    })} />);
    expect(heroSection(noAsset.container).getAttribute("style")).toContain("background: var(--bg-panel)");
    noAsset.unmount();

    const withAsset = render(<ProfileView profile={minimal({
      equipped_cosmetics: { banner: cosmetic({ asset_url: "/b.png", css_value: "red" }) },
    })} />);
    const styled = heroSection(withAsset.container).getAttribute("style") ?? "";
    expect(styled).not.toContain("background: var(--bg-panel)");
    expect(styled).toContain("linear-gradient");
    withAsset.unmount();
  });

  it("renders the stats strip with each count", () => {
    const { container } = render(<ProfileView profile={full()} />);
    const strip = container.querySelector("section.body-serif") as HTMLElement;
    expect(strip.textContent).toBe("4-day streak·12 sessions·3 documents·7 achievements");
    expect(screen.queryByText("This profile is private.")).toBeNull();
  });

  it("shows the strip when only one count is present, filling the rest with 0", () => {
    const stats = { session_count: 2 } as unknown as UserProfile["stats"];
    const { container } = render(<ProfileView profile={minimal({ stats })} />);
    const strip = container.querySelector("section.body-serif") as HTMLElement;
    expect(strip.textContent).toBe("0-day streak·2 sessions·0 documents·0 achievements");
    expect(screen.queryByText("This profile is private.")).toBeNull();
  });

  it("treats missing or empty stats as a private profile, without the strip", () => {
    const missing = render(<ProfileView profile={minimal()} />);
    expect(missing.container.querySelector("section.body-serif")).toBeNull();
    expect(screen.getByText("This profile is private.")).toBeTruthy();
    missing.unmount();

    const empty = render(<ProfileView profile={minimal({ stats: {} as UserProfile["stats"] })} />);
    expect(empty.container.querySelector("section.body-serif")).toBeNull();
    expect(screen.getByText("This profile is private.")).toBeTruthy();
  });

  it("lists fields of study, skipping an empty group", () => {
    const { unmount } = render(<ProfileView profile={full()} />);
    expect(screen.getByText("Fields of study")).toBeTruthy();
    expect(screen.getByText("Majors")).toBeTruthy();
    expect(screen.getByText("Minors")).toBeTruthy();
    expect(["CS", "Math", "Music"].map((v) => screen.getByText(v).className)).toEqual(["chip", "chip", "chip"]);
    unmount();

    const { unmount: u2 } = render(<ProfileView profile={full({ minors: [] })} />);
    expect(screen.getByText("Majors")).toBeTruthy();
    expect(screen.queryByText("Minors")).toBeNull();
    u2();

    render(<ProfileView profile={full({ majors: [], minors: [] })} />);
    expect(screen.queryByText("Fields of study")).toBeNull();
  });

  it("renders featured achievements with icon fallback and rarity color", () => {
    const { container } = render(<ProfileView profile={full()} />);
    expect(screen.getByText("Featured achievements")).toBeTruthy();
    expect(screen.getByText("🔥")).toBeTruthy();
    expect(screen.getByText("★")).toBeTruthy();
    expect(screen.getByText("epic")).toBeTruthy();
    const card = screen.getByText("First Steps").parentElement as HTMLElement;
    expect(card.getAttribute("style")).toContain("var(--rarity-epic, var(--text-muted))");
    expect(container.innerHTML).toContain("No Icon");
  });

  it("omits the achievements section when none are featured", () => {
    render(<ProfileView profile={full({ featured_achievements: [] })} />);
    expect(screen.queryByText("Featured achievements")).toBeNull();
    cleanup();
    render(<ProfileView profile={full({
      featured_achievements: undefined as unknown as UserProfile["featured_achievements"],
    })} />);
    expect(screen.queryByText("Featured achievements")).toBeNull();
  });

  it("drops the outer padding when embedded", () => {
    const page = render(<ProfileView profile={minimal()} />);
    expect((page.container.firstChild as HTMLElement).style.padding).toBe("20px 0px");
    page.unmount();
    const embedded = render(<ProfileView profile={minimal()} embedded />);
    expect((embedded.container.firstChild as HTMLElement).style.padding).toBe("0px");
  });

  it("keeps the section order: hero, stats, studies, achievements", () => {
    const { container } = render(<ProfileView profile={full()} />);
    const root = container.firstChild as HTMLElement;
    const kids = Array.from(root.children).map((el) => el.className || el.tagName);
    expect(kids).toEqual(["SECTION", "body-serif", "card", "card"]);
  });
});
