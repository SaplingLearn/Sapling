/**
 * The pure halves of the Tutor V2 fixes (PR #866 review): which side columns
 * fit (U5), the plan in the history (U2), the "Check me" note (NC), the chat
 * Retry's log edit (F11a) and the due line (F11b).
 */
import { describe, expect, it } from "vitest";
import type { ChatMsg } from "../chat/ChatPanel";
import type { LoopCheckNext } from "@/lib/api";
import { MIN_CHAT_W, PANEL_W, SIDEBAR_W, tutorColumns } from "./tutor/useTutorLayout";
import { EMPTY_PLAN_COPY, PROBE_PHASE_OPENERS, planTurnText, withPlanHistory } from "./loopHistory";
import { NO_ITEM_COPY, PLAN_DONE_COPY, PREPARING_COPY, checkMeNote } from "./checkNote";
import { dropInterruptedTurn } from "./chatRetry";
import { dueCountText } from "./tutor/SessionPanel";

describe("tutorColumns (U5)", () => {
  const both = MIN_CHAT_W + SIDEBAR_W + PANEL_W;
  it("unmeasured or wide: both open", () => {
    expect(tutorColumns(null, null, null)).toEqual({ side: true, panel: true });
    expect(tutorColumns(both, null, null)).toEqual({ side: true, panel: true });
  });
  it("too narrow for both: the panel gives way first, then the sidebar", () => {
    expect(tutorColumns(both - 1, null, null)).toEqual({ side: true, panel: false });
    expect(tutorColumns(MIN_CHAT_W + SIDEBAR_W - 1, null, null)).toEqual({ side: false, panel: false });
  });
  it("the student's own choice always stands; the sidebar gives way to a panel they asked for", () => {
    expect(tutorColumns(both - 1, null, true)).toEqual({ side: false, panel: true });
    expect(tutorColumns(both - 1, true, true)).toEqual({ side: true, panel: true });
    expect(tutorColumns(both + 500, false, false)).toEqual({ side: false, panel: false });
  });
  it("a panel that cannot show (no live session on screen) never pushes the sidebar out", () => {
    expect(tutorColumns(both - 1, null, true, false)).toEqual({ side: true, panel: true });
  });
});

describe("withPlanHistory (U2)", () => {
  const msg = (id: string, role: "user" | "assistant", content: string): ChatMsg => ({ id, role, content });
  const plan = [
    { node_id: "a", concept_name: "Big-O (worst case)", kind: "review" },
    { node_id: "b", concept_name: "Heaps", kind: "new", reason: "goal" as const },
  ];
  it("puts the approved plan in the opener's row", () => {
    const out = withPlanHistory([msg("m0", "assistant", PROBE_PHASE_OPENERS[0]), msg("m1", "user", "hi")], plan);
    expect(out.map((m) => m.id)).toEqual(["m0", "m1"]);
    expect(out[0].content).toBe(planTurnText(plan));
    expect(out[0].content).toContain("1. Big\\-O \\(worst case\\) — Due for review"); // markdown-escaped
    expect(out[0].content).toContain("2. Heaps — Your selected goal");
  });
  it("an empty plan says so; an unknown one drops the opener", () => {
    expect(withPlanHistory([msg("m0", "assistant", PROBE_PHASE_OPENERS[1])], [])[0].content).toBe(EMPTY_PLAN_COPY);
    expect(withPlanHistory([msg("m0", "assistant", PROBE_PHASE_OPENERS[0]), msg("m1", "assistant", "next")], null).map((m) => m.id)).toEqual(["m1"]);
  });
  it("any other first row (a quiz-ask opener, a student's message) is left alone", () => {
    const rows = [msg("m0", "assistant", "Let's look at your quiz question. What does n do?")];
    expect(withPlanHistory(rows, plan)).toBe(rows);
    const later = [msg("m0", "user", "hi"), msg("m1", "assistant", PROBE_PHASE_OPENERS[0])];
    expect(withPlanHistory(later, plan)).toBe(later);
  });
});

describe("checkMeNote (NC)", () => {
  const names = new Map([["n1", "Recursion"], ["n2", "Stacks"], ["n3", "Queues"]]);
  const r = (over: Partial<LoopCheckNext>): LoopCheckNext => ({ phase: "teach", check: null, ...over });
  it("names the concepts with no check question yet", () => {
    expect(checkMeNote(r({ plan_done: true, checks_unavailable_node_ids: ["n1"] }), names)).toBe(
      "No check questions are ready yet for Recursion. You can keep learning with the tutor, or wrap up the session when you're ready.",
    );
    expect(checkMeNote(r({ checks_unavailable_node_ids: ["n1", "n2", "n3"] }), names)).toContain("for Recursion, Stacks and Queues.");
  });
  it("plan done only when none was left unchecked; preparing and fresh practice keep theirs", () => {
    expect(checkMeNote(r({ plan_done: true, checks_unavailable_node_ids: [] }), names)).toBe(PLAN_DONE_COPY);
    expect(checkMeNote(r({ plan_done: true }), names)).toBe(PLAN_DONE_COPY);
    expect(checkMeNote(r({}), names)).toBe(NO_ITEM_COPY);
    expect(checkMeNote(r({ preparing: true, checks_unavailable_node_ids: ["n1"] }), names)).toBe(PREPARING_COPY);
    expect(checkMeNote(r({ practice_unavailable_node_ids: ["n1"], checks_unavailable_node_ids: ["n1"] }), names)).toBeNull();
  });
});

describe("dropInterruptedTurn (F11a)", () => {
  it("drops the interrupted bubble and the student's message right before it", () => {
    const rows: ChatMsg[] = [
      { id: "a", role: "assistant", content: "hello" },
      { id: "u", role: "user", content: "why?" },
      { id: "x", role: "assistant", content: "", interrupted: true, retryText: "why?" },
    ];
    expect(dropInterruptedTurn(rows, "x", "why?").map((m) => m.id)).toEqual(["a"]);
    expect(dropInterruptedTurn(rows, "missing", "why?")).toBe(rows);
  });
});

describe("dueCountText (F11b)", () => {
  it("counts reviews, not courses", () => {
    expect(dueCountText(null)).toBe("Flashcards and retention checks");
    expect(dueCountText(0)).toBe("Nothing due right now");
    expect(dueCountText(1)).toBe("1 review due");
    expect(dueCountText(4)).toBe("4 reviews due");
  });
});
