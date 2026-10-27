// @vitest-environment jsdom
/**
 * The chip is the ENTIRE user-facing surface of the course-scope signal
 * (backend: services/course_scope.py). The tutor's reply is forbidden from
 * mentioning coverage at all, so what this component says — and does not
 * say — is the whole contract:
 *
 *   - a quiet "New", not a warning and not an apology;
 *   - no mention of syllabi, catalogs, documents, or retrieval, which is
 *     the exact wording the disclaimer bug produced;
 *   - a stable testid for the Chapter-1 journeys.
 *
 * Whether it renders at all is Learn.tsx's conditional (`topicStatus ===
 * "new"`), pinned by Learn.topicStatus.test.ts.
 */

import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import { NewTopicChip } from "./NewTopicChip";

afterEach(cleanup);

describe("NewTopicChip", () => {
  it("renders a quiet New label under a stable testid", () => {
    render(<NewTopicChip topic="eigenvalue decomposition" />);
    const chip = screen.getByTestId("tutor-new-topic");
    expect(chip.textContent).toContain("New");
  });

  it("names the question in its accessible label", () => {
    render(<NewTopicChip topic="eigenvalue decomposition" />);
    const label = screen.getByTestId("tutor-new-topic").getAttribute("aria-label") ?? "";
    expect(label).toContain("eigenvalue decomposition");
    expect(label).toContain("knowledge map");
  });

  it("falls back to a topic-less label rather than rendering empty quotes", () => {
    render(<NewTopicChip />);
    const label = screen.getByTestId("tutor-new-topic").getAttribute("aria-label") ?? "";
    expect(label).toBe("This is new to your course — added to your knowledge map.");
  });

  it("never uses the disclaimer wording this feature replaced", () => {
    render(<NewTopicChip topic="eigenvalue decomposition" />);
    const chip = screen.getByTestId("tutor-new-topic");
    const text = `${chip.textContent} ${chip.getAttribute("aria-label")}`.toLowerCase();
    for (const forbidden of ["syllabus", "catalog", "material", "document", "don't have", "no information"]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("explains itself on hover without claiming anything is missing", () => {
    const { container } = render(<NewTopicChip topic="Fourier series" />);
    fireEvent.mouseEnter(container.firstChild as Element);
    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toContain("Fourier series");
    expect(tip.textContent?.toLowerCase()).not.toContain("syllabus");
  });
});
