/**
 * The one shell-route list, matched on segment boundaries.
 */
import { readdirSync } from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

import { SHELL_PREFIXES, isAppShellRoute } from "./appRoutes";

describe("SHELL_PREFIXES", () => {
  it("lists exactly the route directories under app/(shell)", () => {
    // A (shell) page missing here is served with no middleware (no sign-in or
    // /pending redirect), no flags and no analytics: /flashcards was, when it
    // moved into the group. Route groups, private folders and slots are not
    // URL segments.
    const routes = readdirSync(path.resolve(__dirname, "../app/(shell)"), { withFileTypes: true })
      .filter((d) => d.isDirectory() && !/^[(_@]/.test(d.name))
      .map((d) => `/${d.name}`);
    expect([...SHELL_PREFIXES].sort()).toEqual(routes.sort());
  });
});

describe("isAppShellRoute", () => {
  it("matches every shell prefix and paths below it", () => {
    for (const p of SHELL_PREFIXES) {
      expect(isAppShellRoute(p), p).toBe(true);
      expect(isAppShellRoute(`${p}/x/y`), p).toBe(true);
    }
  });

  it("covers the Study tools, including the one served outside /study", () => {
    // Literal paths on purpose: the loop above reads the list it is testing,
    // so it cannot notice a (shell) page that was never added to it.
    for (const p of ["/study", "/study/guide", "/quiz", "/flashcards", "/flashcards/deck-1"]) {
      expect(isAppShellRoute(p), p).toBe(true);
    }
  });

  it("does not match look-alikes that merely start with a prefix", () => {
    for (const p of ["/profiles", "/learn-more", "/settings-help", "/dashboards", "/quizzes/x", "/tree-house", "/flashcards-import", "/flashcard"]) {
      expect(isAppShellRoute(p), p).toBe(false);
    }
  });

  it("public pages, auth and onboarding are not the shell", () => {
    for (const p of ["/", "/privacy", "/about", "/news/x", "/auth/callback", "/onboarding", "/pending", null, undefined, ""]) {
      expect(isAppShellRoute(p as string), String(p)).toBe(false);
    }
  });
});
