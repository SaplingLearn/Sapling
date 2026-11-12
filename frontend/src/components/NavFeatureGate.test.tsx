// @vitest-environment jsdom
/**
 * NavFeatureGate (#620): a hidden feature's route goes to /dashboard and is
 * never visible on the way; unflagged routes are never veiled.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

let pathname = "/quiz";
const replace = vi.fn();
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => ({ replace }) }));
let flagState: { flags: Record<string, string>; ready: boolean } = { flags: {}, ready: true };
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState }));

import { NavFeatureGate } from "./NavFeatureGate";

function renderGate() {
  return render(<NavFeatureGate><p data-testid="page">page</p></NavFeatureGate>);
}

describe("NavFeatureGate", () => {
  beforeEach(() => { replace.mockReset(); pathname = "/quiz"; flagState = { flags: {}, ready: true }; });
  afterEach(() => cleanup());

  it("renders a shown feature's page normally", () => {
    renderGate();
    const gate = screen.getByTestId("nav-feature-gate");
    expect(gate.dataset.veiled).toBeUndefined();
    expect(gate.style.visibility).toBe("");
    expect(gate.style.display).toBe("contents");
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects a hidden feature's route (and below it) to /dashboard, veiled", () => {
    pathname = "/quiz/session-1";
    flagState = { flags: { hide_quiz: "on" }, ready: true };
    renderGate();
    expect(replace).toHaveBeenCalledWith("/dashboard");
    const gate = screen.getByTestId("nav-feature-gate");
    expect(gate.dataset.veiled).toBe("true");
    expect(gate.style.visibility).toBe("hidden");
  });

  it("veils a flagged route while flags load, without redirecting", () => {
    flagState = { flags: {}, ready: false };
    renderGate();
    expect(screen.getByTestId("nav-feature-gate").style.visibility).toBe("hidden");
    expect(screen.getByTestId("page")).toBeTruthy(); // mounted, so its fetches start
    expect(replace).not.toHaveBeenCalled();
  });

  it("never veils or redirects an unflagged route", () => {
    pathname = "/settings";
    flagState = { flags: { hide_quiz: "on" }, ready: false };
    renderGate();
    expect(screen.getByTestId("nav-feature-gate").dataset.veiled).toBeUndefined();
    expect(replace).not.toHaveBeenCalled();
  });

  it("another feature's flag does not affect this route", () => {
    flagState = { flags: { hide_tree: "on" }, ready: true };
    renderGate();
    expect(replace).not.toHaveBeenCalled();
  });

  // Flashcards and the Study Guide are Study's pages; /flashcards is served
  // outside /study and used to slip past the gate (navFeatures NAV_PATH_ALIASES).
  it.each(["/study", "/study/guide", "/flashcards", "/flashcards/deck-1"])(
    "hiding Study redirects %s to /dashboard, veiled",
    (path) => {
      pathname = path;
      flagState = { flags: { hide_study: "on" }, ready: true };
      renderGate();
      expect(replace).toHaveBeenCalledTimes(1);
      expect(replace).toHaveBeenCalledWith("/dashboard");
      expect(screen.getByTestId("nav-feature-gate").style.visibility).toBe("hidden");
    },
  );

  it("veils /flashcards while flags load, without redirecting", () => {
    pathname = "/flashcards";
    flagState = { flags: {}, ready: false };
    renderGate();
    expect(screen.getByTestId("nav-feature-gate").dataset.veiled).toBe("true");
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows /flashcards when Study is visible, whatever Quiz's flag says", () => {
    pathname = "/flashcards";
    flagState = { flags: { hide_study: "off", hide_quiz: "on" }, ready: true };
    renderGate();
    expect(screen.getByTestId("nav-feature-gate").dataset.veiled).toBeUndefined();
    expect(replace).not.toHaveBeenCalled();
  });

  it("the landing page of a redirect is never gated, so it cannot loop", () => {
    // Every hide flag on at once: /dashboard still renders.
    pathname = "/dashboard";
    flagState = {
      flags: { hide_study: "on", hide_quiz: "on", hide_tutor: "on", hide_tree: "on" },
      ready: true,
    };
    renderGate();
    expect(screen.getByTestId("nav-feature-gate").dataset.veiled).toBeUndefined();
    expect(replace).not.toHaveBeenCalled();
  });
});
