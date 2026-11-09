// @vitest-environment jsdom
/**
 * The tree's half of the quiz entry/exit thread (#537 §6, C1):
 *
 *   1. "Quick quiz" on a CONCEPT links by node id, tagged `from=tree`, and
 *      carries a `return` that comes back to this very node's open panel.
 *      Before #537 it linked by concept NAME — unique only within a course —
 *      and the quiz exited to a hardcoded `/learn` no matter how it was
 *      entered.
 *   2. "Quick quiz" on a SUBJECT ROOT links to the abstract course. The old
 *      handler sent a bare `/quiz` because the quiz screen had no course entry
 *      at all; it does now.
 *   3. `/tree?node=<id>` opens that node's panel, and an unknown id is ignored
 *      in silence rather than erroring.
 *   4. "Recent quizzes" shows at most five COMPLETED attempts for the SELECTED
 *      node, newest first — the attempts endpoint is user-scoped and unfiltered
 *      (gaps G2/G3), so every one of those filters is this component's job.
 *
 * The graph renderer is stubbed to a node list of buttons: this is about the
 * panel and the links, and the real renderer needs a canvas.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AttemptSummary } from "@/lib/quiz/types";
import type { GraphNode } from "@/lib/data";

const push = vi.fn();
const params = vi.hoisted(() => ({ value: new URLSearchParams() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => params.value,
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada" }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));

// A clickable stand-in for the real graph: one button per node, so a test can
// "tap" a node exactly as the canvas would.
vi.mock("../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: ({
    nodes,
    onNodeClick,
  }: {
    nodes: GraphNode[];
    onNodeClick?: (n: GraphNode) => void;
  }) => (
    <div data-testid="stub-graph">
      {nodes.map((n) => (
        <button key={n.id} data-testid={`stub-node-${n.id}`} onClick={() => onNodeClick?.(n)}>
          {n.name}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("../Skeleton", () => ({ GraphPanelSkeleton: () => null }));
vi.mock("../Icon", () => ({ Icon: () => null }));

vi.mock("@/lib/api", () => ({
  getGraph: vi.fn(),
  getCourses: vi.fn(),
  getSessions: vi.fn(),
  addGraphNode: vi.fn(),
  deleteGraphNode: vi.fn(),
}));

vi.mock("@/lib/quiz/api", () => ({ listAttempts: vi.fn() }));

import { Tree } from "./Tree";
import { ToastProvider } from "../ToastProvider";
import { getCourses, getGraph, getSessions } from "@/lib/api";
import { listAttempts } from "@/lib/quiz/api";

const mockedGraph = vi.mocked(getGraph);
const mockedCourses = vi.mocked(getCourses);
const mockedSessions = vi.mocked(getSessions);
const mockedAttempts = vi.mocked(listAttempts);

const COURSE_ID = "course-cs101";
const ROOT_ID = `subject_root__${COURSE_ID}`;
const RECURSION = "node-recursion";
const POINTERS = "node-pointers";

/** The wire shape `getGraph` returns, not the mapped `GraphNode`. */
function apiNode(over: Partial<Record<string, unknown>> & { id: string; concept_name: string }) {
  return {
    subject: "Intro to CS",
    mastery_tier: "learning",
    mastery_score: 0.4,
    course_id: COURSE_ID,
    course_color: "#123456",
    times_studied: 2,
    last_studied_at: null,
    is_subject_root: false,
    ...over,
  };
}

function attempt(over: Partial<AttemptSummary> & { quiz_id: string }): AttemptSummary {
  return {
    status: "completed",
    concept_node_id: RECURSION,
    concept_name: "Recursion",
    course_id: COURSE_ID,
    score: 3,
    total: 3,
    difficulty: "medium",
    mastery_before: 0.4,
    mastery_after: 0.44,
    mastery_delta: 0.04,
    created_at: "2026-08-20T10:00:00Z",
    completed_at: "2026-08-20T10:05:00Z",
    ...over,
  };
}

function renderTree() {
  return render(
    <ToastProvider>
      <Tree />
    </ToastProvider>,
  );
}

/** Opens a node's detail panel through the graph, the way a student does. */
async function selectNode(user: ReturnType<typeof userEvent.setup>, id: string) {
  await user.click(await screen.findByTestId(`stub-node-${id}`));
}

beforeEach(() => {
  vi.clearAllMocks();
  params.value = new URLSearchParams();
  window.localStorage.clear();
  // jsdom has no ResizeObserver; the graph slot measures itself with one.
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  mockedCourses.mockResolvedValue({
    courses: [
      {
        enrollment_id: "e1",
        course_id: COURSE_ID,
        course_code: "CS101",
        course_name: "Intro to CS",
        color: "#123456",
      },
    ],
  } as Awaited<ReturnType<typeof getCourses>>);
  mockedGraph.mockResolvedValue({
    nodes: [
      apiNode({ id: RECURSION, concept_name: "Recursion" }),
      apiNode({ id: POINTERS, concept_name: "Pointers" }),
      apiNode({
        id: ROOT_ID,
        concept_name: "CS101 - Intro to CS",
        mastery_tier: "subject_root",
        is_subject_root: true,
      }),
    ],
    edges: [],
  } as unknown as Awaited<ReturnType<typeof getGraph>>);
  mockedSessions.mockResolvedValue({ sessions: [] } as Awaited<ReturnType<typeof getSessions>>);
  mockedAttempts.mockResolvedValue({ total: 0, limit: 100, offset: 0, attempts: [] });
});

afterEach(cleanup);

