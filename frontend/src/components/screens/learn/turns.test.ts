/**
 * #866 K49: which refusals of a legacy-tree tutor call can only have come from
 * the learning loop. With the loop off the legacy tutor answers none of them,
 * so a loop-off student's screen never rechecks the loop.
 */
import { describe, expect, it } from "vitest";

import { ApiError, ChatStreamError } from "@/lib/api";
import { answeredByTheLoop, SESSION_ENDED_CODE } from "./turns";

const apiError = (status: number, body: Record<string, unknown>, code?: string) =>
  new ApiError(JSON.stringify(body), status, { body, code });

describe("answeredByTheLoop", () => {
  it.each([
    ["a budget pause (only the loop reads the AI budget)", apiError(429, { detail: "ai budget reached", reset_at: null }), true],
    ["the loop's phase 409", apiError(409, { detail: "finish the probe first" }), true],
    ["a loop 409 that carries some other code", apiError(409, { detail: "x", error: { code: "LOOP_PHASE" } }, "LOOP_PHASE"), true],
    ["the legacy tutor's SESSION_ENDED 409", apiError(409, { detail: "ended", error: { code: SESSION_ENDED_CODE } }, SESSION_ENDED_CODE), false],
    ["an abuse-limit 429", apiError(429, { detail: "Too many requests. Try again in 30 seconds." }), false],
    ["a 500", apiError(500, { detail: "boom" }), false],
    ["a stream that broke", new ChatStreamError("The tutor was interrupted.", "r1", true), false],
    ["a network failure", new TypeError("Failed to fetch"), false],
  ] as [string, unknown, boolean][])("%s → %s", (_why, err, expected) => {
    expect(answeredByTheLoop(err)).toBe(expected);
  });
});
