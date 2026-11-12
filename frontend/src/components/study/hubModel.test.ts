import { describe, it, expect } from "vitest";
import type { Assignment, StudyGuideCacheEntry } from "@/lib/api";
import type { AttemptSummary } from "@/lib/quiz/types";
import {
  assessmentsForCourse,
  cardCounts,
  cardsFor,
  cardsOfCourse,
  chipsThatFit,
  conceptMarks,
  courseLabel,
  draftsOf,
  dueThisWeek,
  examTabs,
  focusCardsLabel,
  newDraft,
  planDates,
  prerequisitesOf,
  planIsEmpty,
  quickReviewEstimate,
  saveOutcome,
  recentActivity,
  roadmapColumns,
  tileActionsHint,
  tileCardsLabel,
  upcomingOf,
  RECENT_MAX,
  type Draft,
  type RoadmapMarks,
} from "./hubModel";
import type { Assessment, Concept, Status } from "./studyModel";

const TODAY = new Date(2026, 10, 8, 12);
const iso = (d: number) => `2026-11-${String(d).padStart(2, "0")}`;

const concept = (id: string, st: Status = "progress", extra: Partial<Concept> = {}): Concept => ({
  id, name: id.toUpperCase(), st, m: st === "mastered" ? 95 : 50, lastStudied: null,
  pre: [], post: [], step: 0, group: "Foundations", gap: "", weekDelta: 0, ...extra,
});
const assignment = (id: string, title: string, day: number | null, type: string, course = "c1"): Assignment => ({
  id, user_id: "u1", title, due_date: day == null ? null : `${iso(day)}T00:00:00Z`, assignment_type: type, course_id: course,
});
const assessment = (id: string, type: Assessment["type"], day: number, title = id): Assessment =>
  ({ id, type, rawType: type.toLowerCase(), title, iso: iso(day) });

describe("courseLabel", () => {
  it("is the code, else the name, else nothing", () => {
    expect(courseLabel({ course_code: "CS101", course_name: "Intro" })).toBe("CS101");
    expect(courseLabel({ course_code: "", course_name: "Intro" })).toBe("Intro");
    expect(courseLabel(null)).toBe("");
  });
});

describe("a course's dated work", () => {
  const rows = [
    assignment("late", "Final", 20, "final"),
    assignment("hw", "Lab 5", 10, "homework"),
    assignment("undated", "Someday", null, "exam"),
    assignment("elsewhere", "Other Final", 12, "exam", "c2"),
    assignment("q", "Pop quiz", 7, "other"),
  ];

  it("keeps this course's dated rows, soonest first, classified", () => {
    const list = assessmentsForCourse(rows, "c1");
    expect(list.map(e => [e.id, e.type, e.iso])).toEqual([
      ["q", "Quiz", iso(7)], // "other", so the title decides
      ["hw", "Homework", iso(10)],
      ["late", "Exam", iso(20)],
    ]);
    expect(list[2].rawType).toBe("final"); // the stored type rides along
  });

  it("upcoming counts today, and the bell's badge is what is due within the week", () => {
    const list = [assessment("past", "Exam", 7), assessment("today", "Quiz", 8), assessment("week", "Homework", 15), assessment("far", "Exam", 16)];
    const upcoming = upcomingOf(list, TODAY);
    expect(upcoming.map(e => e.id)).toEqual(["today", "week", "far"]);
    expect(dueThisWeek(upcoming, TODAY)).toBe(2);
  });
});

describe("examTabs", () => {
  const list = [assessment("old", "Exam", 1), assessment("hw", "Homework", 9), assessment("next", "Quiz", 12), assessment("later", "Exam", 20)];

  it("gives every exam and quiz a tab, past or not, and never homework", () => {
    expect(examTabs(list, TODAY, null).exams.map(e => e.id)).toEqual(["old", "next", "later"]);
  });

  it("defaults to the next one ahead, else the most recent", () => {
    expect(examTabs(list, TODAY, null).exam?.id).toBe("next");
    expect(examTabs(list.slice(0, 2), TODAY, null).exam?.id).toBe("old");
    expect(examTabs([], TODAY, null).exam).toBeNull();
  });

  it("follows the selection while it is still a tab", () => {
    expect(examTabs(list, TODAY, "later").exam?.id).toBe("later");
    expect(examTabs(list, TODAY, "gone").exam?.id).toBe("next");
    expect(examTabs(list, TODAY, "hw").exam?.id).toBe("next"); // homework is not a tab
  });
});

