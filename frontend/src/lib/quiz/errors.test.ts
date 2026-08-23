import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import {
  QUIZ_ERROR_COPY,
  QUIZ_ERROR_CODES,
  describeQuizError,
  type QuizErrorCode,
} from "./errors";

function apiError(
  status: number,
  extra: { code?: string; message?: string; requestId?: string; retryAfterSec?: number } = {},
): ApiError {
  const body = {
    error: {
      code: extra.code,
      message: extra.message ?? "server sentence",
      request_id: extra.requestId ?? null,
    },
    detail: extra.message ?? "server sentence",
    request_id: extra.requestId ?? null,
  };
  return new ApiError(JSON.stringify(body), status, {
    code: extra.code,
    requestId: extra.requestId,
    retryAfterSec: extra.retryAfterSec,
    body,
  });
}

describe("QUIZ_ERROR_COPY", () => {
  it("covers every code with a non-empty sentence", () => {
    for (const code of QUIZ_ERROR_CODES) {
      expect(QUIZ_ERROR_COPY[code], code).toBeTruthy();
      expect(QUIZ_ERROR_COPY[code].trim().length, code).toBeGreaterThan(10);
    }
  });

  it("pins the contract's final strings", () => {
    expect(QUIZ_ERROR_COPY.QUIZ_RATE_LIMITED).toBe(
      "You're quizzing fast — give it {n} seconds and try again.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_DAILY_LIMIT_REACHED).toBe(
      "You've used today's quiz allowance. It resets tomorrow.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_GENERATION_TIMEOUT).toBe(
      "Writing this quiz took too long. Try again — it usually works the second time.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_GENERATION_FAILED).toBe(
      "We couldn't put a quiz together for this concept right now. Try again in a moment.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_CONCEPT_NOT_FOUND).toBe(
      "That concept isn't on your tree any more. Pick another one.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_ATTEMPT_NOT_FOUND).toBe(
      "We couldn't find that quiz. Start a new one.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_ATTEMPT_ALREADY_COMPLETED).toBe(
      "This quiz was already scored. Your results are on your tree.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_ATTEMPT_ABANDONED).toBe(
      "That quiz expired after a day. Start a fresh one.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_ATTEMPT_NOT_RESUMABLE).toBe(
      "This quiz can't be resumed. Start a new one.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_QUESTION_INVALID).toBe(
      "That answer didn't line up with the question. Reload and try again.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_DIFFICULTY_INVALID).toBe(
      "Something about this request wasn't valid. Reload and try again.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_VALIDATION_ERROR).toBe(
      QUIZ_ERROR_COPY.QUIZ_DIFFICULTY_INVALID,
    );
    expect(QUIZ_ERROR_COPY.QUIZ_NOT_AUTHORIZED).toBe(
      "Please sign in again to keep quizzing.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_INTERNAL_ERROR).toBe(
      "Something went wrong on our side. Try again in a moment.",
    );
    expect(QUIZ_ERROR_COPY.QUIZ_HTTP_ERROR).toBe(QUIZ_ERROR_COPY.QUIZ_INTERNAL_ERROR);
    expect(QUIZ_ERROR_COPY.UNKNOWN).toBe(QUIZ_ERROR_COPY.QUIZ_INTERNAL_ERROR);
    expect(QUIZ_ERROR_COPY.NETWORK).toBe(
      "You look offline. Check your connection and try again.",
    );
  });
});

