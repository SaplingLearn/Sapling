// @vitest-environment jsdom
/**
 * The crisis-support card (docs/safety/crisis-support.md): a calm card, not an
 * error. It renders every string of the backend payload (it has no copy of its
 * own), every resource with a tappable way to reach it, and — in its dialog
 * form — a way back to studying.
 */
import React from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { act, cleanup, render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import fixture from "@/test-utils/crisisSupport.json";
import { crisisSupportOf, type CrisisSupport } from "@/lib/crisisSupport";
import { __resetFeedbackPacingForTests, feedbackHeld, whenFeedbackFree } from "@/lib/feedbackPacing";
import { CrisisSupportCard, CrisisSupportDialog, useCrisisSupport } from "./CrisisSupportCard";

const support = crisisSupportOf(fixture) as CrisisSupport;

afterEach(cleanup);

describe("CrisisSupportCard", () => {
  it("renders every string of the payload", () => {
    render(<CrisisSupportCard support={support} />);
    const card = screen.getByTestId("crisis-support-card");
    for (const text of [support.title, ...support.intro, support.resources_heading, ...support.closing]) {
      expect(card.textContent).toContain(text);
    }
    for (const r of support.resources) {
      const row = screen.getByTestId(`crisis-support-resource-${r.id}`);
      expect(row.textContent).toContain(r.name);
      expect(row.textContent).toContain(r.detail);
    }
    expect(screen.getByRole("heading", { name: support.title })).toBeTruthy();
    expect(screen.getByRole("region", { name: support.title })).toBe(card);
  });

  it("links every way to reach help: call or text 988, text HOME to 741741, call 911, findahelpline.com", () => {
    render(<CrisisSupportCard support={support} />);
    const hrefs = screen.getAllByTestId("crisis-support-action").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(expect.arrayContaining([
      "tel:988", "sms:988", "sms:741741?body=HOME", "tel:911", "https://findahelpline.com",
    ]));
  });

  it("opens web pages in a new tab without a referrer, and phone links in place", () => {
    render(<CrisisSupportCard support={support} />);
    const links = screen.getAllByTestId("crisis-support-action");
    const web = links.find((a) => a.getAttribute("href") === "https://findahelpline.com")!;
    expect(web.getAttribute("target")).toBe("_blank");
    expect(web.getAttribute("rel")).toBe("noopener noreferrer");
    const call = links.find((a) => a.getAttribute("href") === "tel:988")!;
    expect(call.getAttribute("target")).toBeNull();
  });

  it("is calm, not an error: no alert role and no error colours", () => {
    render(<CrisisSupportCard support={support} />);
    const card = screen.getByTestId("crisis-support-card");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(card.getAttribute("style")).toContain("var(--info-soft)");
    expect(card.outerHTML).not.toMatch(/--err|--warn|crimson/);
  });

  it("shows the dismiss button only when it has somewhere to go back to", async () => {
    const onDismiss = vi.fn();
    const { rerender } = render(<CrisisSupportCard support={support} />);
    expect(screen.queryByTestId("crisis-support-dismiss")).toBeNull();
    rerender(<CrisisSupportCard support={support} onDismiss={onDismiss} />);
    const dismiss = screen.getByTestId("crisis-support-dismiss");
    expect(dismiss.textContent).toBe(support.dismiss_label);
    await userEvent.click(dismiss);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

describe("CrisisSupportDialog", () => {
  it("renders nothing without a payload", () => {
    render(<CrisisSupportDialog support={null} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the card over the page, labelled by its title, and closes back to studying", async () => {
    const onClose = vi.fn();
    render(<CrisisSupportDialog support={support} onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: support.title });
    expect(within(dialog).getByTestId("crisis-support-card")).toBeTruthy();
    await userEvent.click(within(dialog).getByTestId("crisis-support-dismiss"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// lib/feedbackPacing.ts: no feedback survey opens over a crisis card, on any
// surface, in either form.
describe("the card holds the shell's feedback prompts", () => {
  beforeEach(() => __resetFeedbackPacingForTests());

  it("while it is on screen, and releases them when it goes", () => {
    const open = vi.fn();
    const view = render(<CrisisSupportCard support={support} />);
    expect(feedbackHeld()).toBe(true);
    whenFeedbackFree(open);
    expect(open).not.toHaveBeenCalled();
    view.unmount();
    expect(feedbackHeld()).toBe(false);
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("in its dialog form, until the dialog closes", () => {
    const { rerender } = render(<CrisisSupportDialog support={support} onClose={() => {}} />);
    expect(feedbackHeld()).toBe(true);
    rerender(<CrisisSupportDialog support={null} onClose={() => {}} />);
    expect(feedbackHeld()).toBe(false);
  });
});

describe("useCrisisSupport", () => {
  it("intercepts a response that carries the card, and only such a response", () => {
    const { result } = renderHook(() => useCrisisSupport());
    let hit = true;
    act(() => { hit = result.current.intercept({ summary: "an ordinary result" }); });
    expect(hit).toBe(false);
    expect(result.current.support).toBeNull();
    act(() => { hit = result.current.intercept({ reply: "…", crisis_support: fixture }); });
    expect(hit).toBe(true);
    expect(result.current.support?.title).toBe(support.title);
  });
});
