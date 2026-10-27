// @vitest-environment jsdom
/**
 * Roadmap screen — rendering, states, and the one invariant that matters
 * most: the page displays server-computed numbers and derives none itself.
 */
import React from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RoadmapScreen } from "./Roadmap";
import type { RoadmapResponse, RoadmapSubtopic, RoadmapTopic } from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "user1", userReady: true }),
}));

const getRoadmap = vi.fn();
const getRoadmapReadiness = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/lib/api");
  return {
    ...actual,
    getRoadmap: (...a: unknown[]) => getRoadmap(...a),
    getRoadmapReadiness: (...a: unknown[]) => getRoadmapReadiness(...a),
  };
});

function sub(overrides: Partial<RoadmapSubtopic> = {}): RoadmapSubtopic {
  return {
    node_id: "s1",
    concept_name: "Mitochondria",
    mastery: 0.8,
    tier: "mastered",
    freshness: 1,
    is_stale: false,
    weight: 1,
    contribution: 0.8,
    color: "#4FA574",
    times_studied: 2,
    last_studied_at: null,
    in_cycle: false,
    ...overrides,
  };
}

function topic(overrides: Partial<RoadmapTopic> = {}): RoadmapTopic {
  const subtopics = overrides.subtopics ?? [sub()];
  return {
    id: "t1",
    concept_name: "Cell Structure",
    color: "#4FA574",
    in_cycle: false,
    subtopics,
    summary: {
      total: subtopics.length,
      mastered: subtopics.filter(s => s.tier === "mastered").length,
      stale: subtopics.filter(s => s.is_stale).length,
      started: subtopics.filter(s => s.mastery > 0).length,
      readiness: 0.8,
    },
    ...overrides,
  };
}

function payload(overrides: Partial<RoadmapResponse> = {}): RoadmapResponse {
  return {
    course_id: "course1",
    topics: [topic()],
    unfiled: [],
    exams: [],
    selected_exam: null,
    start_here_topic_id: "t1",
    start_here_unfiled: false,
    readiness: 0.63,
    summary: { total: 1, mastered: 1, stale: 0, started: 1, readiness: 0.63 },
    needs_structure: false,
    ...overrides,
  };
}

// `globals: false` in vitest.config.ts means testing-library's automatic
// cleanup never registers, so the DOM leaks between tests unless we do this
// ourselves — and a leaked tree makes every queryBy* assertion a lie.
afterEach(cleanup);

beforeEach(() => {
  push.mockClear();
  getRoadmap.mockReset();
  getRoadmapReadiness.mockReset();
});

