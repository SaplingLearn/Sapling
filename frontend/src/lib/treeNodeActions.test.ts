import { describe, it, expect } from "vitest";
import type { GraphNode } from "@/lib/data";
import {
  treeCardsHref,
  treeGuideHref,
  treeNodeActions,
  treeNodeCourseId,
  treeQuizHref,
  treeReturnTo,
  treeTeachHref,
} from "./treeNodeActions";

const concept = {
  id: "node-recursion",
  name: "Recursion",
  course_id: "course-cs101",
  is_subject_root: false,
} as GraphNode;

const root = {
  id: "subject_root__course-cs101",
  name: "CS101 - Intro to CS",
  course_id: "course-cs101",
  is_subject_root: true,
} as GraphNode;

const rootNoCourse = {
  id: "subject_root__peeled-course",
  name: "Orphan root",
  course_id: "",
  is_subject_root: true,
} as GraphNode;

describe("treeReturnTo", () => {
  it("returns to the open concept panel", () => {
    expect(treeReturnTo(concept)).toBe("/tree?node=node-recursion");
  });
  it("returns to the bare tree for a subject root", () => {
    expect(treeReturnTo(root)).toBe("/tree");
  });
});

describe("treeNodeCourseId", () => {
  it("prefers course_id", () => {
    expect(treeNodeCourseId(concept)).toBe("course-cs101");
  });
  it("peels a subject-root id when course_id is missing", () => {
    expect(treeNodeCourseId(rootNoCourse)).toBe("peeled-course");
  });
});

describe("treeTeachHref", () => {
  it("seeds topic + concept for a concept node", () => {
    expect(treeTeachHref(concept)).toBe(
      `/learn?topic=Recursion&concept=${concept.id}&mode=socratic&course=course-cs101`,
    );
  });
  it("scopes a root to the course with no topic", () => {
    expect(treeTeachHref(root)).toBe("/learn?mode=socratic&course=course-cs101");
  });
});

describe("treeQuizHref", () => {
  it("links a concept by id, from=tree, returning to its panel", () => {
    expect(treeQuizHref(concept)).toBe(
      `/quiz?concept=${concept.id}&from=tree&return=${encodeURIComponent(`/tree?node=${concept.id}`)}`,
    );
  });
  it("links a subject root as its course", () => {
    expect(treeQuizHref(root)).toBe(
      `/quiz?course=course-cs101&from=tree&return=${encodeURIComponent("/tree")}`,
    );
  });
});

describe("treeCardsHref", () => {
  it("starts Flashcards on the concept's deck", () => {
    expect(treeCardsHref(concept)).toBe(
      "/flashcards?course=course-cs101&concepts=Recursion&start=1",
    );
  });
  it("opens the course Flashcards home for a subject root", () => {
    expect(treeCardsHref(root)).toBe("/flashcards?course=course-cs101");
  });
});

describe("treeGuideHref", () => {
  it("scopes a concept by id", () => {
    expect(treeGuideHref(concept)).toBe(`/study/guide?concept=${concept.id}`);
  });
  it("scopes a subject root to its course", () => {
    expect(treeGuideHref(root)).toBe("/study/guide?course=course-cs101");
  });
});

describe("treeNodeActions", () => {
  it("offers Learn this + Quick quiz when the loop is off", () => {
    expect(treeNodeActions(concept, { loopOn: false, quizShown: true, studyShown: true }).map(a => a.key))
      .toEqual(["teach", "quiz"]);
    expect(treeNodeActions(concept, { loopOn: false, quizShown: true, studyShown: true }).map(a => a.label))
      .toEqual(["Learn this", "Quick quiz"]);
  });

  it("adds Cards + Guide when learning_loop is on and Study is shown", () => {
    const actions = treeNodeActions(concept, { loopOn: true, quizShown: true, studyShown: true });
    expect(actions.map(a => a.key)).toEqual(["teach", "quiz", "cards", "guide"]);
    expect(actions.map(a => a.label)).toEqual(["Learn", "Quiz", "Cards", "Guide"]);
    expect(actions.find(a => a.key === "cards")!.href).toBe(treeCardsHref(concept));
    expect(actions.find(a => a.key === "guide")!.href).toBe(treeGuideHref(concept));
  });

  it("hides Quiz under hide_quiz", () => {
    expect(treeNodeActions(concept, { loopOn: true, quizShown: false, studyShown: true }).map(a => a.key))
      .toEqual(["teach", "cards", "guide"]);
  });

  it("hides Cards and Guide when Study is hidden", () => {
    expect(treeNodeActions(concept, { loopOn: true, quizShown: true, studyShown: false }).map(a => a.key))
      .toEqual(["teach", "quiz"]);
  });
});