describe("Quick quiz links (§6)", () => {
  it("sends a concept by id, tagged from=tree, returning to its own node", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    await user.click(screen.getByRole("button", { name: /quick quiz/i }));

    expect(push).toHaveBeenCalledWith(
      `/quiz?concept=${RECURSION}&from=tree&return=${encodeURIComponent(`/tree?node=${RECURSION}`)}`,
    );
  });

  it("sends a subject root as its abstract course, returning to the tree", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, ROOT_ID);

    await user.click(screen.getByRole("button", { name: /quick quiz/i }));

    expect(push).toHaveBeenCalledWith(
      `/quiz?course=${COURSE_ID}&from=tree&return=${encodeURIComponent("/tree")}`,
    );
  });
});

describe("?node= focus", () => {
  it("opens the named node's panel", async () => {
    params.value = new URLSearchParams(`node=${POINTERS}`);
    renderTree();

    // The panel's own heading — proof the node is selected, not merely painted.
    expect(await screen.findByRole("heading", { name: "Pointers" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recursion" })).not.toBeInTheDocument();
  });

  it("ignores an id that is not in the graph", async () => {
    params.value = new URLSearchParams("node=node-deleted-last-week");
    renderTree();

    await screen.findByTestId("stub-graph");
    await waitFor(() => expect(mockedGraph).toHaveBeenCalled());
    expect(screen.queryByTestId("tree-node-recent-quizzes")).not.toBeInTheDocument();
  });
});

describe("Recent quizzes", () => {
  it("shows the five newest completed attempts for the selected node only", async () => {
    mockedAttempts.mockResolvedValue({
      total: 8,
      limit: 100,
      offset: 0,
      attempts: [
        // Deliberately out of order on the wire, and the fifth-newest first:
        // the ordering under test is this component's, not the endpoint's.
        attempt({ quiz_id: "q-5th", completed_at: "2026-08-05T10:00:00Z" }),
        attempt({ quiz_id: "q-new", completed_at: "2026-08-21T10:00:00Z" }),
        attempt({ quiz_id: "q-2", completed_at: "2026-08-19T10:00:00Z" }),
        attempt({ quiz_id: "q-3", completed_at: "2026-08-18T10:00:00Z" }),
        attempt({ quiz_id: "q-4", completed_at: "2026-08-17T10:00:00Z" }),
        // Sixth-newest — over the cap, so it never renders.
        attempt({ quiz_id: "q-6th", completed_at: "2026-08-01T10:00:00Z" }),
        // Filtered out: another concept, and an unfinished attempt.
        attempt({ quiz_id: "q-other-node", concept_node_id: POINTERS }),
        attempt({ quiz_id: "q-in-progress", status: "in_progress", completed_at: null }),
      ],
    });
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    const block = await screen.findByTestId("tree-node-recent-quizzes");
    const rows = await within(block).findAllByTestId(/^tree-node-recent-quiz-/);

    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "tree-node-recent-quiz-q-new",
      "tree-node-recent-quiz-q-2",
      "tree-node-recent-quiz-q-3",
      "tree-node-recent-quiz-q-4",
      "tree-node-recent-quiz-q-5th",
    ]);
    expect(within(block).queryByTestId("tree-node-recent-quiz-q-6th")).not.toBeInTheDocument();
    expect(within(block).queryByTestId("tree-node-recent-quiz-q-other-node")).not.toBeInTheDocument();
    expect(within(block).queryByTestId("tree-node-recent-quiz-q-in-progress")).not.toBeInTheDocument();
  });

  it("renders score and a signed whole-percent mastery delta", async () => {
    mockedAttempts.mockResolvedValue({
      total: 3,
      limit: 100,
      offset: 0,
      attempts: [
        attempt({ quiz_id: "q-up", score: 3, total: 3, mastery_delta: 0.04, completed_at: "2026-08-21T10:00:00Z" }),
        attempt({ quiz_id: "q-down", score: 1, total: 4, mastery_delta: -0.02, completed_at: "2026-08-20T10:00:00Z" }),
        attempt({ quiz_id: "q-null", score: 2, total: 3, mastery_delta: null, completed_at: "2026-08-19T10:00:00Z" }),
      ],
    });
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    expect(await screen.findByTestId("tree-node-recent-quiz-q-up")).toHaveTextContent(
      "3/3 · +4% mastery",
    );
    expect(screen.getByTestId("tree-node-recent-quiz-q-down")).toHaveTextContent(
      "1/4 · −2% mastery",
    );
    expect(screen.getByTestId("tree-node-recent-quiz-q-null")).toHaveTextContent(
      "2/3 · — mastery",
    );
  });

  it("says so when the concept has no attempts", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    const block = await screen.findByTestId("tree-node-recent-quizzes");
    await waitFor(() => expect(block).toHaveTextContent("No quizzes yet"));
    // The Quick quiz button above IS the call to action; the empty state must
    // not grow a second one.
    expect(within(block).queryByRole("button")).not.toBeInTheDocument();
  });

  it("never offers history on a subject root", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, ROOT_ID);

    await screen.findByRole("heading", { name: "CS101 - Intro to CS" });
    expect(screen.queryByTestId("tree-node-recent-quizzes")).not.toBeInTheDocument();
    expect(mockedAttempts).not.toHaveBeenCalled();
  });

  it("refetches when a quiz submit announces a graph change", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);
    await waitFor(() => expect(mockedAttempts).toHaveBeenCalledTimes(1));

    mockedAttempts.mockResolvedValue({
      total: 1,
      limit: 100,
      offset: 0,
      attempts: [attempt({ quiz_id: "q-just-finished" })],
    });
    window.dispatchEvent(new CustomEvent("sapling:graph-changed", { detail: {} }));

    expect(await screen.findByTestId("tree-node-recent-quiz-q-just-finished")).toBeInTheDocument();
    expect(mockedAttempts).toHaveBeenCalledTimes(2);
  });
});
