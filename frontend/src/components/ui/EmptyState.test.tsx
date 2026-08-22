// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import React from "react";
import { EmptyState } from "./EmptyState";

afterEach(cleanup);

describe("EmptyState", () => {
  it("renders the title as a heading, with the body and the eyebrow", () => {
    render(
      <EmptyState
        eyebrow="Spring 2026"
        title="Your tree is empty"
        body="Upload notes or talk to the tutor and concepts will appear here."
        testid="quiz-empty-state"
      />,
    );
    expect(screen.getByRole("heading", { name: "Your tree is empty" })).toBeInTheDocument();
    expect(screen.getByText(/Upload notes or talk to the tutor/)).toBeInTheDocument();
    expect(screen.getByText("Spring 2026")).toHaveClass("label-micro");
    expect(screen.getByTestId("quiz-empty-state")).toHaveClass("empty-state--md");
  });

  it("turns a {label, href} action into a primary link out", () => {
    render(
      <EmptyState
        title="Add a course to start quizzing"
        action={{ label: "Go to dashboard", href: "/dashboard" }}
      />,
    );
    const link = screen.getByRole("link", { name: "Go to dashboard" });
    expect(link).toHaveAttribute("href", "/dashboard");
    expect(link).toHaveClass("btn", "btn--primary");
  });

  it("takes an arbitrary node when the caller needs a handler, not a link", () => {
    const onUpload = vi.fn();
    render(
      <EmptyState
        title="A blank semester, ready to plant."
        action={
          <button type="button" onClick={onUpload}>
            Upload syllabus
          </button>
        }
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Upload syllabus" }));
    expect(onUpload).toHaveBeenCalled();
  });

  it("omits the parts it wasn't given", () => {
    const { container } = render(<EmptyState title="Nothing here" />);
    expect(container.querySelector(".empty-state__body")).toBeNull();
    expect(container.querySelector(".empty-state__eyebrow")).toBeNull();
    expect(container.querySelector(".empty-state__action")).toBeNull();
    expect(container.querySelector(".empty-state__icon")).toBeNull();
  });

  it("renders a decorative icon when asked", () => {
    const { container } = render(<EmptyState title="Nothing here" icon="flask" />);
    const icon = container.querySelector(".empty-state__icon")!;
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon.querySelector("svg")).not.toBeNull();
  });

  it("carries Gradebook's display-scale treatment under size=hero", () => {
    const { container } = render(<EmptyState size="hero" title="A blank semester." />);
    expect(container.querySelector(".empty-state")).toHaveClass("empty-state--hero");
  });
});
