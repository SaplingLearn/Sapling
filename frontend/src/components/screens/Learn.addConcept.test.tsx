// @vitest-environment jsdom
/**
 * The reported bug, end-to-end through the real rendered rail:
 *
 *   "when deleting a concept node, i should be able to add it back of the same
 *    name by add concept"
 *
 * Why this has to be a COMPONENT test and not another pure-resolver test:
 * the first attempt at this fix was a `resolveAddConceptCourseId` fallback in
 * `addConcept`, unit-tested and green — and completely unreachable. The
 * composer that calls `addConcept` was itself gated on `cardCourseId`, the
 * exact value the fallback existed to work around, so on the delete that
 * cleared the focus the whole "＋ Add concept" affordance unmounted and the
 * student could not type the name back in at all. No amount of resolver
 * testing could see that, because the gap was in the WIRING: which value the
 * render gate reads. These tests click Remove on the real focus card and then
 * look for the real button.
 *
 * The delete-failure tests cover the other half: a 404 from
 * DELETE /api/graph/{user}/nodes/{id} means the row was already gone (see
 * routes/graph.py::remove_node), so restoring the node would put a phantom
 * concept back on the map under a toast claiming "it's still on your map"
 * about something that is not there.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// `vi.mock` factories are hoisted above every top-level statement AND run on
// first import of the mocked module, so everything they close over — fixtures
// included — has to live in `vi.hoisted`, not in plain consts. (A plain const
// is still in its TDZ when a transitive import of @/lib/api triggers the
// factory.)
//
// `ApiError` is redeclared here rather than imported because @/lib/api is
// itself mocked: `instanceof ApiError` inside lib/errorMessage.ts has to see
// the same class the component's import resolves to.
const h = vi.hoisted(() => {
  class ApiError extends Error {
    readonly status: number;
    constructor(message: string, status: number) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }
  const course = {
    enrollment_id: "e1",
    course_id: "cs132",
    course_code: "CS 132",
    course_name: "Discrete Math",
    school: "",
    department: "",
    color: "#123456",
    nickname: null,
    node_count: 2,
    enrolled_at: "2026-01-01T00:00:00Z",
    term: "",
  };
  // The graph as the API returns it: a subject root plus one concept, both in
  // cs132. The session's topic matches the concept's name, so the rail focuses
  // it and `cardCourseId` resolves off the NODE — which is the whole setup,
  // since the course picker stays at its "" ("No course") default.
  const apiNodes = [
    {
      id: "root-cs132",
      concept_name: "Discrete Math",
      mastery_score: 1,
      mastery_tier: "subject_root",
      times_studied: 0,
      last_studied_at: null,
      subject: "Discrete Math",
      course_id: "cs132",
      is_subject_root: true,
    },
    {
      id: "n-markov",
      concept_name: "Markov Chains",
      mastery_score: 0.2,
      mastery_tier: "struggling",
      times_studied: 1,
      last_studied_at: null,
      subject: "Discrete Math",
      course_id: "cs132",
      description: "Stored description, so no describeConcept fetch fires.",
    },
    // A second concept that is NOT the session topic. It's the only way to
    // observe the focus restore on a failed delete: for the topic's own node,
    // `highlightId` re-derives the focus from the topic name anyway, so the
    // focus card comes back whether or not the catch restores it.
    {
      id: "n-eigen",
      concept_name: "Eigenvalues",
      mastery_score: 0.5,
      mastery_tier: "learning",
      times_studied: 2,
      last_studied_at: null,
      subject: "Discrete Math",
      course_id: "cs132",
      description: "Stored description, so no describeConcept fetch fires.",
    },
  ];
  return {
    ApiError,
    course,
    apiNodes,
    addGraphNode: vi.fn(),
    deleteGraphNode: vi.fn(),
    // Nothing here asserts on rendered toast markup (it portals); the spy is
    // what the assertions read.
    toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
    router: { push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => h.router,
  // Resume deep-link: drops straight into the active session (and therefore
  // the rail) without driving the topic picker. The session itself carries
  // course_id: null below, so `selectedCourseId` stays "".
  useSearchParams: () => new URLSearchParams("resume=sess-1"),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));

// Three.js / next/dynamic — neither renders in jsdom and neither is under test.
vi.mock("../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: () => null,
}));

vi.mock("../ToastProvider", () => ({ useToast: () => h.toast }));

vi.mock("@/lib/api", () => ({
  ApiError: h.ApiError,
  addGraphNode: h.addGraphNode,
  deleteGraphNode: h.deleteGraphNode,
  getSessions: vi.fn(async () => ({ sessions: [] })),
  getCourses: vi.fn(async () => ({ courses: [h.course] })),
  getGraph: vi.fn(async () => ({ nodes: h.apiNodes, edges: [], stats: {} })),
  resumeSession: vi.fn(async () => ({
    session: { id: "sess-1", topic: "Markov Chains", mode: "socratic", course_id: null },
    messages: [],
  })),
  describeConcept: vi.fn(async () => ({ description: "" })),
  startSession: vi.fn(),
  startSessionStream: vi.fn(),
  sendChat: vi.fn(),
  streamChat: vi.fn(),
  deleteSession: vi.fn(),
  renameSession: vi.fn(),
  endSession: vi.fn(),
  switchMode: vi.fn(),
  learnAction: vi.fn(),
  shouldFallBackToJson: vi.fn(() => false),
  fetchSettings: vi.fn(async () => ({ settings: { share_course_context: false } })),
  updateSettings: vi.fn(async () => ({})),
}));

import { Learn } from "./Learn";

/** The rail, focused on "Markov Chains", with the course picker untouched. */
async function renderFocusedRail() {
  const user = userEvent.setup();
  render(<Learn />);
  // The rail's focus card for the session's concept; also proves the resume
  // and bootstrap fetches landed before anything is clicked.
  expect(await screen.findByRole("button", { name: "Remove" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /Add concept/ })).toBeTruthy();
  return user;
}

