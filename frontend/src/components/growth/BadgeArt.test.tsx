// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { BadgeArt } from "./BadgeArt";

afterEach(cleanup);

describe("BadgeArt icon precedence", () => {
  it("prefers an uploaded icon_url", () => {
    const { container } = render(
      <BadgeArt slug="on-fire" rarity="rare" locked={false}
                iconUrl="https://cdn/x.png" emoji="🔥" />,
    );
    expect(container.querySelector("image")?.getAttribute("href")).toBe("https://cdn/x.png");
  });

  it("falls back to the built-in icon when there is no upload", () => {
    const { container } = render(
      <BadgeArt slug="on-fire" rarity="rare" locked={false} emoji="🔥" />,
    );
    expect(container.querySelector("image")).toBeNull();
    expect(container.querySelector('[data-icon="on-fire"]')).not.toBeNull();
  });

  it("falls back to the emoji when the slug has no built-in art", () => {
    const { container } = render(
      <BadgeArt slug="made-up-slug" rarity="common" locked={false} emoji="🌱" />,
    );
    expect(container.textContent).toContain("🌱");
  });

  it("renders a default star when there is nothing at all", () => {
    const { container } = render(
      <BadgeArt slug="made-up-slug" rarity="common" locked={false} />,
    );
    expect(container.textContent).toContain("★");
  });

  it("greys the disc when locked", () => {
    const { container } = render(
      <BadgeArt slug="on-fire" rarity="legendary" locked />,
    );
    expect(container.innerHTML).toContain("#eceae4");
  });

  it("has built-in art for every live catalog slug", () => {
    const LIVE_SLUGS = ["first-steps","flash","early-bird","night-owl","on-fire",
      "deep-focus","quiz-master","marathon","wildfire","first-friend","study-circle",
      "helping-hand","room-leader","popular","social-butterfly","mentor","sprout",
      "rooted","grade-a","branching","rings","canopy","web","old-growth",
      "golden-hour","comeback","perfect-week","secret","methuselah","polymath"];
    for (const slug of LIVE_SLUGS) {
      const { container } = render(
        <BadgeArt slug={slug} rarity="common" locked={false} />,
      );
      expect(container.querySelector(`[data-icon="${slug}"]`), slug).not.toBeNull();
    }
  });
});
