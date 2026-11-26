// @vitest-environment jsdom
/**
 * The session panel and the sidebar's Review, rebuilt (Tutor redesign phase
 * 4, `session_v2`) against the design boards `../__fixtures__/session.design.html`
 * and `../__fixtures__/sidebar.design.html`, kept verbatim (words and
 * structure, not pixels). The board's "Saved" tab and milestone link wait for
 * saved artifacts and milestones; the panel's foot links to the map instead.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const flags: Record<string, string> = {};
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off" }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import type { LoopPanelConcept } from "@/lib/api";
import { SessionPanel } from "./SessionPanel";
import { SESSION_PANEL_COPY, panelRows } from "./SessionPanelV2";
import { TutorSidebar } from "./TutorSidebar";

afterEach(() => {
  cleanup();
  for (const k of Object.keys(flags)) delete flags[k];
});

const read = (f: string) => fs.readFileSync(path.join(__dirname, "../__fixtures__", f), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const SESSION = read("session.design.html");
const SIDEBAR = read("sidebar.design.html");
const PLAN: LoopPanelConcept[] = [
  { node_id: "st", concept_name: "Stacks", kind: "review" }, { node_id: "ht", concept_name: "Hash tables", kind: "new" },
  { node_id: "cr", concept_name: "Collision resolution", kind: "new" }, { node_id: "q", concept_name: "Queues", kind: "sibling" },
];
const SKILLS = [
  { nodeId: "st", name: "Stacks", score: 0.58 }, { nodeId: "ht", name: "Hash tables", score: 0.22 },
  { nodeId: "cr", name: "Collision resolution", score: null }, { nodeId: "q", name: "Queues", score: 0.31 },
];

function renderPanel(over: Partial<React.ComponentProps<typeof SessionPanel>> = {}) {
  render(
    <SessionPanel plan={PLAN} currentNodeId="ht" skills={SKILLS} skillWords dueCount={7} dueHref="/study" map={<div data-testid="the-map" />}
      treeHref="/tree" showTreeLink onHide={() => {}} {...over} />,
  );
}

describe("the panel's one list", () => {
  it("each planned concept once, in plan order: the one being taught now, those before it done", () => {
    expect(panelRows(PLAN, SKILLS, "ht").map((r) => [r.name, r.state, r.score])).toEqual([
      ["Stacks", "done", 0.58], ["Hash tables", "now", 0.22], ["Collision resolution", "next", null], ["Queues", "next", 0.31],
    ]);
    expect(panelRows(PLAN, SKILLS, null).every((r) => r.state === "next")).toBe(true); // not teaching yet
    // no plan yet: the concept in focus
    expect(panelRows(null, [SKILLS[1]], "ht").map((r) => [r.name, r.state])).toEqual([["Hash tables", "now"]]);
  });
});

describe("parity with the design boards", () => {
  it.each([SESSION_PANEL_COPY.title, "Learn 2 of 4", "Wrap up", "Developing", "Getting started", "Not started"])("the session board says %j", (text) => {
    expect(SESSION).toContain(text);
  });
  it.each(["New session", "Search sessions", "Review", "Open"])("the sidebar board says %j", (text) => {
    expect(SIDEBAR).toContain(text);
  });

  it("session_v2 on: one list with each concept's level and bar; no separate meters, map, key or due box", () => {
    flags.session_v2 = "on";
    renderPanel();
    const panel = screen.getByTestId("loop-rail");
    expect(within(panel).getByRole("heading", { name: "Plan" })).toBeTruthy();
    const rows = within(panel).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      "StacksDeveloping", "Hash tablesGetting started", "Collision resolutionNot started", "QueuesDeveloping",
    ]);
    expect(screen.getByTestId("tutor-panel-concept-ht").getAttribute("aria-current")).toBe("step");
    expect(screen.getByTestId("tutor-panel-concept-st").getAttribute("data-state")).toBe("done");
    expect(within(panel).getAllByRole("meter")).toHaveLength(4); // each fact once: the level lives in the row
    expect(screen.queryByTestId("the-map")).toBeNull();
    expect(screen.queryByTestId("tutor-map-key")).toBeNull();
    expect(screen.queryByTestId("tutor-panel-due-count")).toBeNull();
    expect(screen.queryByTestId("session-plan-deps")).toBeNull();
    expect(screen.getByTestId("loop-tree-link").getAttribute("href")).toBe("/tree");
  });

  it("session_v2 off: the panel as before", () => {
    renderPanel();
    expect(screen.queryByTestId("tutor-panel-v2")).toBeNull();
    expect(screen.getByTestId("the-map")).toBeTruthy();
    expect(screen.getByTestId("tutor-panel-due-count")).toBeTruthy();
  });

  it("before a plan: the concept in focus, else one line", () => {
    flags.session_v2 = "on";
    renderPanel({ plan: null, skills: [] });
    expect(screen.getByText(SESSION_PANEL_COPY.empty)).toBeTruthy();
  });
});

describe("the sidebar's Review", () => {
  const props = {
    courses: [], courseId: "c1", sessions: [], currentSessionId: null, currentCourseView: null, query: "", setQuery: () => {},
    newDisabled: false, showNew: true, onNew: () => {}, onCourse: () => {}, onOpen: () => {}, onAll: () => {}, onHide: () => {},
  };

  it("session_v2 on: Review at the foot with the queue's count, to Study", () => {
    flags.session_v2 = "on";
    render(<TutorSidebar {...props} dueCount={7} dueHref="/study?due=1" />);
    const review = screen.getByTestId("tutor-side-review");
    expect(review.getAttribute("href")).toBe("/study?due=1");
    expect(review.textContent?.trim()).toBe("Review7 due");
    expect(screen.getByTestId("tutor-side-review-count").textContent).toBe("7 due");
  });

  it("nothing due: Review without a count; Study hidden or the flag off: no Review", () => {
    flags.session_v2 = "on";
    render(<TutorSidebar {...props} dueCount={0} dueHref="/study" />);
    expect(screen.getByTestId("tutor-side-review").textContent?.trim()).toBe("Review");
    cleanup();
    render(<TutorSidebar {...props} dueCount={3} dueHref={null} />);
    expect(screen.queryByTestId("tutor-side-review")).toBeNull();
    cleanup();
    delete flags.session_v2;
    render(<TutorSidebar {...props} dueCount={3} dueHref="/study" />);
    expect(screen.queryByTestId("tutor-side-review")).toBeNull();
  });
});