// Both failure paths log before they decide what to do, so the log is the
// deterministic sync point for asserting on the decision — including the
// NEGATIVE one (404 restores nothing), where waiting on a rendered change is
// not an option. Mocked rather than merely spied so the deliberate rejections
// don't dump stack traces into the run.
let errorLog: MockInstance;

beforeEach(() => {
  localStorage.clear();
  // The disclaimer modal renders over everything and is unrelated.
  localStorage.setItem("sapling_disclaimer_ack", "true");
  // jsdom has no ResizeObserver; the rail's width tracker constructs one on
  // mount (same stub as Dashboard.test.tsx).
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  h.router.push.mockClear();
  h.router.replace.mockClear();
  h.toast.success.mockClear();
  h.toast.error.mockClear();
  h.addGraphNode.mockReset();
  h.deleteGraphNode.mockReset();
  h.deleteGraphNode.mockResolvedValue({ deleted: true });
  h.addGraphNode.mockResolvedValue({
    node: { id: "n-markov-2", concept_name: "Markov Chains", subject: "Discrete Math", course_id: "cs132", mastery_score: 0, mastery_tier: "unexplored", times_studied: 0, last_studied_at: null },
    already_existed: false,
  });
  errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("delete the focused concept, then add it back (no course picked)", () => {
  it("keeps the ＋ Add concept affordance mounted after the delete clears the focus", async () => {
    const user = await renderFocusedRail();

    await user.click(screen.getByRole("button", { name: "Remove" }));

    // Focus is gone with the node, so `cardCourseId` is now null — this is the
    // exact state in which the affordance used to unmount.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    });
    expect(screen.getByRole("button", { name: /Add concept/ })).toBeTruthy();
  });

  it("adds the concept back under the deleted node's course", async () => {
    const user = await renderFocusedRail();

    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(h.deleteGraphNode).toHaveBeenCalledWith("u1", "n-markov"));

    await user.click(screen.getByRole("button", { name: /Add concept/ }));
    await user.type(screen.getByPlaceholderText("New concept name…"), "Markov Chains");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(h.addGraphNode).toHaveBeenCalledWith("u1", expect.objectContaining({
      concept_name: "Markov Chains",
      course_id: "cs132",
    }));
  });

  it("names the course the concept will land in, so the fallback isn't silent", async () => {
    const user = await renderFocusedRail();

    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: /Add concept/ }));

    expect(screen.getByTestId("tutor-add-concept-course").textContent).toContain("CS 132");
  });
});

