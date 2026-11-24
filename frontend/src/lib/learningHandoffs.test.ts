import { describe, expect, it } from "vitest";
import {
  HANDOFF_COPY,
  closeHandoffCtas,
  handoffLearnHref,
  handoffPracticeDueHref,
  handoffQuizConceptHref,
  handoffStudyHref,
  handoffTreeHref,
  practiceUnavailableHandoffCtas,
  retentionEmptyHandoffCtas,
} from "./learningHandoffs";

const ALL_ON = { study: true, tutor: true, quiz: true, tree: true };

describe("HANDOFF_COPY", () => {
  it("keeps the W8.5 / W3.4 labels stable, and Practice distinct from Teach", () => {
    expect(HANDOFF_COPY.dueOnStudy).toBe("Due on Study");
    expect(HANDOFF_COPY.dueOnStudyCounted(2)).toBe("Due on Study (2)");
    expect(HANDOFF_COPY.continueInTutor).toBe("Continue in Tutor");
    expect(HANDOFF_COPY.continueLearning("Loops")).toBe("Continue learning: Loops");
    expect(HANDOFF_COPY.quizThisConcept).toBe("Quiz this concept");
    expect(HANDOFF_COPY.practiceWhatsDue).toBe("Practice what's due");
    expect(HANDOFF_COPY.seeOnMap).toBe("See on your map");
    expect(HANDOFF_COPY.practiceWhatsDue).not.toMatch(/learn|teach|tutor/i);
  });
});

describe("href builders", () => {
  it("courses Study and Learn with mode=socratic", () => {
    expect(handoffStudyHref("c1")).toBe("/study?course=c1");
    expect(handoffStudyHref(null)).toBe("/study");
    expect(handoffLearnHref({ conceptId: "n1", conceptName: "Recursion", courseId: "c1" })).toBe(
      "/learn?topic=Recursion&concept=n1&mode=socratic&course=c1",
    );
  });

  it("Quiz concept deep-links with start=1 and a Study return", () => {
    expect(handoffQuizConceptHref("n1", { courseId: "c1" })).toBe(
      "/quiz?concept=n1&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1",
    );
  });

  it("Practice what's due feeds due[] as a scope=due queue, else course+start (W3.3c)", () => {
    expect(handoffPracticeDueHref("c1", ["arr", "loop"])).toBe(
      "/quiz?scope=due&queue=arr%2Cloop&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1",
    );
    expect(handoffPracticeDueHref("c1", [])).toBe(
      "/quiz?course=c1&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1",
    );
  });

  it("Tree prefers a node, else a course", () => {
    expect(handoffTreeHref({ nodeId: "n1" })).toBe("/tree?node=n1");
    expect(handoffTreeHref({ courseId: "c1" })).toBe("/tree?course=c1");
    expect(handoffTreeHref({})).toBe("/tree");
  });
});

describe("closeHandoffCtas", () => {
  it("offers Study, Practice (course+start without due ids), Quiz concept, and Tree", () => {
    const links = closeHandoffCtas({
      courseId: "c1",
      quizConceptId: "n-down",
      visibility: ALL_ON,
    });
    expect(links.map((l) => [l.testId, l.label, l.href])).toEqual([
      ["loop-close-study-link", "Due on Study", "/study?course=c1"],
      [
        "loop-close-practice-link",
        "Practice what's due",
        "/quiz?course=c1&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1",
      ],
      [
        "loop-close-quiz-link",
        "Quiz this concept",
        "/quiz?concept=n-down&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1",
      ],
      ["loop-close-tree-link", "See on your map", "/tree?course=c1"],
    ]);
  });

  it("Practice uses the due[] queue when provided (W3.3c)", () => {
    const practice = closeHandoffCtas({
      courseId: "c1",
      dueConceptIds: ["arr", "loop"],
      visibility: ALL_ON,
    }).find((l) => l.testId === "loop-close-practice-link");
    expect(practice?.href).toBe(
      "/quiz?scope=due&queue=arr%2Cloop&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1",
    );
  });

  it("omits Practice under hide_quiz or hide_study; omits Quiz concept without an id", () => {
    expect(
      closeHandoffCtas({ courseId: "c1", visibility: ALL_ON }).map((l) => l.testId),
    ).toEqual(["loop-close-study-link", "loop-close-practice-link", "loop-close-tree-link"]);
    expect(
      closeHandoffCtas({
        courseId: "c1",
        quizConceptId: "n1",
        dueConceptIds: ["arr"],
        visibility: { study: true, tutor: true, quiz: false, tree: true },
      }).map((l) => l.testId),
    ).toEqual(["loop-close-study-link", "loop-close-tree-link"]);
    expect(
      closeHandoffCtas({
        courseId: "c1",
        quizConceptId: "n1",
        visibility: { study: false, tutor: true, quiz: true, tree: false },
      }).map((l) => l.testId),
    ).toEqual(["loop-close-quiz-link"]);
    expect(
      closeHandoffCtas({
        courseId: "c1",
        quizConceptId: "n1",
        visibility: { study: false, tutor: true, quiz: false, tree: false },
      }),
    ).toEqual([]);
  });
});

describe("retentionEmptyHandoffCtas", () => {
  it("offers Due on Study and Continue in Tutor when visible", () => {
    const links = retentionEmptyHandoffCtas({
      courseId: "c1",
      visibility: { study: true, tutor: true },
    });
    expect(links.map((l) => [l.testId, l.href])).toEqual([
      ["retention-study-link", "/study?course=c1"],
      ["retention-tutor-link", "/learn?mode=socratic&course=c1"],
    ]);
  });
});

describe("practiceUnavailableHandoffCtas", () => {
  it("Quiz only when a concept id is present", () => {
    expect(
      practiceUnavailableHandoffCtas({
        courseId: "c1",
        conceptIds: [],
        visibility: { study: true, quiz: true },
      }).map((l) => l.key),
    ).toEqual(["study"]);
    expect(
      practiceUnavailableHandoffCtas({
        courseId: "c1",
        conceptIds: ["n9"],
        visibility: { study: true, quiz: true },
      }).map((l) => l.testId),
    ).toEqual(["loop-practice-study-link", "loop-practice-quiz-link"]);
  });
});
