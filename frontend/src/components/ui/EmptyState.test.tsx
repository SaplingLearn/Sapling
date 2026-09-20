// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import React from "react";
import fs from "node:fs";
import path from "node:path";
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

/**
 * The promotion out of `screens/Gradebook/Landing.tsx` has to render that
 * screen unchanged, and the four values it was drawn at (56px title, 11px
 * ss01 eyebrow, 17px body, a plain primary CTA at 10px/18px) now live in CSS
 * that jsdom does not apply. So this pins both halves: the markup carries the
 * classes the rules hang off, and the rules carry the values.
 */
describe("EmptyState — the Gradebook promotion renders identically", () => {
  const GRADEBOOK = (
    <EmptyState
      size="hero"
      eyebrow="Spring 2026"
      title="A blank semester, ready to plant."
      body="Drop in a syllabus and Sapling lays out every assignment."
      action={
        <button type="button" className="btn btn--primary" data-testid="gradebook-upload-syllabus">
          Upload syllabus
        </button>
      }
    />
  );

  it("hangs every hero rule off the classes the old inline styles carried", () => {
    const { container } = render(GRADEBOOK);
    const root = container.querySelector(".empty-state")!;
    expect(root).toHaveClass("empty-state--hero");
    // Eyebrow: `.label-micro` inside `--hero`, which is what restores 11px+ss01.
    expect(root.querySelector(".empty-state__eyebrow")).toHaveClass("label-micro");
    // Title/body keep the type classes the old inline font-families named.
    expect(root.querySelector(".empty-state__title")).toHaveClass("h-serif");
    expect(root.querySelector(".empty-state__body")).toHaveClass("body-serif");
  });

  it("keeps the CTA a plain primary — btn--lg is 1px shorter and 100 heavier", () => {
    render(GRADEBOOK);
    const cta = screen.getByTestId("gradebook-upload-syllabus");
    expect(cta).toHaveClass("btn", "btn--primary");
    expect(cta).not.toHaveClass("btn--lg");
    expect(cta).not.toHaveClass("btn--sm");
  });

  it("pins the four promoted values in globals.css", () => {
    const css = fs.readFileSync(
      path.resolve(__dirname, "../../app/globals.css"),
      "utf8",
    );
    // The tokens, at the values the screen was drawn at…
    expect(css).toMatch(/--empty-hero-fs:\s*56px;/);
    expect(css).toMatch(/--empty-hero-eyebrow-fs:\s*11px;/);
    expect(css).toMatch(/--empty-hero-body-fs:\s*17px;/);
    expect(css).toMatch(/--empty-hero-cta-pad:\s*10px 18px;/);
    // …and the rules that actually spend them, including the ss01 `.mono`
    // carried and `.label-micro` does not.
    expect(css).toMatch(
      /\.empty-state--hero \.empty-state__eyebrow \{[^}]*font-size:\s*var\(--empty-hero-eyebrow-fs\)[^}]*font-feature-settings:\s*"ss01"[^}]*\}/,
    );
    expect(css).toMatch(
      /\.empty-state--hero \.empty-state__body \{[^}]*font-size:\s*var\(--empty-hero-body-fs\)[^}]*\}/,
    );
    expect(css).toMatch(
      /\.empty-state--hero \.empty-state__action \.btn \{[^}]*padding:\s*var\(--empty-hero-cta-pad\)[^}]*\}/,
    );
  });
});
