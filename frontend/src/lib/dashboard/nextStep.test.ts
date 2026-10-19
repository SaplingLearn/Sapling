/**
 * nextStepFor: the Dashboard's one primary action per authoritative state
 * (docs/07 §4), and the honesty rules for its copy — no durations, no
 * mastery claims, limitations stated, every destination a Learn/Library
 * navigation (never a write).
 */
import { describe, expect, it } from "vitest";

import { goalText, nextStepFor, type LearnerState, type OpenLoopSession } from "./nextStep";

const ctx = {
  conceptName: (id: string) => ({ a: "Binary Numbers", b: "Bitwise Operators" } as Record<string, string>)[id] ?? null,
  courseLabel: (id: string | null | undefined) => (id === "c1" ? "CS101" : id === "c2" ? "MATH210" : null),
};
const open = (over: Partial<OpenLoopSession> = {}): OpenLoopSession => ({
  sessionId: "s1",
  courseId: "c1",
  topic: "Binary",
  phase: "teach",
  goal: { text: "Read binary", target_node_ids: ["a", "b"] },
  goalVersion: 3,
  diagnosis: null,
  goalProgress: null,
  pendingGrade: null,
  practiceUnavailable: [],
  statusLoaded: true,
  ...over,
});
const step = (s: LearnerState) => nextStepFor(s, ctx);

describe("nextStepFor", () => {
  it.each([
    ["probe", "Resume check-in"],
    ["plan", "Review plan"],
    ["teach", "Continue learning"],
    ["check", "Resume check"],
    ["feedback", "Review feedback"],
    ["close", "See wrap-up"],
  ] as const)("%s resumes the same session (%s)", (phase, label) => {
    const s = step({ kind: "loop-open", session: open({ phase }) });
    expect(s.action).toEqual({ label, href: "/learn?resume=s1" });
  });

  it("pending and error offer no action at all", () => {
    expect(step({ kind: "pending" }).action).toBeNull();
    expect(step({ kind: "error" }).action).toBeNull();
    expect(step({ kind: "error" }).reason).toMatch(/Nothing was started/);
  });

  it("no open session: a deliberate check-in in a named course, with the last session read-only", () => {
    const s = step({ kind: "loop-none", courseId: "c2", lastClosed: { id: "old", topic: "Vectors" } });
    expect(s.action).toEqual({ label: "Start a check-in", href: "/learn?course=c2" });
    expect(s.title).toContain("MATH210");
    expect(s.links[0].href).toBe("/learn?resume=old");
  });

  it("no concepts → the course's Library; no course → Library link and no Learn action", () => {
    expect(step({ kind: "no-concepts", courseId: "c1" }).action?.href).toBe("/library?course=c1");
    const none = step({ kind: "no-course" });
    expect(none.action).toBeNull();
    expect(none.links[0].href).toBe("/library");
  });

  it("goal progress names the next remaining real concept", () => {
    const s = step({
      kind: "loop-open",
      session: open({
        goalProgress: {
          status: "needs_more_practice",
          target_node_ids: ["a", "b"],
          remaining_target_node_ids: ["b"],
          unresolved_prerequisite_ids: [],
          attempted_node_ids: ["a"],
        },
      }),
    });
    expect(s.reason).toBe("1 of 2 goal concepts still needs practice, starting with Bitwise Operators.");
  });

  it("limited / untested evidence is stated as a limitation, never as knowledge", () => {
    const s = step({
      kind: "loop-open",
      session: open({
        phase: "plan",
        diagnosis: {
          status: "limited",
          stop_reason: null,
          skills: [
            { node_id: "a", status: "untested" } as never,
            { node_id: "b", status: "bracketed" } as never,
          ],
        },
      }),
    });
    expect(s.details.join(" ")).toMatch(/couldn't place every concept/);
    expect(s.details.join(" ")).toMatch(/1 concept is not yet placed/);
  });

  it("never claims a duration or mastery", () => {
    const states: LearnerState[] = [
      { kind: "loop-open", session: open({ phase: "teach" }) },
      { kind: "loop-open", session: open({ phase: "close" }) },
      { kind: "loop-none", courseId: "c1", lastClosed: null },
      { kind: "legacy-open", sessionId: "x", topic: "T", courseId: "c1" },
    ];
    for (const s of states) {
      const text = JSON.stringify(step(s));
      expect(text).not.toMatch(/\bmin\b|minutes|you've mastered|you have mastered/i);
    }
    expect(step({ kind: "loop-open", session: open({ phase: "close" }) }).reason).toMatch(/isn't the same as mastering/);
  });

  it("a saved answer that hasn't finished checking is recovered first, in the same session", () => {
    const s = step({ kind: "loop-open", session: open({ phase: "check", pendingGrade: { kind: "check", question_hash: "h" } }) });
    expect(s.action).toEqual({ label: "Finish checking", href: "/learn?resume=s1" });
    expect(s.reason).toMatch(/don't need to answer again/);
  });

  it("practice-unavailable goal concepts are named as unresolved, not known", () => {
    const s = step({ kind: "loop-open", session: open({ practiceUnavailable: ["b"] }) });
    expect(s.details).toContain("1 goal concept has no fresh practice question right now; it stays unresolved.");
  });

  it("legacy (kill switch) resumes or starts the legacy tutor", () => {
    expect(step({ kind: "legacy-open", sessionId: "x", topic: "T", courseId: null }).action?.href).toBe("/learn?resume=x");
    expect(step({ kind: "legacy-none" }).action?.href).toBe("/learn");
  });
});

describe("goalText", () => {
  it("uses the confirmed goal and its real concept names", () => {
    expect(goalText(open(), ctx)).toEqual({ text: "Read binary", scope: "Binary Numbers · Bitwise Operators" });
  });
  it("a whole-course session says so", () => {
    expect(goalText(open({ goal: null }), ctx)).toEqual({ text: "Explore CS101", scope: "Whole course" });
  });
});