describe("flashcards per concept", () => {
  it("counts by name, ignoring case and outer spaces", () => {
    const counts = cardCounts([
      { id: "1", topic: "Loops" }, { id: "2", topic: " loops " }, { id: "3", topic: "Arrays" },
      { id: "4", topic: null }, { id: "5" },
    ]);
    expect(cardsFor(counts, "LOOPS")).toBe(2);
    expect(cardsFor(counts, "Arrays")).toBe(1);
    expect(cardsFor(counts, "Recursion")).toBe(0);
    expect(cardsFor(counts, "")).toBe(0);
  });

  it("a card made for another course does not count here; one with no course goes by its topic", () => {
    const cards = [
      { id: "here", topic: "Loops", course_id: "c1" },
      { id: "there", topic: "Loops", course_id: "c2" }, // a same-named concept in another course
      { id: "old", topic: "Loops", course_id: null },
      { id: "older", topic: "Loops" },
    ];
    expect(cardsOfCourse(cards, "c1").map(c => c.id)).toEqual(["here", "old", "older"]);
    expect(cardsFor(cardCounts(cardsOfCourse(cards, "c1")), "Loops")).toBe(3);
    expect(cardsFor(cardCounts(cardsOfCourse(cards, "c3")), "Loops")).toBe(2);
  });

  it("words the action by how many there are", () => {
    expect(focusCardsLabel(0)).toBe("Make flashcards");
    expect(focusCardsLabel(1)).toBe("Review 1 flashcard");
    expect(focusCardsLabel(3)).toBe("Review 3 flashcards");
    expect(tileCardsLabel(0)).toBe("Make Flashcards");
    expect(tileCardsLabel(2)).toBe("2 Flashcards");
  });

  it("the tile's tooltip names only what its menu offers", () => {
    expect(tileActionsHint(true)).toBe("Quiz or flashcards for this concept");
    expect(tileActionsHint(false)).toBe("Flashcards for this concept");
  });
});

describe("chipsThatFit", () => {
  it("is zero with nothing to show, and never less than one otherwise", () => {
    expect(chipsThatFit([])).toBe(0);
    expect(chipsThatFit(["A prerequisite whose name alone is far wider than the line"])).toBe(1);
    expect(chipsThatFit(["A prerequisite whose name alone is far wider than the line", "B"])).toBe(1);
  });

  it("fits short names, and stops while there is still room for '+N more'", () => {
    expect(chipsThatFit(["Loops", "Arrays"])).toBe(2);
    // Each is 28 + 10 * 6.4 + 5 = 97 wide; two fit the 230 line only when
    // nothing has to follow them.
    expect(chipsThatFit(["Recursion!", "Iteration!"])).toBe(2);
    expect(chipsThatFit(["Recursion!", "Iteration!", "Induction!"])).toBe(1);
  });
});

describe("conceptMarks", () => {
  const a = concept("a"), b = concept("b", "review", { pre: ["a", "ghost"] });
  const byId = new Map([a, b].map(t => [t.id, t]));

  it("Up Next follows the clicked concept, else the head of the queue", () => {
    expect(conceptMarks(byId, b, null, null)).toMatchObject({ sel: null, rec: b, focus: b, hot: null });
    expect(conceptMarks(byId, b, "a", null)).toMatchObject({ sel: a, rec: b, focus: a, hot: a });
  });

  it("the highlight follows the hovered concept, never the focus", () => {
    const marks = conceptMarks(byId, b, "a", "b");
    expect(marks.hot).toBe(b);
    expect(marks.focus).toBe(a);
  });

  it("an id that is not on the course is no one", () => {
    expect(conceptMarks(byId, null, "gone", "gone")).toEqual({ sel: null, rec: null, focus: null, hot: null });
  });

  it("prerequisites resolve in order and drop unknown ids", () => {
    expect(prerequisitesOf(b, byId)).toEqual([a]);
    expect(prerequisitesOf(null, byId)).toEqual([]);
  });
});