describe("describeQuizError — coded envelope", () => {
  const cases: [QuizErrorCode, number][] = [
    ["QUIZ_DIFFICULTY_INVALID", 400],
    ["QUIZ_QUESTION_INVALID", 400],
    ["QUIZ_VALIDATION_ERROR", 422],
    ["QUIZ_NOT_AUTHORIZED", 401],
    ["QUIZ_CONCEPT_NOT_FOUND", 404],
    ["QUIZ_ATTEMPT_NOT_FOUND", 404],
    ["QUIZ_ATTEMPT_ALREADY_COMPLETED", 409],
    ["QUIZ_ATTEMPT_ABANDONED", 409],
    ["QUIZ_ATTEMPT_NOT_RESUMABLE", 409],
    ["QUIZ_DAILY_LIMIT_REACHED", 429],
    ["QUIZ_GENERATION_TIMEOUT", 502],
    ["QUIZ_GENERATION_FAILED", 502],
    ["QUIZ_INTERNAL_ERROR", 500],
    ["QUIZ_HTTP_ERROR", 405],
  ];

  for (const [code, status] of cases) {
    it(`maps ${code} to its copy`, () => {
      const out = describeQuizError(apiError(status, { code }));
      expect(out.code).toBe(code);
      expect(out.message).toBe(QUIZ_ERROR_COPY[code]);
    });
  }

  it("interpolates Retry-After into the rate-limit copy", () => {
    const out = describeQuizError(apiError(429, { code: "QUIZ_RATE_LIMITED", retryAfterSec: 42 }));
    expect(out.code).toBe("QUIZ_RATE_LIMITED");
    expect(out.message).toBe("You're quizzing fast — give it 42 seconds and try again.");
    expect(out.retryAfterSec).toBe(42);
    expect(out.retryable).toBe(true);
  });

  it("falls back to 60 seconds when Retry-After is missing", () => {
    const out = describeQuizError(apiError(429, { code: "QUIZ_RATE_LIMITED" }));
    expect(out.message).toBe("You're quizzing fast — give it 60 seconds and try again.");
    expect(out.retryAfterSec).toBeUndefined();
  });

  it("uses the server sentence verbatim for QUIZ_COUNT_OUT_OF_RANGE (it carries the bounds)", () => {
    const out = describeQuizError(
      apiError(422, {
        code: "QUIZ_COUNT_OUT_OF_RANGE",
        message: "Quizzes can have between 1 and 10 questions.",
      }),
    );
    expect(out.code).toBe("QUIZ_COUNT_OUT_OF_RANGE");
    expect(out.message).toBe("Quizzes can have between 1 and 10 questions.");
  });

  it("falls back to generic copy when QUIZ_COUNT_OUT_OF_RANGE has no server sentence", () => {
    const err = new ApiError("", 422, { code: "QUIZ_COUNT_OUT_OF_RANGE" });
    expect(describeQuizError(err).message).toBe(QUIZ_ERROR_COPY.QUIZ_COUNT_OUT_OF_RANGE);
  });

  it("carries the request id through for support", () => {
    const out = describeQuizError(
      apiError(500, { code: "QUIZ_INTERNAL_ERROR", requestId: "req-9" }),
    );
    expect(out.requestId).toBe("req-9");
  });

  it("marks the retryable codes", () => {
    const retryable: QuizErrorCode[] = [
      "QUIZ_RATE_LIMITED",
      "QUIZ_GENERATION_TIMEOUT",
      "QUIZ_GENERATION_FAILED",
      "QUIZ_INTERNAL_ERROR",
      "QUIZ_HTTP_ERROR",
      "UNKNOWN",
      "NETWORK",
    ];
    for (const code of QUIZ_ERROR_CODES) {
      const out = describeQuizError(apiError(500, { code }));
      expect(out.retryable, code).toBe(retryable.includes(code));
    }
  });
});

describe("describeQuizError — uncoded responses", () => {
  it("reads 401/403 as not-authorized", () => {
    expect(describeQuizError(new ApiError("nope", 401)).code).toBe("QUIZ_NOT_AUTHORIZED");
    expect(describeQuizError(new ApiError("nope", 403)).code).toBe("QUIZ_NOT_AUTHORIZED");
  });

  it("reads 429 as rate-limited", () => {
    expect(describeQuizError(new ApiError("slow down", 429)).code).toBe("QUIZ_RATE_LIMITED");
  });

  it("reads 5xx as an internal error", () => {
    expect(describeQuizError(new ApiError("boom", 500)).code).toBe("QUIZ_INTERNAL_ERROR");
    expect(describeQuizError(new ApiError("boom", 503)).code).toBe("QUIZ_INTERNAL_ERROR");
  });

  it("does not read an uncoded 404 as a domain state (QUIZ_HTTP_ERROR, per R1 §D)", () => {
    expect(describeQuizError(new ApiError("missing", 404)).code).toBe("QUIZ_HTTP_ERROR");
  });

  it("ignores a code the client does not know", () => {
    const out = describeQuizError(apiError(500, { code: "QUIZ_BRAND_NEW_CODE" }));
    expect(out.code).toBe("QUIZ_INTERNAL_ERROR");
  });
});

describe("describeQuizError — transport failures", () => {
  it("maps a TypeError to NETWORK", () => {
    const out = describeQuizError(new TypeError("Failed to fetch"));
    expect(out.code).toBe("NETWORK");
    expect(out.message).toBe(QUIZ_ERROR_COPY.NETWORK);
    expect(out.retryable).toBe(true);
  });

  it("maps a fetch-worded plain Error to NETWORK", () => {
    expect(describeQuizError(new Error("NetworkError when attempting to fetch resource")).code)
      .toBe("NETWORK");
    expect(describeQuizError(new Error("network request failed")).code).toBe("NETWORK");
  });

  it("maps anything else to UNKNOWN", () => {
    expect(describeQuizError(new Error("something odd")).code).toBe("UNKNOWN");
    expect(describeQuizError(undefined).code).toBe("UNKNOWN");
    expect(describeQuizError("string throw").code).toBe("UNKNOWN");
  });
});
