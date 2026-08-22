// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import React from "react";
import { Button } from "./Button";

afterEach(cleanup);

describe("Button — the link variant (#537)", () => {
  it("carries .btn--link and stays a real button", () => {
    render(<Button variant="link">adjust</Button>);
    const btn = screen.getByRole("button", { name: "adjust" });
    expect(btn).toHaveClass("btn", "btn--link");
    expect(btn).toHaveAttribute("type", "button");
  });

  it("leaves the other variants alone", () => {
    render(
      <>
        <Button>secondary</Button>
        <Button variant="primary">primary</Button>
        <Button variant="ghost" size="sm">
          ghost
        </Button>
      </>,
    );
    // secondary is the default and adds no modifier
    expect(screen.getByRole("button", { name: "secondary" }).className).toBe("btn");
    expect(screen.getByRole("button", { name: "primary" })).toHaveClass("btn--primary");
    expect(screen.getByRole("button", { name: "ghost" })).toHaveClass("btn--ghost", "btn--sm");
  });

  it("exposes the open-dialog state the quiz's `adjust` link needs", () => {
    render(
      <Button variant="link" aria-pressed data-active="true">
        adjust
      </Button>,
    );
    const btn = screen.getByRole("button", { name: "adjust" });
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(btn).toHaveAttribute("data-active", "true");
  });
});
