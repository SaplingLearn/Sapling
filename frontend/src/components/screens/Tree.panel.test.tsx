// @vitest-environment jsdom
/**
 * The Tree screen's own surface, outside the quiz thread `Tree.quiz.test.tsx`
 * already pins: the node detail panel (tiles, Learn this, the two-click
 * delete, past sessions), the toolbar (search, mastery-tier pills, the #330
 * add-concept composer), the graph wiring (highlight and course focus),
 * fullscreen, and the mobile bottom sheet.
 *
 * The graph renderer is stubbed to a node list of buttons that also echoes
 * the props the screen hands it, so the wiring is assertable without a canvas.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { GraphNode } from "@/lib/data";

const push = vi.fn();
const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
const mobile = vi.hoisted(() => ({ value: false }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => params.value,
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Ada" }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => mobile.value }));

vi.mock("../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: ({
    nodes,
    onNodeClick,
    highlightId,
    focusCourseId,
  }: {
    nodes: GraphNode[];
    onNodeClick?: (n: GraphNode) => void;
    highlightId?: string;
    focusCourseId?: string | null;
  }) => (
    <div
      data-testid="stub-graph"
      data-highlight={highlightId ?? ""}
      data-focus-course={focusCourseId === undefined ? "undefined" : String(focusCourseId)}
    >
      {nodes.map((n) => (
        <button key={n.id} data-testid={`stub-node-${n.id}`} onClick={() => onNodeClick?.(n)}>
          {n.name}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("../Skeleton", () => ({ GraphPanelSkeleton: () => <div data-testid="stub-skeleton" /> }));
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
import { addGraphNode, deleteGraphNode, getCourses, getGraph, getSessions } from "@/lib/api";
import { listAttempts } from "@/lib/quiz/api";

const mockedGraph = vi.mocked(getGraph);
const mockedCourses = vi.mocked(getCourses);
const mockedSessions = vi.mocked(getSessions);
const mockedAttempts = vi.mocked(listAttempts);
const mockedAdd = vi.mocked(addGraphNode);
const mockedDelete = vi.mocked(deleteGraphNode);

const COURSE_ID = "course-cs101";
const ROOT_ID = `subject_root__${COURSE_ID}`;
const RECURSION = "node-recursion";
const POINTERS = "node-pointers";
const LOOPS = "node-loops";

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

function session(id: string, topic: string, over: Record<string, unknown> = {}) {
  return {
    id,
    topic,
    mode: "socratic",
    message_count: 7,
    started_at: "2026-08-20T10:00:00Z",
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

async function selectNode(user: ReturnType<typeof userEvent.setup>, id: string) {
  await user.click(await screen.findByTestId(`stub-node-${id}`));
}

function graphNodeIds(): string[] {
  return within(screen.getByTestId("stub-graph"))
    .queryAllByTestId(/^stub-node-/)
    .map((b) => b.getAttribute("data-testid")!.replace("stub-node-", ""));
}

beforeEach(() => {
  vi.clearAllMocks();
  params.value = new URLSearchParams();
  mobile.value = false;
  window.localStorage.clear();
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
      apiNode({ id: RECURSION, concept_name: "Recursion", mastery_score: 0.456 }),
      apiNode({
        id: POINTERS,
        concept_name: "Pointers",
        mastery_tier: "mastered",
        mastery_score: 0.9,
        last_studied_at: "2026-08-20T10:00:00Z",
      }),
      apiNode({ id: LOOPS, concept_name: "Loops", mastery_tier: "struggling", subject: "Loopy Subject" }),
      apiNode({
        id: ROOT_ID,
        concept_name: "CS101 - Intro to CS",
        mastery_tier: "subject_root",
        is_subject_root: true,
      }),
    ],
    edges: [],
  } as unknown as Awaited<ReturnType<typeof getGraph>>);
  mockedSessions.mockResolvedValue({ sessions: [] } as unknown as Awaited<ReturnType<typeof getSessions>>);
  mockedAttempts.mockResolvedValue({ total: 0, limit: 100, offset: 0, attempts: [] });
});

afterEach(cleanup);

describe("loading", () => {
  it("shows the skeleton until the graph lands, then the graph", async () => {
    renderTree();
    expect(screen.getByTestId("stub-skeleton")).toBeInTheDocument();
    expect(await screen.findByTestId("stub-graph")).toBeInTheDocument();
    expect(screen.queryByTestId("stub-skeleton")).not.toBeInTheDocument();
    expect(screen.getByTestId("graph-fullscreen")).toBeInTheDocument();
    expect(mockedGraph).toHaveBeenCalledWith("u1", undefined);
    expect(mockedSessions).toHaveBeenCalledWith("u1", 50);
  });
});

describe("detail panel", () => {
  it("shows the node's course, name, mastery, tier and last-studied", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    const panel = screen.getByRole("complementary");
    expect(within(panel).getByRole("heading", { name: "Recursion" })).toBeInTheDocument();
    expect(panel).toHaveTextContent("Intro to CS");
    expect(panel).toHaveTextContent("Mastery46%");
    expect(panel).toHaveTextContent("Tierlearning");
    expect(panel).toHaveTextContent("Last studiednever");
    expect(within(panel).getByRole("button", { name: /delete concept/i })).toBeInTheDocument();
  });

  it("formats a real last-studied time and highlights the selected node", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, POINTERS);

    const panel = screen.getByRole("complementary");
    expect(panel).toHaveTextContent(new Date("2026-08-20T10:00:00Z").toLocaleString());
    expect(panel).toHaveTextContent("Mastery90%");
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-highlight", POINTERS);
  });

  it("closes from its X button", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    await user.click(screen.getByRole("button", { name: "Close detail panel" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-highlight", "");
  });

  it("Learn this opens the tutor on the concept", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    await user.click(screen.getByRole("button", { name: /learn this/i }));
    expect(push).toHaveBeenCalledWith(`/learn?topic=Recursion&mode=socratic&course=${COURSE_ID}`);
  });

  it("Learn this on a subject root opens the course without a topic", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, ROOT_ID);

    await user.click(screen.getByRole("button", { name: /learn this/i }));
    expect(push).toHaveBeenCalledWith(`/learn?mode=socratic&course=${COURSE_ID}`);
    expect(screen.queryByRole("button", { name: /delete concept/i })).not.toBeInTheDocument();
  });

  it("deletes on the second click, closes the panel and reloads", async () => {
    mockedDelete.mockResolvedValue(undefined as never);
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    await user.click(screen.getByRole("button", { name: /delete concept/i }));
    expect(mockedDelete).not.toHaveBeenCalled();
    const armed = screen.getByRole("button", { name: /click again to confirm/i });
    expect(armed).toHaveStyle({ color: "var(--err)" });

    await user.click(armed);
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("u1", RECURSION));
    expect(await screen.findByText('Deleted "Recursion".')).toBeInTheDocument();
    await waitFor(() => expect(mockedGraph).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("toasts a failed delete and keeps the panel", async () => {
    mockedDelete.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    await user.click(screen.getByRole("button", { name: /delete concept/i }));
    await user.click(screen.getByRole("button", { name: /click again to confirm/i }));
    expect(await screen.findByText("Delete failed: boom")).toBeInTheDocument();
    expect(screen.getByRole("complementary")).toBeInTheDocument();
  });

  it("lists up to four sessions on the concept and resumes one", async () => {
    mockedSessions.mockResolvedValue({
      sessions: [
        session("s1", "recursion", { mode: "socratic", message_count: 3 }),
        session("s2", "Recursion", { mode: "expository" }),
        session("s3", "RECURSION"),
        session("s4", "Recursion"),
        session("s5", "Recursion"),
        session("s-other", "Pointers"),
      ],
    } as unknown as Awaited<ReturnType<typeof getSessions>>);
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    const panel = screen.getByRole("complementary");
    expect(panel).toHaveTextContent("Sessions for this concept");
    const rows = within(panel)
      .getAllByRole("button")
      .filter((b) => /msgs/.test(b.textContent || ""));
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent(
      `socratic3 msgs · ${new Date("2026-08-20T10:00:00Z").toLocaleDateString()}`,
    );
    expect(rows[1]).toHaveTextContent("expository");

    await user.click(rows[1]);
    expect(push).toHaveBeenCalledWith("/learn?resume=s2");
  });

  it("has no sessions block when no session matches", async () => {
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);
    expect(screen.getByRole("complementary")).not.toHaveTextContent("Sessions for this concept");
  });

  it("selects the ?suggest= node by name, case-insensitively, and highlights it", async () => {
    params.value = new URLSearchParams("suggest=pointers");
    renderTree();

    expect(await screen.findByRole("heading", { name: "Pointers" })).toBeInTheDocument();
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-highlight", POINTERS);
  });

  it("highlights the ?suggest= node over a different selection", async () => {
    params.value = new URLSearchParams("suggest=pointers");
    const user = userEvent.setup();
    renderTree();
    await screen.findByRole("heading", { name: "Pointers" });

    await selectNode(user, RECURSION);
    expect(await screen.findByRole("heading", { name: "Recursion" })).toBeInTheDocument();
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-highlight", POINTERS);
  });
});

describe("toolbar filters", () => {
  it("search matches concept name or subject", async () => {
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");
    expect(graphNodeIds()).toEqual([RECURSION, POINTERS, LOOPS, ROOT_ID]);

    await user.type(screen.getByLabelText("Search concepts"), "  POINT ");
    expect(graphNodeIds()).toEqual([POINTERS]);

    await user.clear(screen.getByLabelText("Search concepts"));
    await user.type(screen.getByLabelText("Search concepts"), "loopy");
    expect(graphNodeIds()).toEqual([LOOPS]);
  });

  it("tier pills keep matching concepts and every subject root", async () => {
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");

    await user.click(screen.getByRole("button", { name: "Mastered" }));
    expect(graphNodeIds()).toEqual([POINTERS, ROOT_ID]);

    await user.click(screen.getByRole("button", { name: "Struggling" }));
    expect(graphNodeIds()).toEqual([LOOPS, ROOT_ID]);

    await user.click(screen.getByRole("button", { name: "All" }));
    expect(graphNodeIds()).toEqual([RECURSION, POINTERS, LOOPS, ROOT_ID]);
  });
});

describe("course key + add concept (#330)", () => {
  it("offers Add concept only once a course is picked, and focuses the graph on it", async () => {
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");
    expect(screen.queryByTestId("graph-add-concept")).not.toBeInTheDocument();
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-focus-course", "null");

    await user.click(screen.getByTestId(`graph-course-filter-${COURSE_ID}`));
    expect(screen.getByTestId("graph-add-concept")).toBeInTheDocument();
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-focus-course", COURSE_ID);

    // Picking it again zooms back out and withdraws the composer; the hovered
    // key row keeps its course in focus until the pointer leaves it.
    await user.click(screen.getByTestId(`graph-course-filter-${COURSE_ID}`));
    expect(screen.queryByTestId("graph-add-concept")).not.toBeInTheDocument();
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-focus-course", COURSE_ID);
    await user.unhover(screen.getByTestId(`graph-course-filter-${COURSE_ID}`));
    expect(screen.getByTestId("stub-graph")).toHaveAttribute("data-focus-course", "null");
  });

  it("submits on Enter, anchored on the selected node of that course", async () => {
    mockedAdd.mockResolvedValue({ already_existed: false } as Awaited<ReturnType<typeof addGraphNode>>);
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);
    await user.click(screen.getByTestId(`graph-course-filter-${COURSE_ID}`));
    await user.click(screen.getByTestId("graph-add-concept"));

    const input = screen.getByTestId("graph-add-concept-input");
    expect(input).toHaveFocus();
    expect(screen.getByTestId("graph-add-concept-submit")).toBeDisabled();

    await user.type(input, "  Trees  ");
    expect(screen.getByTestId("graph-add-concept-submit")).toBeEnabled();
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(mockedAdd).toHaveBeenCalledWith("u1", {
        concept_name: "Trees",
        course_id: COURSE_ID,
        anchor_node_id: RECURSION,
      }),
    );
    expect(await screen.findByText("Added “Trees”.")).toBeInTheDocument();
    await waitFor(() => expect(mockedGraph).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("graph-add-concept-input")).not.toBeInTheDocument();
    expect(screen.getByTestId("graph-add-concept")).toBeInTheDocument();
  });

  it("the Add button submits too, with no anchor when nothing is selected, and says when it merged", async () => {
    mockedAdd.mockResolvedValue({ already_existed: true } as Awaited<ReturnType<typeof addGraphNode>>);
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");
    await user.click(screen.getByTestId(`graph-course-filter-${COURSE_ID}`));
    await user.click(screen.getByTestId("graph-add-concept"));
    await user.type(screen.getByTestId("graph-add-concept-input"), "Recursion");
    await user.click(screen.getByTestId("graph-add-concept-submit"));

    await waitFor(() =>
      expect(mockedAdd).toHaveBeenCalledWith("u1", {
        concept_name: "Recursion",
        course_id: COURSE_ID,
        anchor_node_id: undefined,
      }),
    );
    expect(await screen.findByText("Merged into your existing “Recursion” node.")).toBeInTheDocument();
  });

  it("keeps the composer open and toasts when the add fails", async () => {
    mockedAdd.mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");
    await user.click(screen.getByTestId(`graph-course-filter-${COURSE_ID}`));
    await user.click(screen.getByTestId("graph-add-concept"));
    await user.type(screen.getByTestId("graph-add-concept-input"), "Heaps{Enter}");

    expect(await screen.findByText("Couldn't add the concept.")).toBeInTheDocument();
    expect(screen.getByTestId("graph-add-concept-input")).toHaveValue("Heaps");
    expect(mockedGraph).toHaveBeenCalledTimes(1);
  });

  it("Escape cancels and clears the draft", async () => {
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");
    await user.click(screen.getByTestId(`graph-course-filter-${COURSE_ID}`));
    await user.click(screen.getByTestId("graph-add-concept"));
    await user.type(screen.getByTestId("graph-add-concept-input"), "Draft{Escape}");

    expect(screen.queryByTestId("graph-add-concept-input")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("graph-add-concept"));
    expect(screen.getByTestId("graph-add-concept-input")).toHaveValue("");
    expect(mockedAdd).not.toHaveBeenCalled();
  });
});

describe("fullscreen", () => {
  it("opens from the graph corner and closes on Escape", async () => {
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");

    await user.click(screen.getByTestId("graph-fullscreen"));
    expect(screen.getByText("Press Esc to exit")).toBeInTheDocument();
    expect(screen.getAllByTestId("stub-graph")).toHaveLength(2);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Press Esc to exit")).not.toBeInTheDocument();
  });

  it("a node tap in fullscreen selects it and exits", async () => {
    const user = userEvent.setup();
    renderTree();
    await screen.findByTestId("stub-graph");
    await user.click(screen.getByTestId("graph-fullscreen"));

    const fullscreenGraph = screen.getAllByTestId("stub-graph")[1];
    await user.click(within(fullscreenGraph).getByTestId(`stub-node-${POINTERS}`));
    expect(screen.queryByText("Press Esc to exit")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pointers" })).toBeInTheDocument();
  });
});

describe("mobile bottom sheet", () => {
  it("renders the panel in a sheet that closes from the backdrop only", async () => {
    mobile.value = true;
    const user = userEvent.setup();
    renderTree();
    await selectNode(user, RECURSION);

    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    const heading = screen.getByRole("heading", { name: "Recursion" });
    const sheet = heading.parentElement!;
    expect(sheet).toHaveClass("slide-up");

    await user.click(sheet);
    expect(screen.getByRole("heading", { name: "Recursion" })).toBeInTheDocument();

    await user.click(sheet.parentElement!);
    expect(screen.queryByRole("heading", { name: "Recursion" })).not.toBeInTheDocument();
  });
});
