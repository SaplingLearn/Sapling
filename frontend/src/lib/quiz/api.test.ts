import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  answerQuestion,
  describeConcept,
  fetchQuizConfig,
  generateQuiz,
  getAttempt,
  listAttempts,
  submitQuiz,
} from "./api";

const realFetch = globalThis.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fetchMock(): ReturnType<typeof vi.fn> {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

function lastCall(): [string, RequestInit] {
  const calls = fetchMock().mock.calls;
  return calls[calls.length - 1] as [string, RequestInit];
}

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
  fetchMock().mockResolvedValue(jsonResponse({}));
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("fetchQuizConfig", () => {
  it("GETs the unauthenticated config route", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({
        num_questions: { min: 1, max: 10, options: [3, 5, 10] },
        difficulties: ["easy", "medium", "hard", "adaptive"],
        question_types: ["multiple_choice"],
      }),
    );
    const config = await fetchQuizConfig();
    expect(lastCall()[0]).toBe("/api/quiz/config");
    expect(config.num_questions.options).toEqual([3, 5, 10]);
  });
});

describe("generateQuiz", () => {
  it("always sends include_answer_key: false (R-2 — the server grades)", async () => {
    await generateQuiz({
      userId: "u1",
      conceptNodeId: "c1",
      numQuestions: 5,
      difficulty: "medium",
    });
    const [url, init] = lastCall();
    expect(url).toBe("/api/quiz/generate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      user_id: "u1",
      concept_node_id: "c1",
      num_questions: 5,
      difficulty: "medium",
      include_answer_key: false,
    });
  });
});

describe("answerQuestion", () => {
  it("posts the 0-based index pair plus the 1-based wire question id", async () => {
    await answerQuestion("a-1", { questionIndex: 2, selectedIndex: 0, questionId: 3 });
    const [url, init] = lastCall();
    expect(url).toBe("/api/quiz/attempts/a-1/answer");
    expect(JSON.parse(init.body as string)).toEqual({
      question_index: 2,
      selected_index: 0,
      question_id: 3,
    });
  });

  it("omits time_ms and confidence — nothing reads them back (G10)", async () => {
    await answerQuestion("a-1", { questionIndex: 0, selectedIndex: 1, questionId: 1 });
    const body = JSON.parse(lastCall()[1].body as string) as Record<string, unknown>;
    expect("time_ms" in body).toBe(false);
    expect("confidence" in body).toBe(false);
  });

  it("url-encodes the attempt id", async () => {
    await answerQuestion("a/1", { questionIndex: 0, selectedIndex: 0, questionId: 1 });
    expect(lastCall()[0]).toBe("/api/quiz/attempts/a%2F1/answer");
  });
});

describe("submitQuiz", () => {
  it("posts quiz_id plus the local answers as the belt-and-braces payload", async () => {
    await submitQuiz("a-1", [{ question_id: 1, selected_label: "B" }]);
    const [url, init] = lastCall();
    expect(url).toBe("/api/quiz/submit");
    expect(JSON.parse(init.body as string)).toEqual({
      quiz_id: "a-1",
      answers: [{ question_id: 1, selected_label: "B" }],
    });
  });

  it("accepts an empty answers list (recorded rows win at reconciliation)", async () => {
    await submitQuiz("a-1", []);
    expect(JSON.parse(lastCall()[1].body as string).answers).toEqual([]);
  });
});

describe("listAttempts", () => {
  it("scopes by user id and omits absent pagination params", async () => {
    await listAttempts("u1");
    expect(lastCall()[0]).toBe("/api/quiz/attempts?user_id=u1");
  });

  it("passes limit and offset through", async () => {
    await listAttempts("u 1", { limit: 20, offset: 40 });
    expect(lastCall()[0]).toBe("/api/quiz/attempts?user_id=u+1&limit=20&offset=40");
  });
});

describe("getAttempt", () => {
  it("GETs the resume route", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ quiz_id: "a-1", resumable: true }));
    const detail = await getAttempt("a-1");
    expect(lastCall()[0]).toBe("/api/quiz/attempts/a-1");
    expect(detail.quiz_id).toBe("a-1");
  });
});

describe("describeConcept", () => {
  it("unwraps the description and sends the course LABEL, not an id", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ description: "A way to solve X." }));
    const out = await describeConcept("u1", "Recursion", "CS 330 — Algorithms");
    const [url, init] = lastCall();
    expect(url).toBe("/api/graph/u1/concept-description");
    expect(JSON.parse(init.body as string)).toEqual({
      concept: "Recursion",
      course_label: "CS 330 — Algorithms",
    });
    expect(out).toBe("A way to solve X.");
  });

  it("sends a null course label when none is known", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ description: "d" }));
    await describeConcept("u1", "Recursion");
    expect(JSON.parse(lastCall()[1].body as string).course_label).toBeNull();
  });
});

describe("every call is same-origin and cookie-bearing", () => {
  it("sends credentials: include", async () => {
    await fetchQuizConfig();
    const [url, init] = lastCall();
    expect(url.startsWith("/api/")).toBe(true);
    expect(init.credentials).toBe("include");
  });
});