describe("roadmapColumns", () => {
  const none: RoadmapMarks = { sel: null, rec: null, hot: null, lvl: null };
  // a -> b -> c, plus d on its own; all in one column unless a group says otherwise.
  const a = concept("a", "mastered", { post: ["b"] });
  const b = concept("b", "progress", { pre: ["a"], post: ["c"], step: 1 });
  const c = concept("c", "review", { pre: ["b"], step: 2 });
  const d = concept("d", "new");
  const topics = [a, b, c, d];
  const tiles = (marks: RoadmapMarks) =>
    Object.fromEntries(roadmapColumns(topics, marks, "c1", {})[0].shown.map(x => [x.t.id, x]));

  it("makes a column per group, keyed on the course, with its mastered count and bars", () => {
    const cols = roadmapColumns([a, concept("z", "new", { group: "Advanced", step: 3 })], none, "c1", {});
    expect(cols.map(col => [col.label, col.key, col.frac])).toEqual([["Foundations", "c1Foundations", "1/1"], ["Advanced", "c1Advanced", "0/1"]]);
    expect(cols[0].bars).toEqual(["var(--state-mastery)"]);
  });

  it("marks the clicked concept and Up Next", () => {
    const t = tiles({ ...none, sel: b, rec: c, hot: b });
    expect(t.b).toMatchObject({ isSel: true, isNext: false });
    expect(t.c).toMatchObject({ isSel: false, isNext: true });
  });

  it("labels what the hot concept needs and what it unlocks, and dims the rest", () => {
    const t = tiles({ ...none, hot: b });
    expect(t.a.rel).toBe("Needed First");
    expect(t.c.rel).toBe("Unlocks");
    expect(t.b.rel).toBe("");
    expect([t.a.dim, t.b.dim, t.c.dim, t.d.dim]).toEqual([false, false, false, true]);
  });

  it("dims nothing for a hot concept with no links", () => {
    const t = tiles({ ...none, hot: d });
    expect(Object.values(t).some(x => x.dim || x.rel)).toBe(false);
  });

  it("the legend filter dims every other status", () => {
    const t = tiles({ ...none, lvl: "review" });
    expect([t.a.dim, t.b.dim, t.c.dim, t.d.dim]).toEqual([true, true, false, true]);
  });

  describe("a long column", () => {
    const mastered = ["m1", "m2", "m3", "m4", "m5"].map(id => concept(id, "mastered"));
    const open = { c1Foundations: true };
    const column = (list: Concept[], marks = none, openCols = {}) => roadmapColumns(list, marks, "c1", openCols)[0];

    it("is left alone at four tiles or fewer", () => {
      const col = column(mastered.slice(0, 4));
      expect(col.shown).toHaveLength(4);
      expect(col.hidden).toEqual([]);
    });

    it("folds mastered tiles away past four, keeping every unmastered one", () => {
      const col = column([...mastered, concept("u1", "review"), concept("u2", "new")]);
      // Both unmastered stay; mastered ones top the column up to four.
      expect(col.shown.map(x => x.t.id)).toEqual(["m1", "m2", "u1", "u2"]);
      expect(col.hidden.map(x => x.t.id)).toEqual(["m3", "m4", "m5"]);
    });

    it("never folds away the selected concept, Up Next, or the selection's links", () => {
      const m5 = concept("m5", "mastered", { pre: ["m4"] });
      const list = [...mastered.slice(0, 4), m5];
      expect(column(list).hidden.map(x => x.t.id)).toEqual(["m5"]);
      const col = column(list, { ...none, sel: m5 });
      expect(col.shown.map(x => x.t.id)).toEqual(["m1", "m2", "m4", "m5"]); // m5 and its prerequisite m4
      expect(col.hidden.map(x => x.t.id)).toEqual(["m3"]);
    });

    it("open shows everything and still says what closing would hide", () => {
      const col = column(mastered, none, open);
      expect(col.open).toBe(true);
      expect(col.shown).toHaveLength(5);
      expect(col.hidden.map(x => x.t.id)).toEqual(["m5"]);
    });
  });
});

