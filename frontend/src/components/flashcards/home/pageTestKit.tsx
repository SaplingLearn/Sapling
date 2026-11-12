/**
 * Shared by the Flashcards page suites (FlashcardsHome.test.tsx and
 * SetBuilder.test.tsx): the course fixture, the mocks' defaults and the
 * helpers that drive the page. Test-only: nothing in the app imports it.
 *
 * Each suite declares its own `vi.mock(...)` blocks (they are hoisted per
 * file); this module then sees the same mocked modules the page does.
 */
import React from "react";
import { vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  getCourses,
  getFlashcards,
  generateFlashcards,
  getDocuments,
  getGraph,
  getAllAssignments,
  type EnrolledCourse,
} from "@/lib/api";
import {
  listFlashcardSets,
  createFlashcardSet,
  updateFlashcardSet,
  deleteFlashcardSet,
  suggestFlashcardSet,
  type FlashcardSet,
  type FlashcardSetSuggestion,
} from "@/lib/flashcardSetsApi";
import { getTopicChecklist, type TopicChecklist } from "@/lib/topicChecklistApi";
import { Flashcards } from "../../screens/Flashcards";
import { ToastProvider } from "../../ToastProvider";

export const mocks = {
  courses: vi.mocked(getCourses),
  cards: vi.mocked(getFlashcards),
  generate: vi.mocked(generateFlashcards),
  graph: vi.mocked(getGraph),
  assignments: vi.mocked(getAllAssignments),
  checklist: vi.mocked(getTopicChecklist),
  sets: vi.mocked(listFlashcardSets),
  create: vi.mocked(createFlashcardSet),
  update: vi.mocked(updateFlashcardSet),
  remove: vi.mocked(deleteFlashcardSet),
  suggest: vi.mocked(suggestFlashcardSet),
};

// ── fixtures ──────────────────────────────────────────────────────────────

export const NOW = new Date("2026-11-12T12:00:00Z");
export const PAST = "2026-11-11T09:00:00Z";
export const FUTURE = "2026-11-20T09:00:00Z";

export const COURSE: EnrolledCourse = {
  enrollment_id: "enr-c1", course_id: "c1", course_code: "CS101", course_name: "Intro to CS",
  school: "BU", department: "CS", color: null, nickname: null, node_count: 0,
  enrolled_at: "2026-09-01", term: "Fall 2026",
};

export const node = (id: string, name: string, tier: string, score = 0, course = "c1") =>
  ({ id, course_id: course, concept_name: name, mastery_tier: tier, mastery_score: score });

// No usable outline categories, so the builder's columns are the hub's layers:
// Foundations = Pointers, Sorting, Trees, Variables; Core Methods = Recursion.
export const NODES = [
  node("n1", "Variables", "mastered", 0.9),
  node("n2", "Recursion", "struggling", 0.2),
  node("n3", "Sorting", "unexplored"),
  node("n4", "Pointers", "learning", 0.5),
  node("n5", "Trees", "unexplored"),
  node("n9", "Limits", "learning", 0.5, "c2"),
];
export const EDGES = [{ source: "n1", target: "n2", relationship_type: "prerequisite" }];

export type TestCard = { id: string; topic: string; front: string; back: string; course_id: string | null; due_at?: string | null };
export const card = (id: string, topic: string, extra: Partial<TestCard> = {}): TestCard =>
  ({ id, topic, front: `Q-${id}`, back: `A-${id}`, course_id: "c1", ...extra });

/** Five cards in the course (two of them due), one in another course. */
export const CARDS: TestCard[] = [
  card("v1", "Variables", { due_at: PAST }),
  card("v2", "Variables", { due_at: FUTURE }),
  card("r1", "Recursion", { due_at: PAST }),
  card("p1", "Pointers"),
  card("d1", "CS Basics"),
  card("x1", "Recursion", { course_id: "c2", due_at: PAST }),
];
/** The same cards with due dates not tracked (how the data is today). */
export const CARDS_NO_DUE = CARDS.map(c => ({ ...c, due_at: null }));

export const EXAM = { id: "e1", user_id: "u1", title: "Midterm 2", due_date: "2026-11-21", assignment_type: "exam", course_id: "c1" };
export const OUTLINE = [
  { id: "t1", name: "Recursion", parent_id: null, node_id: "n2", assessments: [{ id: "e1" }] },
  { id: "t2", name: "Sorting", parent_id: null, node_id: "n3", assessments: [{ id: "e1" }] },
];

