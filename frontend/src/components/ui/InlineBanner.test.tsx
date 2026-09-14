// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import React from "react";
import { InlineBanner } from "./InlineBanner";
import { Button } from "./Button";

afterEach(cleanup);

describe("InlineBanner", () => {
  it("announces itself — the strip appears without the user asking", () => {
    render(<InlineBanner>You left a quiz on Recursion — 2 of 5 answered</InlineBanner>);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("You left a quiz on Recursion — 2 of 5 answered");
    expect(banner).toHaveClass("inline-banner", "inline-banner--accent");
  });

  it("keeps its actions in their own slot, after the body", () => {
    render(
      <InlineBanner
        testid="quiz-resume-strip"
        actions={
          <>
            <Button data-testid="quiz-resume">Resume</Button>
            <Button variant="link" data-testid="quiz-resume-discard">
              Discard
            </Button>
          </>
        }
      >
        You left a quiz on Recursion
      </InlineBanner>,
    );
    const banner = screen.getByTestId("quiz-resume-strip");
    expect(banner.querySelector(".inline-banner__body")).toHaveTextContent(
      "You left a quiz on Recursion",
    );
    const actions = banner.querySelector(".inline-banner__actions")!;
    expect(actions.querySelectorAll("button")).toHaveLength(2);
    expect(screen.getByTestId("quiz-resume-discard")).toHaveClass("btn--link");
  });

  it("omits the actions slot entirely when there are none", () => {
    const { container } = render(<InlineBanner>Nothing to do here</InlineBanner>);
    expect(container.querySelector(".inline-banner__actions")).toBeNull();
  });

  it("takes the neutral tone for strips that aren't about the course", () => {
    render(<InlineBanner tone="neutral">Heads up</InlineBanner>);
    expect(screen.getByRole("status")).toHaveClass("inline-banner--neutral");
  });
});