describe("quickReviewEstimate", () => {
  it("is two minutes a concept, and always worded as a guess", () => {
    expect(quickReviewEstimate(1)).toBe("~2 min");
    expect(quickReviewEstimate(5)).toBe("~10 min");
  });
});

describe("recentActivity", () => {
  const at = (day: number, hour: number) => new Date(2026, 10, day, hour).toISOString();
  const attempt = (id: string, over: Partial<AttemptSummary> = {}): AttemptSummary => ({
    quiz_id: id, status: "completed", concept_node_id: "rec", concept_name: "Recursion", course_id: "c1",
    score: 6, total: 10, difficulty: "medium", mastery_before: 0.25, mastery_after: 0.3, mastery_delta: 0.05,
    created_at: at(7, 10), completed_at: at(7, 11), ...over,
  });
  const guide = (id: string, over: Partial<StudyGuideCacheEntry> = {}): StudyGuideCacheEntry => ({
    id, course_id: "c1", exam_id: "e1", course_name: "Intro to CS", exam_title: "Exam 2", overview: "", generated_at: at(6, 9), ...over,
  });
  const course = { course_id: "c1", course_code: "CS101", course_name: "Intro to CS" };
  const topics = [concept("rec", "review", { name: "Recursion" }), concept("loop", "progress", { name: "Loops" })];
  const rows = (input: Partial<Parameters<typeof recentActivity>[0]>) =>
    recentActivity({ attempts: [], cards: [], guides: [], topics, course, today: TODAY, ...input });

  it("a finished quiz is a row with its score and the concept's mastery change", () => {
    expect(rows({ attempts: [attempt("a1")] })).toEqual([{
      key: "qa1", at: Date.parse(at(7, 11)), kind: "quiz", title: "Recursion Quiz", meta: "Quiz · Yesterday",
      result: "60%", resultColor: "var(--warn)", chips: [{ id: "rec", name: "Recursion", delta: 5 }],
    }]);
  });

  it("leaves out unfinished or unscored attempts, and other courses' quizzes", () => {
    const out = rows({ attempts: [
      attempt("open", { status: "in_progress" as AttemptSummary["status"] }),
      attempt("unscored", { score: null }),
      attempt("empty", { total: 0 }),
      attempt("elsewhere", { course_id: "c2", concept_node_id: "other" }),
      attempt("by-concept", { course_id: null, mastery_delta: null }), // no course on the row, but one of its concepts
    ] });
    expect(out.map(r => r.key)).toEqual(["qby-concept"]);
    expect(out[0].chips).toEqual([]);
  });

  it("groups flashcard reviews by deck and day, for this course's decks only", () => {
    const out = rows({ cards: [
      { id: "1", topic: "Loops", last_reviewed_at: at(8, 9) },
      { id: "2", topic: "loops ", last_reviewed_at: at(8, 10) }, // a deck of its own spelling, same course
      { id: "3", topic: "Loops", last_reviewed_at: at(8, 11) },
      { id: "4", topic: "Loops", last_reviewed_at: at(5, 9) },
      { id: "5", topic: "CS101", last_reviewed_at: at(4, 9) }, // a deck named for the course
      { id: "6", topic: "Chemistry", last_reviewed_at: at(8, 9) },
      { id: "7", topic: "Loops", last_reviewed_at: null },
    ] });
    expect(out.map(r => [r.title, r.result, r.meta])).toEqual([
      ["Loops", "2 cards", "Flashcards · Today"],
      ["loops ", "1 card", "Flashcards · Today"],
      ["Loops", "1 card", "Flashcards · Nov 5"],
      ["CS101", "1 card", "Flashcards · Nov 4"],
    ]);
    expect(out[0].at).toBe(Date.parse(at(8, 11))); // the deck's latest review
  });

  it("a review of a card made for another course is not this course's activity", () => {
    const out = rows({ cards: [
      { id: "1", topic: "Loops", course_id: "c2", last_reviewed_at: at(8, 9) },
      { id: "2", topic: "Loops", course_id: "c1", last_reviewed_at: at(8, 10) },
      { id: "3", topic: "Loops", last_reviewed_at: at(8, 11) },
    ] });
    expect(out.map(r => [r.title, r.result])).toEqual([["Loops", "2 cards"]]);
  });

  it("an unreadable review date drops the row instead of breaking the list", () => {
    const out = rows({ cards: [
      { id: "1", topic: "Loops", last_reviewed_at: "not a date" },
      { id: "2", topic: "Recursion", last_reviewed_at: at(8, 9) },
    ] });
    expect(out.map(r => r.title)).toEqual(["Recursion"]);
  });

  it("lists this course's study guides", () => {
    const out = rows({ guides: [guide("g1"), guide("g2", { course_id: "c2" }), guide("g3", { exam_title: "" })] });
    expect(out.map(r => [r.key, r.title, r.meta, r.result])).toEqual([
      ["gg1", "Exam 2 Study Guide", "Study Guide · Nov 6", ""],
      ["gg3", "Exam Study Guide", "Study Guide · Nov 6", ""],
    ]);
  });

  it("is newest first across kinds, capped at RECENT_MAX", () => {
    const mixed = rows({
      attempts: [attempt("a1")],
      cards: [{ id: "1", topic: "Loops", last_reviewed_at: at(8, 9) }],
      guides: [guide("g1")],
    });
    expect(mixed.map(r => r.kind)).toEqual(["cards", "quiz", "guide"]);
    const many = Array.from({ length: RECENT_MAX + 5 }, (_, i) => attempt(`a${i}`, { completed_at: at(1, 1 + (i % 20)) }));
    expect(rows({ attempts: many })).toHaveLength(RECENT_MAX);
  });

  it("with no course there is nothing to show", () => {
    expect(recentActivity({ attempts: [attempt("a1")], cards: [], guides: [guide("g1")], topics: [], course: null, today: TODAY })).toEqual([]);
  });
});