export const savedSet = (over: Partial<FlashcardSet> = {}): FlashcardSet => ({
  id: "s1", name: "Midterm crunch", course_id: "c1", concepts: ["Variables", "Recursion", "Graphs"],
  options: { only_due: true, shuffle: false }, exam_id: "e1",
  created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", ...over,
});
export const POINTERS_SET = savedSet({ id: "s2", name: "Pointers only", concepts: ["Pointers"], options: { only_due: false, shuffle: true }, exam_id: null });

export const suggestion = (over: Partial<FlashcardSetSuggestion> = {}): FlashcardSetSuggestion => ({
  name: "Midterm: pointers and recursion",
  concepts: [
    { name: "pointers", course_id: "c1", source: "named", confidence: 1 },
    { name: "Recursion", course_id: "c1", source: "named", confidence: 1 },
    { name: "Dynamic Programming", course_id: "c1", source: "model", confidence: 0.6 },
  ],
  considered: 5,
  backend: "function",
  ...over,
});

export function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

export const generated = (cards: TestCard[]) => ({ flashcards: cards, context_used: { documents_found: 1, weak_concepts_found: 0 } });

// ── harness ───────────────────────────────────────────────────────────────

/** The URL the page reads on mount, and the live one `start` is consumed from. */
export function arriveAt(qs: string) {
  window.history.replaceState(null, "", qs ? `/flashcards?${qs}` : "/flashcards");
}

/** Every mock back to the fixture course. Call in `beforeEach`. */
export function resetMocks() {
  vi.resetAllMocks();
  arriveAt("");
  // A review left open by the last test is not this one's to come back to.
  window.sessionStorage.clear();
  vi.spyOn(console, "error").mockImplementation(() => {});
  mocks.courses.mockResolvedValue({ courses: [COURSE] });
  mocks.cards.mockResolvedValue({ flashcards: CARDS });
  mocks.graph.mockResolvedValue({ nodes: NODES, edges: EDGES, stats: {} });
  mocks.assignments.mockResolvedValue({ assignments: [EXAM] });
  mocks.checklist.mockResolvedValue({ topics: OUTLINE } as unknown as TopicChecklist);
  mocks.sets.mockResolvedValue({ sets: [] });
  vi.mocked(getDocuments).mockResolvedValue({ documents: [] });
}

export function renderPage() {
  return render(
    <ToastProvider>
      <Flashcards now={NOW} random={() => 0} />
    </ToastProvider>,
  );
}

// ── the home ──────────────────────────────────────────────────────────────

export const deck = (id: string) => screen.getByTestId(`flashcards-deck-${id}`);
export const figure = (kind: "cards" | "concepts" | "sets") =>
  screen.getByTestId(`flashcards-figure-${kind}`).querySelector("dd")?.textContent;
export const homeStatus = () => screen.getByTestId("flashcards-home-status").textContent;

/** The home is up: every read it waits on has answered. */
export async function home() {
  renderPage();
  await screen.findByTestId("flashcards-home-status");
  return userEvent.setup();
}

// ── the builder ───────────────────────────────────────────────────────────

export const tile = (name: string) => screen.getByRole("checkbox", { name: new RegExp(`^${name}`) });
export const findTile = (name: string) => screen.findByRole("checkbox", { name: new RegExp(`^${name}`) });
export const selection = () => screen.getByTestId("flashcards-selection").textContent;
/** The "Your own" column: decks that are not concepts, and added concepts. */
export const ownColumn = () => screen.getByRole("checkbox", { name: "Select all of Your own" }).closest("label")!.parentElement as HTMLElement;
/** The ticked tiles' names, in the map's order. */
export const ticked = () =>
  screen.queryAllByRole("checkbox", { checked: true })
    .filter(box => !box.getAttribute("aria-label"))
    .map(box => box.closest("label")?.querySelector("span > span")?.textContent);

/** The builder, opened from the home with nothing ticked. */
export async function builder() {
  const user = await home();
  await user.click(screen.getByRole("button", { name: /Build one by hand/ }));
  await findTile("Variables");
  return user;
}
