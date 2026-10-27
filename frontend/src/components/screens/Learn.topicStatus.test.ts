/**
 * The per-turn course-scope chip contract (`nextTopicChipState`).
 *
 * Backend side: services/course_scope.py labels each turn covered / new /
 * unknown and the tutor's reply is forbidden from mentioning coverage at
 * all. This helper is the client half — it decides whether the quiet "New"
 * chip appears, and it is the only place that decision is made.
 *
 * The two failure modes it exists to prevent:
 *   - a chip on `unknown` (the backend could not tell), which would assert a
 *     novelty nobody established — the same class of claim-without-evidence
 *     the disclaimer bug was;
 *   - a stale tooltip, where a later in-scope turn leaves the previous
 *     question's words showing.
 */

import { describe, it, expect } from "vitest";

import { nextTopicChipState } from "./Learn";

describe("nextTopicChipState", () => {
  it("raises the chip and remembers the question on a `new` verdict", () => {
    expect(nextTopicChipState({ topic_status: "new" }, "explain eigenvalue decomposition")).toEqual({
      status: "new",
      text: "explain eigenvalue decomposition",
    });
  });

  it("clears both on a covered turn, so the chip is per-turn not per-session", () => {
    expect(nextTopicChipState({ topic_status: "covered" }, "and the chain rule?")).toEqual({
      status: "covered",
      text: "",
    });
  });

  it("shows nothing when the backend could not tell", () => {
    expect(nextTopicChipState({ topic_status: "unknown" }, "q")).toEqual({
      status: "unknown",
      text: "",
    });
  });

  it("treats a backend that never sent the field as unknown, not as new", () => {
    expect(nextTopicChipState({}, "q")).toEqual({ status: "unknown", text: "" });
    expect(nextTopicChipState({ topic_status: undefined }, "q")).toEqual({
      status: "unknown",
      text: "",
    });
  });
});