describe("the Exams and Deadlines editor", () => {
  const saved = [assessment("hw", "Homework", 10, "Lab 5"), { ...assessment("e2", "Exam", 18, "Exam 2"), rawType: "midterm" }];
  const opened = new Map(saved.map(e => [e.id, e]));
  const fresh = (over: Partial<Draft> = {}): Draft => ({ ...newDraft(TODAY, 2, 1), ...over });

  it("a blank row is an exam a week out, with an id of its own", () => {
    expect(newDraft(TODAY, 3, 42)).toEqual({ id: "new-42-3", type: "Exam", title: "", iso: iso(15), isNew: true });
    expect(newDraft(new Date(2026, 11, 28), 0, 1).iso).toBe("2027-01-04"); // across the year
  });

  it("opens on the saved rows as they are", () => {
    expect(draftsOf(saved)).toEqual([
      { id: "hw", type: "Homework", title: "Lab 5", iso: iso(10) },
      { id: "e2", type: "Exam", title: "Exam 2", iso: iso(18) },
    ]);
  });

  it("an untouched editor writes nothing", () => {
    expect(planDates(draftsOf(saved), opened)).toEqual({ remove: [], update: [], add: [], addedExam: null });
  });

  it("patches only what changed, and leaves the stored type alone unless the class changed", () => {
    const [hw, e2] = draftsOf(saved);
    const plan = planDates([{ ...hw, type: "Quiz" }, { ...e2, title: " Exam Two ", iso: iso(19) }], opened);
    expect(plan.update).toEqual([
      { id: "hw", patch: { assignment_type: "quiz" } },
      { id: "e2", patch: { title: "Exam Two", due_date: iso(19) } }, // still a "midterm"
    ]);
    expect(plan.remove).toEqual([]);
  });

  it("removes the saved rows the editor no longer has", () => {
    expect(planDates(draftsOf(saved).slice(1), opened).remove).toEqual(["hw"]);
  });

  it("never removes or patches a row it was not opened with", () => {
    // The list loaded after the editor opened: the editor saw nothing.
    const plan = planDates([fresh({ title: "Final" })], new Map());
    expect(plan.remove).toEqual([]);
    expect(plan.update).toEqual([]);
    expect(plan.add).toEqual([{ title: "Final", due_date: iso(15), assignment_type: "exam" }]);
    // A saved-looking row that was not in the opened set is left alone too.
    expect(planDates(draftsOf(saved), new Map()).update).toEqual([]);
  });

  it("names a blank row for its type and position", () => {
    const plan = planDates([...draftsOf(saved), fresh({ type: "Quiz", title: "  " })], opened);
    expect(plan.add).toEqual([{ title: "Quiz 3", due_date: iso(15), assignment_type: "quiz" }]);
  });

  it("a blank row's default name steps past names the editor already has", () => {
    // Two saved "Exam 1"/"Exam 3"-style names would collide with the defaults
    // for rows 1 and 3; the calendar would refuse them as duplicates.
    const plan = planDates([
      { id: "e1", type: "Exam", title: "exam 2", iso: iso(18) },
      fresh({ id: "n1" }), // row 2: "Exam 2" is taken (case aside), so "Exam 3"
      fresh({ id: "n2" }), // row 3: "Exam 3" just went, so "Exam 4"
      fresh({ id: "n3", type: "Quiz" }), // row 4: nothing is called "Quiz 4"
    ], new Map());
    expect(plan.add.map(a => a.title)).toEqual(["Exam 3", "Exam 4", "Quiz 4"]);
  });

  it("the tab to open afterwards is the last exam or quiz added, never homework", () => {
    const rows = [fresh({ id: "n1", title: "Midterm" }), fresh({ id: "n2", title: "Final", iso: iso(30) }), fresh({ id: "n3", type: "Homework", title: "Lab" })];
    expect(planDates(rows, new Map()).addedExam).toEqual({ title: "Final", iso: iso(30) });
    expect(planDates([rows[2]], new Map()).addedExam).toBeNull();
  });
});