describe("a failed delete", () => {
  it("treats 404 as success — the row is already gone, so nothing is restored", async () => {
    h.deleteGraphNode.mockRejectedValue(new h.ApiError('{"detail":"Node not found"}', 404));
    const user = await renderFocusedRail();

    await user.click(screen.getByRole("button", { name: "Remove" }));
    // The catch has run and any state update it would make is committed, so
    // the assertions below are a real negative rather than a race the fix
    // happens to win.
    await waitFor(() => {
      expect(errorLog).toHaveBeenCalledWith(
        "[removeConcept] failed",
        expect.objectContaining({ nodeId: "n-markov" }),
      );
    });

    // No focus card (the restore would bring it back — see the 500 case
    // below), no phantom concept in the branch list, and no toast claiming
    // it's "still on your map" about a row that does not exist.
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Markov Chains" })).toBeNull();
    expect(h.toast.error).not.toHaveBeenCalled();
  });

  it("restores the node and an honest toast on a genuine failure", async () => {
    h.deleteGraphNode.mockRejectedValue(new h.ApiError("Internal Server Error", 500));
    const user = await renderFocusedRail();

    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();
    });
    expect(h.toast.error).toHaveBeenCalledTimes(1);
    const message = h.toast.error.mock.calls[0][0] as string;
    expect(message).toContain("still on your map");
    // humanizeError, not the raw body: no JSON, no HTML, no bare status code.
    expect(message).not.toContain("{");
    expect(message).toContain("Something went wrong on our end.");
  });

  it("puts the focus back on the concept it restored, not on the session topic", async () => {
    h.deleteGraphNode.mockRejectedValue(new h.ApiError("Internal Server Error", 500));
    const user = await renderFocusedRail();

    // Focus a concept that isn't the session topic, then delete it. Restoring
    // the node but not the focus left "Eigenvalues" back on the map while the
    // rail silently snapped to the topic's card — so the composer and the
    // Remove button the student needed to retry with belonged to a different
    // concept than the one whose delete had just failed.
    await user.click(screen.getByRole("button", { name: "Eigenvalues" }));
    expect(screen.getByTestId("tutor-focus-quiz").getAttribute("title"))
      .toBe("Quiz me on Eigenvalues");

    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(screen.getByTestId("tutor-focus-quiz").getAttribute("title"))
        .toBe("Quiz me on Eigenvalues");
    });
  });
});

describe("a failed add", () => {
  it("rolls back and reports the reason without printing the raw body", async () => {
    h.addGraphNode.mockRejectedValue(new h.ApiError('{"detail":"Not Found"}', 404));
    const user = await renderFocusedRail();

    await user.click(screen.getByRole("button", { name: /Add concept/ }));
    await user.type(screen.getByPlaceholderText("New concept name…"), "Eigenvalues");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(h.toast.error).toHaveBeenCalled());
    const message = h.toast.error.mock.calls[0][0] as string;
    expect(message).toContain("Eigenvalues");
    // The regression: `ApiError.message` is the RAW response body, so the old
    // interpolation put `{"detail":"Not Found"}` in front of the student.
    expect(message).not.toContain('{"detail"');
    expect(message).not.toContain("404");
  });
});
