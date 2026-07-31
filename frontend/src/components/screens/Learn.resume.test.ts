/**
 * Pure helpers behind the #164 deep-link resume and the ADR-0020 Retry:
 *
 *  - readResumeParam: /learn?resume=<id> is the contract both callers use
 *    (Dashboard "Where you left off", Tree session rows); legacy ?session=
 *    links must keep working. The bug being pinned: Learn read only
 *    topic/mode/course/suggest, so both params were silently dropped and the
 *    dashboard cards were dead buttons.
 *
 *  - removeInterruptedTurn: Retry re-dispatches through `send`, which appends
 *    its own user bubble — so the failed turn's pair must come out first, and
 *    ONLY that pair (never an earlier identical user message).
 */
import { describe, it, expect } from "vitest";

import { readResumeParam, removeInterruptedTurn } from "./Learn";
import type { ChatMsg } from "../chat/ChatPanel";

describe("readResumeParam (#164)", () => {
  it("reads ?resume=", () => {
    expect(readResumeParam(new URLSearchParams("resume=sess-1&mode=socratic"))).toBe("sess-1");
  });

  it("accepts the legacy ?session= alias", () => {
    expect(readResumeParam(new URLSearchParams("session=sess-2"))).toBe("sess-2");
  });

  it("prefers ?resume= when both are present", () => {
    expect(readResumeParam(new URLSearchParams("resume=a&session=b"))).toBe("a");
  });

  it("returns null when neither is present", () => {
    expect(readResumeParam(new URLSearchParams("topic=Recursion&mode=socratic"))).toBeNull();
  });
});

describe("removeInterruptedTurn (ADR 0020)", () => {
  const turn = (over: Partial<ChatMsg> & { id: string; role: ChatMsg["role"]; content: string }): ChatMsg => over;

  const transcript: ChatMsg[] = [
    turn({ id: "m-1", role: "user", content: "earlier question" }),
    turn({ id: "m-2", role: "assistant", content: "earlier answer" }),
    turn({ id: "m-3", role: "user", content: "the question" }),
    turn({ id: "m-4", role: "assistant", content: "partial…", interrupted: true, retryText: "the question" }),
  ];

  it("drops the interrupted bubble and its own user bubble", () => {
    const next = removeInterruptedTurn(transcript, "m-4", "the question");
    expect(next.map(m => m.id)).toEqual(["m-1", "m-2"]);
  });

  it("keeps an earlier identical user message intact (only the adjacent pair goes)", () => {
    const withDuplicate: ChatMsg[] = [
      turn({ id: "m-0", role: "user", content: "the question" }),
      turn({ id: "m-0b", role: "assistant", content: "first answer" }),
      ...transcript.slice(2),
    ];
    const next = removeInterruptedTurn(withDuplicate, "m-4", "the question");
    expect(next.map(m => m.id)).toEqual(["m-0", "m-0b"]);
  });

  it("leaves the user bubble alone when it isn't directly adjacent", () => {
    const gap: ChatMsg[] = [
      turn({ id: "m-3", role: "user", content: "the question" }),
      turn({ id: "m-x", role: "assistant", content: "unrelated" }),
      turn({ id: "m-4", role: "assistant", content: "", interrupted: true, retryText: "the question" }),
    ];
    const next = removeInterruptedTurn(gap, "m-4", "the question");
    expect(next.map(m => m.id)).toEqual(["m-3", "m-x"]);
  });

  it("is a no-op for an unknown id", () => {
    expect(removeInterruptedTurn(transcript, "nope", "the question")).toEqual(transcript);
  });
});