describe("saveOutcome", () => {
  const plan = (add: number, other = 0) => ({
    remove: Array.from({ length: other }, (_, i) => `r${i}`),
    update: [],
    add: Array.from({ length: add }, (_, i) => ({ title: `Exam ${i + 1}`, due_date: iso(15), assignment_type: "exam" })),
    addedExam: null,
  });

  it("is 'Dates saved' when every new row went in, or there were none to send", () => {
    expect(saveOutcome(plan(2), { saved_count: 2 })).toEqual({ saved: true, message: "Dates saved" });
    expect(saveOutcome(plan(0, 1), null)).toEqual({ saved: true, message: "Dates saved" });
    // An older server that does not count: taken at its word.
    expect(saveOutcome(plan(1), {})).toEqual({ saved: true, message: "Dates saved" });
  });

  it("names what the calendar skipped, and why", () => {
    const out = saveOutcome(plan(2), {
      saved_count: 0, skipped_count: 2,
      skipped: [
        { title: "Exam 1", due_date: iso(15), reason: "duplicate" },
        { title: "Exam 2", due_date: null, reason: "no_enrollment" },
      ],
    });
    expect(out).toEqual({
      saved: false,
      message: 'Not saved: "Exam 1" (already on your calendar), "Exam 2" (not a course you are enrolled in).',
    });
  });

  it("says the rest went in when it did", () => {
    const some = saveOutcome(plan(2), { saved_count: 1, skipped: [{ title: "Exam 1", reason: "duplicate" }] });
    expect(some).toEqual({ saved: false, message: 'Not saved: "Exam 1" (already on your calendar). Your other changes were saved.' });
    expect(saveOutcome(plan(1, 1), { saved_count: 0, skipped: [{ title: "Exam 1", reason: "duplicate" }] }).message)
      .toBe('Not saved: "Exam 1" (already on your calendar). Your other changes were saved.');
  });

  it("without the skipped list it still does not claim a save", () => {
    expect(saveOutcome(plan(1), { saved_count: 0 })).toEqual({ saved: false, message: "1 of 1 new date was not saved." });
    expect(saveOutcome(plan(3), { saved_count: 1 }).message).toBe("2 of 3 new dates were not saved. Your other changes were saved.");
    expect(saveOutcome(plan(1), { saved_count: 0, skipped: [{ title: "Exam 1", reason: "something new" }] }).message)
      .toBe('Not saved: "Exam 1" (not accepted).');
  });

  it("an untouched editor is an empty plan", () => {
    expect(planIsEmpty(plan(0))).toBe(true);
    expect(planIsEmpty(plan(1))).toBe(false);
    expect(planIsEmpty(plan(0, 1))).toBe(false);
  });
});
