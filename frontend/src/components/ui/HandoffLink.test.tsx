// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import { CtaLink, HandoffLink } from "./HandoffLink";

afterEach(cleanup);

describe("HandoffLink", () => {
  it("is a real link with its href and test id, shaped like a button", () => {
    render(<HandoffLink href="/study?course=c1" testId="h" variant="primary" size="sm">Review</HandoffLink>);
    const link = screen.getByRole("link", { name: "Review" });
    expect(link.getAttribute("href")).toBe("/study?course=c1");
    expect(link.getAttribute("data-testid")).toBe("h");
    expect(link.className).toBe("btn btn--primary btn--sm");
  });

  it("plain keeps only the caller's class; text is the bare link", () => {
    render(<><HandoffLink href="/a" variant="plain" className="mine">A</HandoffLink><HandoffLink href="/b" variant="text">B</HandoffLink></>);
    expect(screen.getByRole("link", { name: "A" }).className).toBe("mine");
    expect(screen.getByRole("link", { name: "B" }).className).toBe("btn btn--link");
  });

  it("onNavigate takes a plain click; a modified or middle click is the browser's (new tab)", () => {
    const onNavigate = vi.fn();
    render(<HandoffLink href="/quiz" onNavigate={onNavigate}>Quiz</HandoffLink>);
    const link = screen.getByRole("link", { name: "Quiz" });
    for (const init of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      expect(fireEvent.click(link, init)).toBe(true); // not prevented
    }
    expect(onNavigate).not.toHaveBeenCalled();
    expect(fireEvent.click(link)).toBe(false); // prevented: the surface navigates
    expect(onNavigate).toHaveBeenCalledWith("/quiz");
  });

  it("CtaLink renders a hand-off's label, href and id, with an override", () => {
    const cta = { key: "study" as const, label: "Review", href: "/study", testId: "loop-close-study-link" };
    render(<><CtaLink cta={cta} /><CtaLink cta={cta} testId="again" /></>);
    const [first, second] = screen.getAllByRole("link", { name: "Review" });
    expect(first.getAttribute("data-testid")).toBe("loop-close-study-link");
    expect(second.getAttribute("data-testid")).toBe("again");
  });
});