describe("RoadmapScreen", () => {
  it("renders topics in the order the server returned", async () => {
    getRoadmap.mockResolvedValue(payload({
      topics: [
        topic({ id: "t2", concept_name: "Second" }),
        topic({ id: "t1", concept_name: "First" }),
      ],
      start_here_topic_id: "t2",
    }));

    render(<RoadmapScreen courseId="course1" />);

    // Topic names appear TWICE by design — once in the accordion, once in
    // the sidebar breakdown — so scope to the accordion before asserting.
    const list = await screen.findByTestId("roadmap-topics");
    const names = within(list)
      .getAllByText(/^(First|Second)$/)
      .map(n => n.textContent);
    expect(names).toEqual(["Second", "First"]);
  });

  it("shows the readiness percentage the server computed, unmodified", async () => {
    getRoadmap.mockResolvedValue(payload({ readiness: 0.63 }));

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByText("63%")).toBeInTheDocument();
  });

  it("marks the start-here topic", async () => {
    getRoadmap.mockResolvedValue(payload());

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByTestId("roadmap-start-here")).toBeInTheDocument();
  });

  it("expands the start-here topic on first load", async () => {
    getRoadmap.mockResolvedValue(payload());

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByTestId("roadmap-subtopic-s1")).toBeInTheDocument();
  });

  it("names what the ring is measured against", async () => {
    getRoadmap.mockResolvedValue(payload({
      exams: [{ id: "e1", title: "Midterm 2", due_date: "2099-01-01" }],
      selected_exam: { id: "e1", title: "Midterm 2", due_date: "2099-01-01" },
    }));

    render(<RoadmapScreen courseId="course1" />);

    const ring = await screen.findByTestId("roadmap-readiness-ring");
    expect(within(ring).getByText("Midterm 2")).toBeInTheDocument();
  });

  it("offers the flat list plus an organise action when nothing is grouped", async () => {
    getRoadmap.mockResolvedValue(payload({
      topics: [],
      unfiled: [sub({ node_id: "x1", concept_name: "Orphan" })],
      needs_structure: true,
      start_here_topic_id: null,
    }));

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByTestId("roadmap-needs-structure")).toBeInTheDocument();
    expect(screen.getByText(/Organise into topics/)).toBeInTheDocument();
  });

  it("does not offer organising when there are no concepts at all", async () => {
    getRoadmap.mockResolvedValue(payload({
      topics: [], unfiled: [], needs_structure: false, start_here_topic_id: null,
    }));

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByTestId("roadmap-empty")).toBeInTheDocument();
    expect(screen.queryByText(/Organise into topics/)).not.toBeInTheDocument();
  });

  it("points at the unfiled group when every topic is done but concepts remain", async () => {
    getRoadmap.mockResolvedValue(payload({
      unfiled: [sub({ node_id: "x1", concept_name: "Untouched", mastery: 0, tier: "unexplored" })],
      start_here_topic_id: null,
      start_here_unfiled: true,
    }));

    render(<RoadmapScreen courseId="course1" />);

    const unfiled = await screen.findByTestId("roadmap-unfiled");
    expect(within(unfiled).getByTestId("roadmap-start-here")).toBeInTheDocument();
  });

  it("keeps unfiled concepts visible alongside grouped topics", async () => {
    getRoadmap.mockResolvedValue(payload({
      unfiled: [sub({ node_id: "x1", concept_name: "Loose End" })],
    }));

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByTestId("roadmap-unfiled")).toBeInTheDocument();
    expect(screen.getByText("Loose End")).toBeInTheDocument();
  });

  it("flags a stale subtopic in text, not only by styling", async () => {
    getRoadmap.mockResolvedValue(payload({
      topics: [topic({ subtopics: [sub({ is_stale: true })] })],
    }));

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByText("needs review")).toBeInTheDocument();
  });

  it("explains a prerequisite cycle instead of presenting a confident order", async () => {
    getRoadmap.mockResolvedValue(payload({
      topics: [topic({ in_cycle: true })],
    }));

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByText(/prerequisites loop/)).toBeInTheDocument();
  });

  it("fetches the breakdown rather than recomputing it", async () => {
    getRoadmap.mockResolvedValue(payload());
    getRoadmapReadiness.mockResolvedValue({
      course_id: "course1",
      exam: null,
      factors: [{
        topic_id: "t1", concept_name: "Cell Structure", mastered: 1,
        total: 1, stale: 0, freshness: 1, weight: 1, contribution: 0.8,
      }],
      readiness: 0.8,
    });

    render(<RoadmapScreen courseId="course1" />);
    await userEvent.click(await screen.findByText("Why this number?"));

    await waitFor(() =>
      expect(screen.getByTestId("roadmap-readiness-breakdown")).toBeInTheDocument(),
    );
    expect(getRoadmapReadiness).toHaveBeenCalledWith("user1", "course1", undefined);
  });

  it("re-fetches scoped to an exam when one is picked", async () => {
    getRoadmap.mockResolvedValue(payload({
      exams: [{ id: "e1", title: "Midterm 2", due_date: "2099-01-01" }],
      selected_exam: null,
    }));

    render(<RoadmapScreen courseId="course1" />);
    const exams = await screen.findByTestId("roadmap-exams");
    await userEvent.click(within(exams).getByText("Midterm 2"));

    await waitFor(() =>
      expect(getRoadmap).toHaveBeenLastCalledWith("user1", "course1", "e1"),
    );
  });

  it("surfaces a load failure instead of rendering an empty plan", async () => {
    getRoadmap.mockRejectedValue(new Error("boom"));

    render(<RoadmapScreen courseId="course1" />);

    expect(await screen.findByTestId("roadmap-error")).toBeInTheDocument();
  });
});
