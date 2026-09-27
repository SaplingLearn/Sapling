/**
 * The one shell-route list, matched on segment boundaries.
 */
import { describe, it, expect } from "vitest";

import { SHELL_PREFIXES, isAppShellRoute } from "./appRoutes";

describe("isAppShellRoute", () => {
  it("matches every shell prefix and paths below it", () => {
    for (const p of SHELL_PREFIXES) {
      expect(isAppShellRoute(p), p).toBe(true);
      expect(isAppShellRoute(`${p}/x/y`), p).toBe(true);
    }
  });

  it("does not match look-alikes that merely start with a prefix", () => {
    for (const p of ["/profiles", "/learn-more", "/settings-help", "/dashboards", "/quizzes/x", "/tree-house"]) {
      expect(isAppShellRoute(p), p).toBe(false);
    }
  });

  it("public pages, auth and onboarding are not the shell", () => {
    for (const p of ["/", "/privacy", "/about", "/news/x", "/auth/callback", "/onboarding", "/pending", null, undefined, ""]) {
      expect(isAppShellRoute(p as string), String(p)).toBe(false);
    }
  });
});
