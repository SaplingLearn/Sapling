import { expect, it } from "vitest";
import { initialSession, reduce, canSubmitAnswer, firstUnansweredIndex } from "./machine";
import { WRITTEN_TYPES, isWrittenType, type QuizConfig, type QuizPrefs } from "./types";

it("mirrors backend WRITTEN_TYPES (services/quiz_grading.py) exactly", () => {
  expect([...WRITTEN_TYPES].sort()).toEqual(["numeric", "short_answer", "symbolic"]);
  for (const type of ["short_answer", "numeric", "symbolic"]) expect(isWrittenType(type)).toBe(true);
  // Like the backend, anything outside the written set is answered by choice.
  for (const type of ["multiple_choice", undefined, null, "", "essay"]) expect(isWrittenType(type)).toBe(false);
});

it("an unrecognised type is answered by choice everywhere, as the backend treats it", () => {
  const config: QuizConfig = { num_questions: { min: 1, max: 10, options: [3] }, difficulties: ["easy"], question_types: ["multiple_choice"] };
  const prefs: QuizPrefs = { count: null, difficulty: null, feedback: "at-end" };
  const session = reduce(initialSession({ source: { kind: "nav" } }, config, prefs), { type: "RESUME", stored: null, detail: {
    quiz_id: "q", concept_node_id: "c1", difficulty: "easy", resumable: true, status: "in_progress",
    // A future/unknown type must not silently become a free-text item.
    questions: [{ id: 1, type: "essay" as never, question: "Pick", options: [{ label: "A", text: "a" }, { label: "B", text: "b" }], difficulty: "easy" }],
    responses: [], score: null, total: null, created_at: "2026-10-18T00:00:00Z",
  } });
  const written = reduce(session, { type: "WRITE", text: "free text" });
  expect(written.items[0].answerText).toBeUndefined();
  expect(canSubmitAnswer(written)).toBe(false);
  expect(firstUnansweredIndex(written.items)).toBe(0);
});
