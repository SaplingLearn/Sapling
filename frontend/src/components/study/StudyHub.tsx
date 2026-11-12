"use client";
/**
 * The Study hub: one page per course (design: "Sapling Study v2").
 *
 * Every number is derived from real data in ./studyModel.ts; this file owns
 * loading, interaction state, and layout. Data sources:
 *   courses ............ getCourses (passed in, semester-scoped)
 *   concepts/edges ..... getGraph(userId, semester)
 *   exams/deadlines .... getAllAssignments (+ save/update/deleteAssignment)
 *   quiz history ....... listAttempts (GET /api/quiz/attempts)
 *   flashcards ......... getFlashcards
 *   study guides ....... getCachedStudyGuides
 *   daily minutes/goal . getStudyDaily / setStudyDailyGoal (routes/study.py)
 *   roadmap categories . getTopicChecklist, and refreshTopicChecklist when the
 *                        course has no current outline (routes/topic_checklist.py)
 *   exam coverage ...... the same checklist (a topic's assessments + node_id)
 *
 * Its three tool buttons leave for pages of their own (@/lib/toolHrefs):
 * Study Guide -> /study/guide, Flashcards -> /flashcards, Quiz -> /quiz.
 */
import React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Icon } from "../Icon";
import { useToast } from "../ToastProvider";
import { useFlagMap } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import { humanizeError } from "@/lib/errorMessage";
import {
  getGraph,
  getAllAssignments,
  saveAssignments,
  updateAssignment,
  deleteAssignment,
  getFlashcards,
  getCachedStudyGuides,
  type Assignment,
  type EnrolledCourse,
  type StudyGuideCacheEntry,
} from "@/lib/api";
import { listAttempts } from "@/lib/quiz/api";
import { buildQuizHref } from "@/lib/quiz/source";
import type { AttemptSummary } from "@/lib/quiz/types";
import { getStudyDaily, setStudyDailyGoal, type StudyDaily } from "@/lib/studyApi";
import { getTopicChecklist, refreshTopicChecklist, type ChecklistTopic } from "@/lib/topicChecklistApi";
import { studyGuideHref, flashcardsHref, studyHref } from "@/lib/toolHrefs";
import { StudyHubSkeleton } from "../Skeleton";
import s from "./StudyHub.module.css";
import { StudyModal } from "./StudyModal";
import { DailyGoalCard, GOAL_MIN, GOAL_MAX } from "./DailyGoalCard";
import { CoursePicker } from "./CoursePicker";
import {
  conceptsForCourse,
  categoriesFromChecklist,
  roadmapGroups,
  classifyAssessment,
  daysTo,
  fmtDow,
  fmtWhen,
  countdown,
  countFg,
  scoreColor,
  readiness,
  readinessBand,
  studyQueue,
  squaresOrder,
  quickReviews,
  ring,

  ST_LABEL,
  TC,
  SC,
  STATUS_ORDER,
  type Assessment,
  type AssessType,

  type Status,
} from "./studyModel";
import { INHERIT_FONT } from "@/lib/inheritFont";

/* Type and colour come from the app tokens (globals.css), the ones the
   Dashboard is built on. Titles and figures use the display face, as its
   `.h-serif` does; micro labels are `.label-micro`; buttons are `.btn`. */
const DISPLAY = "var(--font-display)";
const SANS = "var(--font-sans)";
const MONO = "var(--font-mono)";
const TYPE_DOT: Record<AssessType, string> = { Exam: "var(--err)", Quiz: "#6A3E68", Homework: "var(--info)" };
const TYPE_RAW: Record<AssessType, string> = { Exam: "exam", Quiz: "quiz", Homework: "homework" };

type FlashcardRow = { id: string; topic?: string; last_reviewed_at?: string | null };
type Draft = { id: string; type: AssessType; rawType: string; title: string; iso: string; isNew?: boolean };

/* ── small inline icons the repo's Icon set doesn't carry ───────────────────── */
function CardsIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M7 3h11a2 2 0 0 1 2 2v11h-2V5H7z" />
      <path d="M4 7h11a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
    </svg>
  );
}
/* Prerequisite warning glyph: Sapling's leaf-shaped error badge (exclamation
   knocked out, so the banner's cream shows through), in the warning amber the
   design's round icon used rather than the badge's source green. */
function WarnIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
      <path
        fill="var(--warn)"
        d="M23.62,17.47c-.56-1.65-.86-3.75-1.75-5.26-.69-.94-1.05-2.34-1.77-3.2-.19-.25-.44-.49-.61-.76-1.48-2.92-4.17-5.22-6.64-7.34-.25-.21-.56-.37-.89-.37-.46.03-.93.11-1.41.4-.56.49-.8.93-1.33,1.42-.67.58-1.29,1.35-1.79,2.04-.67.75-1.44,1.34-1.97,2.18-.88,1.25-1.87,2.76-2.53,4.11-.22.71-.64,1.22-1,1.86-.71,1.31-.84,2.85-1.35,4.26-.2.67-.36,1.34-.19,2.03.33,1.38,1.7,1.93,2.93,2.26,1.08.4,2.1.83,3.25,1.11.61.15,1.28.05,1.8.1.74.33,1.72.18,2.37.7.37.24.75.49,1.22.47.7,0,1.13-.55,1.73-.78.57-.13,1.4-.16,1.95-.39,1.7.14,3.35-.54,4.94-1.14,1.58-.49,3.39-1.69,3.05-3.56l-.02-.11ZM11.78,19.32c-.78,0-1.41-.63-1.41-1.41s.63-1.41,1.41-1.41,1.41.64,1.41,1.41-.63,1.41-1.41,1.41ZM13.28,14.14c-.05.74-.66,1.31-1.4,1.31h-.2c-.74,0-1.35-.57-1.4-1.31l-.51-7.05c-.05-.82.59-1.51,1.41-1.51h1.2c.82,0,1.47.69,1.41,1.51l-.51,7.05Z"
      />
    </svg>
  );
}
function Glyph({ name, size }: { name: "bulb" | "cards" | "file"; size: number }) {
  return name === "cards" ? <CardsIcon size={size} /> : <Icon name={name} size={size} />;
}
const TOOLS = [
  { key: "quiz", title: "Quiz", icon: "bulb", bg: "#EBDDEE", fg: "#7A4A78" },
  { key: "cards", title: "Flashcards", icon: "cards", bg: "var(--sap-100)", fg: "var(--brand-forest)" },
  { key: "guide", title: "Study Guide", icon: "file", bg: "#F1E3C4", fg: "var(--warn)" },
] as const;


/** Recent Activity: rows shown in the rail, and the most "Show all" reveals. */
const RECENT_SHOWN = 4;
const RECENT_MAX = 30;

const sameName = (a?: string | null, b?: string | null) =>
  !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();

/**
 * The selected course's topic checklist, which names the roadmap columns and
 * says which concepts each exam covers. `[]` means "asked, nothing usable":
 * the roadmap falls back to layers and readiness to the whole course.
 *
 * The outline is per course, so it reloads with the course dropdown. A course
 * with no enrollment or no generated checklist answers with nothing to place,
 * which is not an error the student needs to see.
 *
 * The hub is also what GENERATES the outline: when the read says the course
 * has material the saved outline does not reflect (`needs_refresh`), it asks
 * for a refresh and swaps the result in when it lands. What the read returned
 * shows meanwhile and stays if the refresh fails (it is rate-limited and calls
 * a model), silently. One attempt per course and semester for the life of the
 * page: `refreshes` keeps each attempt, so coming back to a course whose
 * refresh is still running picks up that one instead of starting another.
 */
function useCourseOutline(userId: string, cid: string, semester: string, semesterReady: boolean): ChecklistTopic[] {
  const [outline, setOutline] = React.useState<ChecklistTopic[]>([]);
  const refreshes = React.useRef(new Map<string, Promise<ChecklistTopic[] | null>>());
  React.useEffect(() => {
    if (!userId || !cid || !semesterReady) { setOutline([]); return; }
    // Latest request wins: a course or semester change drops everything the
    // previous one still has in flight, its refresh included.
    let live = true;
    setOutline([]);
    const sem = semester || undefined;
    getTopicChecklist(userId, cid, sem)
      .then(r => {
        if (!live) return;
        setOutline(r.topics || []);
        if (!r.needs_refresh) return;
        const key = `${userId}|${cid}|${semester}`;
        let refresh = refreshes.current.get(key);
        if (!refresh) {
          refresh = refreshTopicChecklist(userId, cid, sem).then(
            f => f.topics || [],
            err => { console.error("study checklist refresh failed", err); return null; },
          );
          refreshes.current.set(key, refresh);
        }
        refresh.then(topics => { if (live && topics) setOutline(topics); });
      })
      .catch(err => { if (live) console.error("study checklist load failed", err); });
    return () => { live = false; };
  }, [userId, cid, semester, semesterReady]);
  return outline;
}

export function StudyHub({
  courses,
  coursesReady = true,
  semester,
  semesterReady,
  initialCourseId,
  isMobile,
  today: todayProp,
}: {
  courses: EnrolledCourse[];
  /** False until the course list has actually been fetched. An empty list
   *  means "no courses" only once this is true — before it, `courses` is just
   *  the initial `[]` and the "Add a course" empty state would be a lie. */
  coursesReady?: boolean;
  semester: string;
  semesterReady: boolean;
  initialCourseId?: string | null;
  isMobile: boolean;
  /** Test seam: a fixed "now". */
  today?: Date;
}) {
  const router = useRouter();
  // hide_quiz (#620) hides Quiz everywhere it is offered:
  // shown only once the flags are in and it is not hidden.
  const { flags: navFlags, ready: flagsReady } = useFlagMap();
  const quizShown = flagsReady && navFlags.hide_quiz !== "on";
  const toast = useToast();
  const { userId } = useUser();
  const today = React.useMemo(() => todayProp ?? new Date(), [todayProp]);

  /* ── data ─────────────────────────────────────────────────────────────── */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [graph, setGraph] = React.useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [assignments, setAssignments] = React.useState<Assignment[]>([]);
  const [attempts, setAttempts] = React.useState<AttemptSummary[]>([]);
  const [cards, setCards] = React.useState<FlashcardRow[]>([]);
  const [guides, setGuides] = React.useState<StudyGuideCacheEntry[]>([]);
  const [daily, setDaily] = React.useState<StudyDaily | null>(null);

  const loadAssignments = React.useCallback(async () => {
    if (!userId) return;
    try {
      const r = await getAllAssignments(userId);
      setAssignments(r.assignments || []);
    } catch (err) {
      console.error("study assignments load failed", err);
    }
  }, [userId]);

  React.useEffect(() => {
    if (!userId || !semesterReady) return;
    let live = true;
    getGraph(userId, semester || undefined)
      .then(r => { if (live) setGraph({ nodes: r.nodes || [], edges: r.edges || [] }); })
      .catch(err => {
        if (!live) return;
        console.error("study graph load failed", err);
        setGraph({ nodes: [], edges: [] });
        toast.error(humanizeError(err, "Couldn't load your concepts."));
      });
    getFlashcards(userId, undefined, semester || undefined)
      .then(r => { if (live) setCards(r.flashcards || []); })
      .catch(err => console.error("study flashcards load failed", err));
    return () => { live = false; };
  }, [userId, semester, semesterReady, toast]);

  React.useEffect(() => {
    if (!userId) return;
    let live = true;
    loadAssignments();
    listAttempts(userId, { limit: 100 })
      .then(r => { if (live) setAttempts(r.attempts || []); })
      .catch(err => console.error("study quiz history load failed", err));
    getCachedStudyGuides(userId)
      .then(r => { if (live) setGuides(r.guides || []); })
      .catch(err => console.error("study guides load failed", err));
    getStudyDaily(userId)
      .then(r => { if (live) setDaily(r); })
      .catch(err => console.error("study daily load failed", err));
    return () => { live = false; };
  }, [userId, loadAssignments]);

  /* ── course + exam selection ──────────────────────────────────────────── */
  const [courseId, setCourseId] = React.useState<string>(initialCourseId || "");
  const course = courses.find(c => c.course_id === courseId) || courses[0] || null;
  const cid = course?.course_id || "";

  const [st, setSt] = React.useState<{
    exam: string | null; topic: string | null; hover: string | null; lvl: Status | null;
    menu: "bell" | null; tileMenu: string | null; openCols: Record<string, boolean>;
    moreOpen: boolean; qrOpen: boolean; recentOpen: boolean;
  }>({ exam: null, topic: null, hover: null, lvl: null, menu: null, tileMenu: null, openCols: {}, moreOpen: false, qrOpen: false, recentOpen: false });
  const set = (patch: Partial<typeof st>) => setSt(prev => ({ ...prev, ...patch }));
  const [drafts, setDrafts] = React.useState<Draft[] | null>(null);
  /** What the open modal's drafts were made from. Save diffs against THIS, never
   *  the live list: a list that loads or reloads while the modal is open would
   *  otherwise read every row the drafts never saw as "removed" and delete it. */
  const manageBase = React.useRef<{ cid: string; rows: Map<string, Assessment> } | null>(null);
  const [saving, setSaving] = React.useState(false);

  const assessFor = React.useCallback((id: string): Assessment[] =>
    assignments
      .filter(a => a.course_id === id && a.due_date)
      .map(a => ({
        id: a.id,
        type: classifyAssessment(a.assignment_type, a.title),
        rawType: a.assignment_type || "",
        title: a.title,
        iso: String(a.due_date).slice(0, 10),
      }))
      .sort((p, q) => p.iso.localeCompare(q.iso)), [assignments]);

  const list = React.useMemo(() => assessFor(cid), [assessFor, cid]);
  const upcoming = list.filter(e => daysTo(e.iso, today) >= 0);
  // Every exam and quiz configured for the course gets a tab, past or not (as
  // in the v3 handoff: a date in Exams and Deadlines is enough). Homework stays
  // in the bell / deadline pill only. The default tab is the next exam ahead,
  // else the most recent one.
  const exams = list.filter(e => e.type !== "Homework");
  const nextExam = exams.find(e => daysTo(e.iso, today) >= 0) || exams[exams.length - 1] || null;
  const exam = exams.find(e => e.id === st.exam) || nextExam;
  // An exam just added in Exams and Deadlines: select its tab once it loads.
  const [justAdded, setJustAdded] = React.useState<{ title: string; iso: string } | null>(null);
  React.useEffect(() => {
    if (!justAdded) return;
    const hit = exams.find(e => e.title === justAdded.title && e.iso === justAdded.iso);
    if (hit) { setJustAdded(null); set({ exam: hit.id, topic: null, hover: null, lvl: null }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `set` is a stable state merger
  }, [justAdded, exams]);

  /** Dated work still ahead for a course: the count on its picker row. */
  const upcomingIn = (id: string) => assessFor(id).filter(e => daysTo(e.iso, today) >= 0).length;

  const pickCourse = (id: string) => {
    setCourseId(id);
    set({ exam: null, topic: null, hover: null, lvl: null, menu: null, tileMenu: null, recentOpen: false });
  };

  /* ── concepts ─────────────────────────────────────────────────────────── */
  const outline = useCourseOutline(userId, cid, semester, semesterReady);

  const categories = React.useMemo(() => categoriesFromChecklist(outline), [outline]);
  const topics = React.useMemo(
    () => (graph ? conceptsForCourse(graph.nodes, graph.edges, cid, today, categories) : []),
    [graph, cid, today, categories],
  );
  const byId = React.useMemo(() => new Map(topics.map(t => [t.id, t])), [topics]);
  const queue = studyQueue(topics);
  const rec = queue[0] || null;
  const sel = (st.topic && byId.get(st.topic)) || null;
  const hov = (st.hover && byId.get(st.hover)) || null;
  // The focus card and the prerequisite warning beside it follow the CLICKED
  // concept, never the hovered one. Both are in flow above the roadmap and
  // change height with the concept (a longer name or gap sentence wraps), so
  // previewing the hovered tile there pushed the whole roadmap down or up
  // under the pointer (~20-40px at 1280-1440 wide). Hover only highlights
  // prerequisites on the roadmap itself, which is paint-only.
  const focus = sel || rec;
  const hot = hov || sel;
  const hp = new Set(hot ? hot.pre : []);
  const hd = new Set(hot ? hot.post : []);
  const sp = new Set(sel ? sel.pre : []);
  const sd = new Set(sel ? sel.post : []);
  // The readiness band alone follows the selected exam: its figure, trend,
  // squares and legend counts are over the concepts the outline puts on that
  // exam, or over the whole course (labelled as the course) when it puts none.
  const band = readinessBand(topics, outline, exam, course?.course_code || course?.course_name || "");
  const ready = readiness(band.concepts);

  const completed = React.useMemo(
    () => attempts.filter(a => a.status === "completed" && a.score != null && a.total),
    [attempts],
  );
  const cardsFor = (name: string) => cards.filter(c => sameName(c.topic, name)).length;

  const soon = upcoming.filter(e => daysTo(e.iso, today) <= 7).length;

  /* ── navigation to the tool pages ─────────────────────────────────────── */
  // Two depths, on purpose.
  //   The header's tool buttons open the TOOL: its own home, on this course,
  //   with nothing started. That is where you browse decks, pick what to quiz,
  //   or choose an exam's guide.
  //   A concept's "..." menu, the Up Next block and Quick Reviews go straight
  //   INTO it: the quiz starts on that concept, flashcards open on its deck
  //   (`start=1`).
  // The hub owns "which course"; each tool opens on it and comes back to it.
  const quizHref = (ids: string[]) =>
    buildQuizHref(ids.length === 1 ? { concept: ids[0] } : { course: cid }, { kind: "link", returnTo: studyHref(cid) }, { start: true });
  const cardsHref = (names: string[]) => flashcardsHref(cid, names, { start: true });
  // Study Guide is not offered per concept: a guide is built for an exam, so
  // it is reached from the header only.
  const toolHome = (k: "quiz" | "cards" | "guide") =>
    k === "quiz" ? buildQuizHref({ course: cid }, { kind: "link", returnTo: studyHref(cid) })
      : k === "cards" ? flashcardsHref(cid)
      : studyGuideHref(cid);
  // Leaving for a tool fades the hub out first, so the tool's arrival
  // (`tool-enter`) reads as one hand-off rather than a cut.
  const [leaving, setLeaving] = React.useState(false);
  const leaveTo = React.useCallback((href: string) => {
    const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { router.push(href); return; }
    setLeaving(true);
    window.setTimeout(() => router.push(href), 180);
  }, [router]);
  const goTool = (k: "quiz" | "cards" | "guide") => leaveTo(toolHome(k));

  /* ── exams and deadlines modal ────────────────────────────────────────── */
  /** A blank row for the editor: an exam, a week out. */
  const newDraft = (n: number): Draft => {
    const d = new Date(today.getTime() + 7 * 86400000);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return { id: `new-${Date.now()}-${n}`, type: "Exam", rawType: "exam", title: "", iso, isNew: true };
  };
  /** The newest blank row's Name field, which takes focus when it appears. */
  const newNameRef = React.useRef<HTMLInputElement | null>(null);
  const openEditor = (withNewRow: boolean) => {
    manageBase.current = { cid, rows: new Map(list.map(e => [e.id, e])) };
    const rows: Draft[] = list.map(e => ({ id: e.id, type: e.type, rawType: e.rawType, title: e.title, iso: e.iso }));
    setDrafts(withNewRow ? [...rows, newDraft(rows.length)] : rows);
    set({ menu: null });
  };
  const openManage = () => openEditor(false);
  /** The "+" beside the exam tabs: the same editor, opened on a fresh row
   *  with the cursor in its Name field, so adding is one click and typing. */
  const openAdd = () => openEditor(true);
  const updDraft = (i: number, patch: Partial<Draft>) =>
    setDrafts(d => (d ? d.map((x, j) => (j === i ? { ...x, ...patch } : x)) : d));
  const saveManage = async () => {
    const base = manageBase.current;
    if (!drafts || !base || !userId || !base.cid || saving) return;
    const rows = drafts.map((e, i) => ({ ...e, title: e.title.trim() || `${e.type} ${i + 1}` }));
    const original = base.rows;
    const keep = new Set(rows.filter(r => !r.isNew).map(r => r.id));
    setSaving(true);
    try {
      for (const id of original.keys()) if (!keep.has(id)) await deleteAssignment(id, userId);
      for (const r of rows) {
        if (r.isNew) continue;
        const o = original.get(r.id);
        if (!o) continue;
        const patch: Partial<Pick<Assignment, "title" | "due_date" | "assignment_type">> = {};
        if (r.title !== o.title) patch.title = r.title;
        if (r.iso !== o.iso) patch.due_date = r.iso;
        if (r.type !== o.type) patch.assignment_type = TYPE_RAW[r.type];
        if (Object.keys(patch).length) await updateAssignment(r.id, userId, patch);
      }
      const added = rows.filter(r => r.isNew);
      const addedExam = added.filter(r => r.type !== "Homework").pop();
      if (addedExam) setJustAdded({ title: addedExam.title, iso: addedExam.iso });
      if (added.length) {
        await saveAssignments(userId, added.map(r => ({
          title: r.title, course_id: base.cid, due_date: r.iso, assignment_type: TYPE_RAW[r.type],
        })));
      }
      setDrafts(null);
      await loadAssignments();
      toast.success("Dates saved");
    } catch (err) {
      console.error("study dates save failed", err);
      toast.error(humanizeError(err, "Couldn't save those dates."));
      await loadAssignments();
    } finally {
      setSaving(false);
    }
  };

  const saveGoal = async (n: number): Promise<boolean> => {
    if (!userId || !Number.isFinite(n) || n < GOAL_MIN || n > GOAL_MAX) {
      toast.warn(`Pick a goal between ${GOAL_MIN} and ${GOAL_MAX} minutes.`);
      return false;
    }
    try {
      const r = await setStudyDailyGoal(userId, n);
      setDaily(d => (d ? { ...d, goal_minutes: r.goal_minutes } : d));
      return true;
    } catch (err) {
      console.error("daily goal save failed", err);
      toast.error(humanizeError(err, "Couldn't save your daily goal."));
      return false;
    }
  };

  /* ── roadmap columns ──────────────────────────────────────────────────── */
  const groups = roadmapGroups(topics);
  const LIM = 4;
  // The open tile menu closes on Esc (focus returns to its "..." button) or on a press
  // anywhere outside its tile. A press on ANOTHER tile closes this one and
  // that tile's click opens its own, so at most one menu is ever open. (This
  // replaced a full-screen click-catcher inside the tile, which lived in the
  // tile's stacking context and so sat under the later tiles it was meant
  // to cover.)
  const tileMenuOwner = React.useRef<HTMLDivElement | null>(null);
  const openTileMenu = st.tileMenu;
  React.useEffect(() => {
    if (!openTileMenu) return;
    const close = () => setSt(prev => (prev.tileMenu === openTileMenu ? { ...prev, tileMenu: null } : prev));
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const owner = tileMenuOwner.current;
      close();
      // Back to the "..." that opened it.
      (owner?.querySelector<HTMLElement>("[data-tile-actions]") ?? owner)?.focus();
    };
    const onDown = (e: Event) => {
      const owner = tileMenuOwner.current;
      if (owner && e.target instanceof Node && owner.contains(e.target)) return;
      close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [openTileMenu]);
  const columns = groups.map(label => {
    const ts = topics.filter(t => t.group === label);
    const tiles = ts.map(t => {
      const isSel = !!sel && sel.id === t.id;
      const isNext = !!rec && rec.id === t.id;
      const isHot = !!hot && hot.id === t.id;
      const rel = hot && !isHot ? (hp.has(t.id) ? "Needed First" : hd.has(t.id) ? "Unlocks" : "") : "";
      const dim = (!!st.lvl && t.st !== st.lvl) || (!!hot && !isHot && !rel && (hp.size > 0 || hd.size > 0));
      return { t, isSel, isNext, isHot, rel, dim, pin: isSel || isNext || sp.has(t.id) || sd.has(t.id) };
    });
    const key = cid + label;
    const open = !!st.openCols[key];
    let shown = tiles;
    let hidden: typeof tiles = [];
    if (tiles.length > LIM) {
      const keepIdx = tiles.map(x => x.t.st !== "mastered" || x.pin);
      let n = keepIdx.filter(Boolean).length;
      tiles.forEach((_, i) => { if (!keepIdx[i] && n < LIM) { keepIdx[i] = true; n++; } });
      hidden = tiles.filter((_, i) => !keepIdx[i]);
      if (!open) shown = tiles.filter((_, i) => keepIdx[i]);
    }
    return {
      label, key, open, shown, hidden,
      frac: `${ts.filter(t => t.st === "mastered").length}/${ts.length}`,
      bars: squaresOrder(ts).map(t => TC[t.st]),
    };
  });

  /* ── recent activity ──────────────────────────────────────────────────── */
  const recent = React.useMemo(() => {
    type Row = { key: string; at: number; kind: "quiz" | "cards" | "guide"; title: string; meta: string; result: string; resultColor: string; chips: { id: string; name: string; delta: number }[] };
    const out: Row[] = [];
    const conceptIds = new Set(topics.map(t => t.id));
    for (const a of completed) {
      if (a.course_id !== cid && !conceptIds.has(a.concept_node_id)) continue;
      const ts = a.completed_at || a.created_at;
      const p = Math.round(((a.score || 0) / (a.total || 1)) * 100);
      const delta = a.mastery_delta != null ? Math.round(a.mastery_delta * 100) : null;
      out.push({
        key: `q${a.quiz_id}`, at: Date.parse(ts), kind: "quiz", title: `${a.concept_name || "Concept"} Quiz`,
        meta: `Quiz · ${fmtWhen(ts, today)}`, result: `${p}%`, resultColor: scoreColor(p),
        chips: delta != null && a.concept_name ? [{ id: a.concept_node_id, name: a.concept_name, delta }] : [],
      });
    }
    const names = new Set([...topics.map(t => t.name.toLowerCase()), (course?.course_name || "").toLowerCase(), (course?.course_code || "").toLowerCase()].filter(Boolean));
    const decks = new Map<string, { topic: string; n: number; at: number }>();
    for (const c of cards) {
      if (!c.last_reviewed_at || !c.topic || !names.has(c.topic.trim().toLowerCase())) continue;
      const at = Date.parse(c.last_reviewed_at);
      const k = `${c.topic}|${new Date(at).toDateString()}`;
      const d = decks.get(k) || { topic: c.topic, n: 0, at: 0 };
      d.n += 1; d.at = Math.max(d.at, at);
      decks.set(k, d);
    }
    for (const [k, d] of decks) {
      out.push({ key: `c${k}`, at: d.at, kind: "cards", title: d.topic, meta: `Flashcards · ${fmtWhen(new Date(d.at).toISOString(), today)}`, result: `${d.n} ${d.n === 1 ? "card" : "cards"}`, resultColor: "var(--text-dim)", chips: [] });
    }
    for (const g of guides) {
      if (g.course_id !== cid) continue;
      out.push({ key: `g${g.id}`, at: Date.parse(g.generated_at), kind: "guide", title: `${g.exam_title || "Exam"} Study Guide`, meta: `Study Guide · ${fmtWhen(g.generated_at, today)}`, result: "", resultColor: "var(--text-dim)", chips: [] });
    }
    // Newest first. The rail shows RECENT_SHOWN of these and offers the rest
    // (up to RECENT_MAX) behind "Show all".
    return out.filter(r => Number.isFinite(r.at)).sort((a, b) => b.at - a.at).slice(0, RECENT_MAX);
  }, [completed, cards, guides, topics, cid, course, today]);

  /** One Recent Activity row: the rail shows the newest few, the "Show all"
   *  modal every one. */
  const recentRow = (rc: (typeof recent)[number]) => {
        const ic = rc.kind === "quiz" ? { bg: "#EBDDEE", fg: "#7A4A78", name: "bulb" as const } : rc.kind === "cards" ? { bg: "var(--sap-100)", fg: "var(--brand-forest)", name: "cards" as const } : { bg: "#F1E3C4", fg: "var(--warn)", name: "file" as const };
        return (
          <div key={rc.key} style={{ display: "grid", gridTemplateColumns: "28px minmax(0, 1fr)", columnGap: 10, padding: "8px 0" }}>
            <span style={{ width: 28, height: 28, borderRadius: 7, background: ic.bg, color: ic.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><Glyph name={ic.name} size={13} /></span>
            <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontSize: "var(--fs-md)", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{rc.title}</span>
                  <span style={{ display: "block", fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{rc.meta}</span>
                </span>
                {rc.result && <span style={{ fontSize: "var(--fs-md)", fontWeight: 600, color: rc.resultColor, whiteSpace: "nowrap" }}>{rc.result}</span>}
              </div>
              {rc.chips.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {rc.chips.map(ch => (
                    <button key={ch.id} onClick={() => byId.has(ch.id) && set({ topic: ch.id, recentOpen: false })} title="Mastery change from this quiz"
                      style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 22, padding: "0 8px", border: 0, borderRadius: 11, background: ch.delta >= 0 ? "var(--sap-100)" : "var(--err-soft)", color: "var(--text)", ...INHERIT_FONT, fontSize: "var(--fs-xs)", whiteSpace: "nowrap", flexShrink: 0, cursor: "pointer" }}>
                      {ch.name}<span style={{ fontWeight: 600, color: ch.delta >= 0 ? "var(--sap-600)" : "var(--err)" }}>{ch.delta >= 0 ? "+" : "−"}{Math.abs(ch.delta)}%</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
  };

  const qr = quickReviews(topics, today);

  /* ── render helpers ───────────────────────────────────────────────────── */
  const iconBtn: React.CSSProperties = { width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center", border: 0, borderRadius: "var(--r-sm)", background: "transparent", color: "var(--text-dim)", cursor: "pointer", position: "relative" };
  /* `.label-micro`, for the two places it sits on the dark Up Next block. */
  const microOnDark: React.CSSProperties = { fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--sap-100)" };
  /* The small tags that ride a tile's top edge: the `.chip` voice, tile-sized. */
  const tileTag: React.CSSProperties = { position: "absolute", top: -7, right: 8, height: 15, padding: "0 6px", borderRadius: "var(--r-full)", fontFamily: MONO, fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase", fontWeight: 600, display: "inline-flex", alignItems: "center", boxShadow: "0 0 0 2px var(--bg)" };
  const popover: React.CSSProperties = { background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: "var(--r-md)", boxShadow: "var(--shadow-lg)" };

  // The hub paints nothing real until it knows the student's courses AND has
  // their concepts: without this it rendered the "Add a course" empty state,
  // then the chrome, then the roadmap, in three visible steps.
  if (!coursesReady || !semesterReady || (!!courses.length && !graph)) {
    return <StudyHubSkeleton isMobile={isMobile} />;
  }

  if (!courses.length) {
    return (
      <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)", fontFamily: SANS, color: "var(--text)", padding: 32 }}>
        <div style={{ textAlign: "center", maxWidth: 420 }}>
          <h1 className="h-serif" style={{ margin: 0, fontSize: 42, letterSpacing: "-0.02em" }}>Study</h1>
          <p style={{ fontSize: "var(--fs-base)", color: "var(--text-dim)" }}>Add a course to get a study roadmap, readiness for each exam, and quick reviews.</p>
        </div>
      </div>
    );
  }

  const focusPres = focus ? focus.pre.map(id => byId.get(id)!).filter(Boolean) : [];
  let kS = 0;
  {
    let w = 0;
    for (; kS < focusPres.length; kS++) {
      const cw = 28 + focusPres[kS].name.length * 6.4 + 5;
      const reserve = kS < focusPres.length - 1 ? 80 : 0;
      if (w + cw + reserve > 230) break;
      w += cw;
    }
    kS = Math.max(kS, Math.min(1, focusPres.length));
  }
  const restP = focusPres.slice(kS);
  const focusArc = !focus ? "" : focus.st === "mastered" ? "var(--sap-300)" : focus.st === "progress" ? "#F0C75E" : focus.st === "review" ? "#F08A80" : "rgba(255,255,255,0.4)";
  const focusCards = focus ? cardsFor(focus.name) : 0;
  const focusActions = !focus ? [] : [
    { key: "quiz", icon: "bulb" as const, label: "Start quiz", href: quizHref([focus.id]) },
    { key: "cards", icon: "cards" as const, label: focusCards ? `Review ${focusCards} ${focusCards === 1 ? "flashcard" : "flashcards"}` : "Make flashcards", href: cardsHref([focus.name]) },
  ].filter(ac => ac.key !== "quiz" || quizShown);

  return (
    <div className={s.shell} style={{ background: "var(--bg)" }}>
    <div
      className={leaving ? `${s.hub} ${s.leaving}` : s.hub}
      style={{
        color: "var(--text)", fontFamily: SANS, fontSize: "var(--fs-md)", lineHeight: 1.45,
        WebkitFontSmoothing: "antialiased",
      }}
    >
      {/* ── header ── */}
      <header className={s.areaHeader} style={{ display: "flex", flexDirection: "column", gap: 10, padding: isMobile ? "14px 0" : "6px 0 18px" }}>
        {/* Laid out like the Dashboard's header: the title on the left, the
            page's actions (its three tools) on the right. */}
        <div className={s.headRow} style={{ display: "flex", alignItems: "center", gap: 16 }}>
        {/* The Dashboard greeting's size and line box, so the page title sits
            on the same line on both screens, at `.h-serif`'s own medium
            weight: the greeting's 600 is right for a sentence but made this
            one short word read as a slab. */}
        <h1 className="h-serif" style={{ margin: 0, fontSize: isMobile ? 34 : 42, letterSpacing: "-0.02em", lineHeight: 1.15, color: "var(--text)" }}>Study</h1>
        <CoursePicker courses={courses} value={cid} onChange={pickCourse} fullWidth={isMobile}
          meta={c => { const n = upcomingIn(c.course_id); return n > 0 ? `${n} upcoming` : null; }} />
        <nav aria-label="Study tools" style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: "auto" }}>
          {TOOLS.filter(tl => tl.key !== "quiz" || quizShown).map(tl => (
            <button key={tl.key} type="button" className={`btn btn--sm ${s.tool}`} onClick={() => goTool(tl.key)}>
              <span aria-hidden="true" style={{ display: "grid", color: tl.fg }}><Glyph name={tl.icon} size={14} /></span>
              {tl.title}
            </button>
          ))}
        </nav>
        </div>
      </header>

      {/* ── exam tabs + tools ── */}
      {/* The row itself is not animated (only the tab list is, re-keyed on the
          course): an animated ancestor would trap the deadlines pop-up and
          its click-away layer inside the row. */}
      <div className={s.areaTabs} style={{ display: "flex", alignItems: "center", gap: 16, borderBottom: "1px solid var(--border)", minWidth: 0 }}>
        <div key={cid} className={s.paneEnter} role="tablist" aria-label="Exams" style={{ flex: "0 1 auto", minWidth: 0, alignSelf: "stretch", display: "flex", gap: 28, overflowX: "auto", overflowY: "hidden" }}>
          {exams.map(e => {
            const on = !!exam && e.id === exam.id;
            return (
              <button key={e.id} role="tab" aria-selected={on} className={on ? undefined : s.hoverTab} onClick={() => set({ exam: e.id, topic: null, hover: null, lvl: null })}
                style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 0, flexShrink: 0, padding: "0 0 8px", border: 0, borderBottom: `2px solid ${on ? "var(--brand-forest)" : "transparent"}`, background: "transparent", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
                <span style={{ fontSize: "var(--fs-base)", fontWeight: 600, color: on ? "var(--text)" : "var(--text-muted)", whiteSpace: "nowrap" }}>{e.title}</span>
                <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>{fmtDow(e.iso, today)}</span>
              </button>
            );
          })}
          {exams.length === 0 && (
            <button onClick={openAdd} style={{ alignSelf: "center", padding: "0 0 8px", border: 0, background: "transparent", ...INHERIT_FONT, fontSize: "var(--fs-md)", fontWeight: 600, color: "var(--brand-forest)", cursor: "pointer" }}>+ Add Exam or Deadline</button>
          )}
        </div>
        {/* Add an exam right where the exams are listed: the "+" follows the
            last tab and opens the editor on a new row. (With no exams yet the
            row's "+ Add Exam or Deadline" link does the same.) */}
        {exams.length > 0 && (
          <button type="button" className={s.addExam} onClick={openAdd} aria-label="Add exam or deadline" title="Add an exam or deadline">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.5v9M1.5 6h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
          </button>
        )}
        {/* Upcoming deadlines sit with the exams, at the end of the exam row.
            The gear that opened the dates editor is gone: "+" adds a date, and
            the bell's "Manage Dates" opens the editor to change or remove one. */}
        <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0, marginLeft: "auto", paddingBottom: 6 }}>
        <div style={{ position: "relative" }}>
          <button className={s.hoverIcon} onClick={() => set({ menu: st.menu === "bell" ? null : "bell" })} aria-label={`Upcoming deadlines, ${soon} this week`} aria-expanded={st.menu === "bell"} title="Upcoming deadlines"
            style={{ ...iconBtn, background: st.menu === "bell" ? "var(--bg-soft)" : "transparent" }}>
            <Icon name="nofitication" size={18} />
            {soon > 0 && (
              <span style={{ position: "absolute", top: 2, right: 1, minWidth: 16, height: 16, padding: "0 4px", boxSizing: "border-box", borderRadius: 8, background: "var(--err)", color: "#FFFFFF", fontSize: "var(--fs-2xs)", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 0 2px var(--bg)" }}>{soon}</span>
            )}
          </button>
          {st.menu === "bell" && (
            <>
              <div onClick={() => set({ menu: null })} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
              <div role="dialog" aria-label="Upcoming deadlines" className={s.pop} style={{ position: "absolute", right: 0, top: 44, zIndex: 31, width: 320, maxWidth: "calc(100vw - 32px)", ...popover, padding: 6, display: "flex", flexDirection: "column" }}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "6px 8px 8px" }}>
                  <span style={{ fontFamily: DISPLAY, fontSize: "var(--fs-lg)", fontWeight: 600 }}>Upcoming Deadlines</span>
                  <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{course?.course_code || course?.course_name}</span>
                </div>
                {upcoming.length === 0 && <div style={{ padding: "4px 8px 10px", fontSize: "var(--fs-md)", color: "var(--text-muted)" }}>Nothing due for this course.</div>}
                {upcoming.map(e => {
                  const n = daysTo(e.iso, today);
                  return (
                    <button key={e.id} className={s.hoverOption} onClick={() => set(e.type === "Homework" ? { menu: null } : { menu: null, exam: e.id, topic: null, lvl: null })}
                      style={{ display: "flex", alignItems: "center", gap: 10, padding: 8, border: 0, borderRadius: "var(--r-sm)", background: "transparent", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: TYPE_DOT[e.type], flexShrink: 0 }} />
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "block", fontSize: "var(--fs-md)", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.title}</span>
                        <span style={{ display: "block", fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{e.type} · {fmtDow(e.iso)}</span>
                      </span>
                      <span style={{ fontSize: "var(--fs-sm)", fontWeight: 600, color: countFg(n), whiteSpace: "nowrap" }}>{countdown(n)}</span>
                    </button>
                  );
                })}
                <button onClick={openManage} style={{ marginTop: 4, padding: 8, border: 0, borderTop: "1px solid var(--border)", borderRadius: "0 0 8px 8px", background: "transparent", color: "var(--brand-forest)", ...INHERIT_FONT, fontSize: "var(--fs-md)", fontWeight: 600, cursor: "pointer" }}>Manage Dates</button>
              </div>
            </>
          )}
        </div>
        </div>
      </div>

      {/* ── readiness band ── */}
      <section aria-label="Readiness" key={`${cid}:${exam?.id ?? ""}`} className={`${s.areaReady} ${s.readyGrid} ${s.examEnter}`} style={{ padding: "16px 0", borderBottom: "1px solid var(--border)" }}>
        {/* Centred against the Up Next block beside it. Nothing here changes
            height with the selected concept any more (the prerequisite warning
            that used to sit under the legend is gone, along with the two lines
            it kept reserved, which is what left a blank band under this row),
            so centring no longer makes the figure jump. A concept's missing
            prerequisite is still marked on its roadmap tile. */}
        <div style={{ position: "relative", alignSelf: "stretch", display: "flex", flexDirection: "column", justifyContent: "center", gap: 14, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 14 }}>
            <span data-testid="readiness-pct" style={{ fontFamily: DISPLAY, fontSize: 42, fontWeight: 600, lineHeight: 1, letterSpacing: "-0.02em" }}>{graph ? `${ready.pct}%` : "–"}</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, paddingBottom: 2 }}>
              <span style={{ fontSize: "var(--fs-base)", lineHeight: 1.3, fontWeight: 600 }}>{band.label}</span>
              {ready.trend !== 0 && (
                <span className={`chip ${ready.trend > 0 ? "chip--accent" : "chip--err"}`} style={{ alignSelf: "flex-start" }}>
                  {ready.trend > 0 ? "+" : "−"}{Math.abs(ready.trend)}% this week
                </span>
              )}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div role="img" aria-label={`Overall mastery ${ready.pct} percent`} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {squaresOrder(band.concepts).map(t => (
                <button key={t.id} className={s.hoverSeg} onClick={() => set({ topic: sel && sel.id === t.id ? null : t.id })} title={`${t.name} · ${ST_LABEL[t.st]}`} aria-label={`${t.name} · ${ST_LABEL[t.st]}`}
                  style={{ width: 14, height: 14, flexShrink: 0, padding: 0, border: 0, borderRadius: "var(--r-xs)", background: TC[t.st], opacity: st.lvl && t.st !== st.lvl ? 0.3 : 1, boxShadow: sel && sel.id === t.id ? "0 0 0 1.5px var(--bg), 0 0 0 3px var(--brand-forest)" : "none", cursor: "pointer" }} />
              ))}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 4px", marginLeft: -6 }}>
              {STATUS_ORDER.map(k => {
                const on = st.lvl === k;
                return (
                  <button key={k} aria-pressed={on} className={on ? undefined : s.hoverLegend} onClick={() => set({ lvl: on ? null : k })} title="Highlight these on the roadmap"
                    style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 22, padding: "0 8px 0 6px", border: 0, borderRadius: "var(--r-full)", background: on ? "var(--sap-100)" : "transparent", ...INHERIT_FONT, fontSize: "var(--fs-xs)", color: on ? "var(--text)" : "var(--text-muted)", cursor: "pointer" }}>
                    {/* The Dashboard mastery legend: a round dot, the count, the state. */}
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: TC[k] }} />
                    <span>{band.concepts.filter(t => t.st === k).length} {ST_LABEL[k]}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {focus ? (
          <div data-testid="focus-card" className={s.focus} style={{ position: "relative", borderRadius: "var(--r-lg)", background: "var(--sidenav-bg)", color: "#FFFFFF", padding: "16px 18px", minWidth: 0 }}>
            {/* One row, like the Dashboard's lead plan row: the concept on the
                left, the ways straight into it on the right. Stacked once the
                block is too narrow for that (StudyHub.module.css). */}
            <div className={s.focusBody}>
            <div className={s.focusMain}>
              <span style={microOnDark}>{rec && focus.id === rec.id ? "Up Next" : focus.group}</span>
            <div className={s.focusConcept}>
              <span style={{ position: "relative", width: 54, height: 54, flexShrink: 0 }}>
                <svg width="54" height="54" viewBox="0 0 54 54" aria-hidden="true" style={{ display: "block", transform: "rotate(-90deg)" }}>
                  <circle cx="27" cy="27" r="23" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="5" />
                  <circle cx="27" cy="27" r="23" fill="none" stroke={focusArc} strokeWidth="5" strokeLinecap="round" strokeDasharray={ring(focus.m, 23)} />
                </svg>
                <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "var(--fs-base)", fontWeight: 600 }}>{focus.m}%</span>
              </span>
              <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                <span className={s.focusName} title={focus.name} style={{ fontFamily: DISPLAY, fontSize: 22, fontWeight: 600, lineHeight: 1.2, letterSpacing: "-0.01em" }}>{focus.name}</span>
                {/* One fixed-height line: the chips that fit, then "+N more". */}
                <div style={{ display: "flex", flexWrap: "nowrap", alignItems: "center", gap: 6, height: 22, fontSize: "var(--fs-sm)", color: "rgba(255,255,255,0.86)" }}>
                  {focusPres.length === 0 && <span style={{ flexShrink: 0, whiteSpace: "nowrap" }}>No prerequisites</span>}
                  {focusPres.slice(0, kS).map(t => (
                    <span key={t.id} title={`${t.name} · ${ST_LABEL[t.st]}`} style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 22, padding: "0 8px", borderRadius: 11, background: "rgba(255,255,255,0.12)", color: "#FFFFFF", fontSize: "var(--fs-xs)", fontWeight: 600, whiteSpace: "nowrap" }}>
                      <span style={{ width: 7, height: 7, borderRadius: "50%", background: TC[t.st] }} />{t.name}
                    </span>
                  ))}
                  {restP.length > 0 && (
                    <span onMouseEnter={() => set({ moreOpen: true })} onMouseLeave={() => set({ moreOpen: false })} style={{ position: "relative", flexShrink: 0 }}>
                      <span tabIndex={0} onFocus={() => set({ moreOpen: true })} onBlur={() => set({ moreOpen: false })} style={{ display: "inline-flex", alignItems: "center", height: 22, padding: "0 8px", borderRadius: 11, background: "rgba(255,255,255,0.22)", color: "#FFFFFF", fontSize: "var(--fs-xs)", fontWeight: 600, whiteSpace: "nowrap", cursor: "default" }}>+{restP.length} more</span>
                      {st.moreOpen && (
                        <span style={{ position: "absolute", left: 0, top: "100%", paddingTop: 6, zIndex: 25 }}>
                          <span className={s.pop} style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 180, padding: "8px 10px", ...popover, borderRadius: "var(--r-md)" }}>
                            {restP.map(t => (
                              <span key={t.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "var(--fs-md)", fontWeight: 600, color: "var(--text)", whiteSpace: "nowrap" }}>
                                <span style={{ width: 8, height: 8, borderRadius: "50%", background: TC[t.st] }} />{t.name}
                              </span>
                            ))}
                          </span>
                        </span>
                      )}
                    </span>
                  )}
                </div>
              </div>
            </div>
            </div>
            {/* Straight into this concept. The header's tool buttons open the
                tools themselves; these start the quiz / deck on what is up next. */}
            <nav aria-label={`Study ${focus.name}`} className={s.focusActions}>
              {focusActions.map((ac, i) => (
                <Link key={ac.key} href={ac.href} className={i === 0 ? `${s.focusAct} ${s.focusActPrimary}` : s.focusAct}
                  onClick={e => { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); leaveTo(ac.href); } }}>
                  <span aria-hidden="true" style={{ display: "grid" }}><Glyph name={ac.icon} size={14} /></span>
                  {ac.label}
                </Link>
              ))}
            </nav>
            </div>
          </div>
        ) : (
          <div className={s.focusEmpty} style={{ borderRadius: "var(--r-lg)", background: "var(--sidenav-bg)", color: "#FFFFFF", padding: "16px 18px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 6 }}>
            {topics.length ? (
              <>
                <span style={{ fontFamily: DISPLAY, fontSize: "var(--fs-xl)", fontWeight: 600 }}>Every concept is mastered</span>
                <span style={{ fontSize: "var(--fs-md)", color: "rgba(255,255,255,0.86)" }}>Keep them fresh with a mixed quiz before the exam.</span>
              </>
            ) : (
              <>
                <span style={{ fontFamily: DISPLAY, fontSize: "var(--fs-xl)", fontWeight: 600 }}>{graph ? "No concepts yet" : "Loading concepts"}</span>
                <span style={{ fontSize: "var(--fs-md)", color: "rgba(255,255,255,0.86)" }}>{graph ? "Upload course material in the Library to build this course's roadmap." : "One moment."}</span>
              </>
            )}
          </div>
        )}
      </section>

      {/* ── roadmap ── */}
      {/* An open tile menu can hang past the section's bottom edge; lifting
          the section keeps it over whatever follows (the rail, once the
          narrow layout stacks it underneath). */}
      <section aria-label="Roadmap" key={`roadmap:${cid}`} className={`${s.areaRoadmap} ${s.paneEnter}`}
        style={{ position: "relative", zIndex: st.tileMenu ? 2 : undefined, padding: "16px 6px 24px 0" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
          <span className="label-micro">Roadmap</span>
        </div>
        {/* auto-fit, not auto-fill: the columns share the whole row instead of
            leaving empty tracks (a blank strip) to their right. A course with
            only one or two columns is capped so its tiles don't stretch into
            banners.
            At most four columns across, at any width: a track is never
            narrower than a quarter of the row (less the three 16px gaps
            between four), so a fifth cannot fit beside four and a course with
            more categories wraps onto a second row. Below ~850px that quarter
            is under 200px and the 200px floor takes over, wrapping earlier as
            before. The 0.1px keeps four quarters from rounding up past the
            row's width, which would leave room for only three. */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(max(200px, calc((100% - 48px) / 4 - 0.1px)), 1fr))", gap: "20px 16px", alignItems: "start", maxWidth: columns.length < 3 ? columns.length * 336 - 16 : undefined }}>
          {/* Stacking: every column is its own stacking context (its colEnter
              opacity/transform animation), and so is any hovered (lifted) or
              dimmed tile. A z-index on the menu alone is therefore trapped
              and later tiles/columns paint over it, so the column AND the
              tile that own the open menu are lifted above their siblings. */}
          {columns.map((col, ci) => (
            <div key={col.key} className={s.colEnter}
              style={{ "--i": Math.min(ci, 6), position: "relative", zIndex: col.shown.some(x => x.t.id === st.tileMenu) ? 2 : undefined, display: "flex", flexDirection: "column", gap: 6, minWidth: 0 } as React.CSSProperties}>
              <div style={{ display: "flex", flexDirection: "column", gap: 5, paddingBottom: 2 }}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
                  <span style={{ fontSize: "var(--fs-md)", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{col.label}</span>
                  <span className="mono" style={{ fontSize: "var(--fs-xs)", color: "var(--text-dim)", flexShrink: 0 }}>{col.frac}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(8, minmax(0, 1fr))", gap: "4px 3px" }}>
                  {col.bars.map((b, i) => <span key={i} className={s.bar} style={{ height: 4, borderRadius: "var(--r-full)", background: b }} />)}
                </div>
              </div>
              {col.shown.map(({ t, isSel, isNext, rel, dim }) => {
                const warn = !!t.gap && t.st !== "mastered" && !rel;
                const n = cardsFor(t.name);
                const actions = [
                  { label: "Quiz Me", icon: "bulb" as const, bg: "#EBDDEE", fg: "#7A4A78", href: quizHref([t.id]) },
                  { label: n ? `${n} Flashcards` : "Make Flashcards", icon: "cards" as const, bg: "var(--sap-100)", fg: "var(--brand-forest)", href: cardsHref([t.name]) },
                ].filter(ac => ac.icon !== "bulb" || quizShown);
                const menuOpen = st.tileMenu === t.id;
                return (
                  <div key={t.id} ref={menuOpen ? tileMenuOwner : undefined} role="button" tabIndex={0} aria-pressed={isSel} data-testid={`tile-${t.id}`} className={`${s.tile}${isSel ? ` ${s.tileSel}` : isNext ? ` ${s.tileNext}` : ""}`}
                    // The tile selects the concept (the Up Next block follows it);
                    // going INTO a tool for it is the "..." button's menu.
                    onClick={() => set({ topic: isSel ? null : t.id, tileMenu: null })}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); set({ topic: isSel ? null : t.id, tileMenu: null }); } }}
                    onMouseEnter={() => set({ hover: t.id })} onMouseLeave={() => set({ hover: null })}
                    style={{ position: "relative", zIndex: menuOpen ? 2 : undefined, display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", borderRadius: "var(--r-md)", opacity: dim ? 0.3 : 1, cursor: "pointer" }}>
                    <span style={{ position: "relative", width: 28, height: 28, flexShrink: 0 }}>
                      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" style={{ display: "block", transform: "rotate(-90deg)" }}>
                        <circle cx="14" cy="14" r="11.5" fill="none" stroke="var(--bg-soft)" strokeWidth="3" />
                        <circle cx="14" cy="14" r="11.5" fill="none" stroke={TC[t.st]} strokeWidth="3" strokeLinecap="round" strokeDasharray={ring(t.m, 11.5)} />
                        <circle cx="14" cy="14" r="7.5" fill={t.st === "new" ? "transparent" : TC[t.st]} />
                      </svg>
                      <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#FFFFFF" }}>
                        {t.st === "mastered" && <Icon name="check" size={10} />}
                      </span>
                    </span>
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                      <span style={{ fontSize: "var(--fs-md)", fontWeight: 600, lineHeight: 1.25, textWrap: "pretty" } as React.CSSProperties}>{t.name}</span>
                      <span style={{ fontSize: "var(--fs-xs)", color: SC[t.st], whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.st === "new" ? "Not Started" : `${ST_LABEL[t.st]} · ${t.m}%`}</span>
                    </span>
                    {isNext && !isSel && <span style={{ ...tileTag, background: "var(--brand-forest)", color: "#FFFFFF" }}>Next</span>}
                    {rel && <span style={{ ...tileTag, background: rel === "Unlocks" ? "var(--info-soft)" : "var(--warn-soft)", color: rel === "Unlocks" ? "var(--info)" : "var(--warn)" }}>{rel}</span>}
                    {warn && <span title={t.gap} style={{ display: "block", lineHeight: 0, flexShrink: 0 }}><WarnIcon size={14} /></span>}
                    <button type="button" className={s.tileMore} data-testid={`tile-actions-${t.id}`} data-tile-actions=""
                      aria-label={`Actions for ${t.name}`} title="Quiz, flashcards or study guide for this concept" aria-haspopup="menu" aria-expanded={menuOpen}
                      onClick={e => { e.stopPropagation(); set({ topic: t.id, tileMenu: menuOpen ? null : t.id }); }}
                      // Enter/Space must press THIS button, not reach the tile's select handler.
                      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") e.stopPropagation(); }}>
                      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="currentColor"><circle cx="2.5" cy="7" r="1.3" /><circle cx="7" cy="7" r="1.3" /><circle cx="11.5" cy="7" r="1.3" /></svg>
                    </button>
                    {menuOpen && (
                      <>
                        <div role="menu" aria-label={`${t.name} actions`} className={s.pop} onClick={e => e.stopPropagation()}
                          // Enter/Space on an item must follow the link, not reach the tile's toggle.
                          onKeyDown={e => { if (e.key === "Enter" || e.key === " ") e.stopPropagation(); }}
                          style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 6px)", zIndex: 21, minWidth: 200, ...popover, borderRadius: "var(--r-md)", padding: 4, display: "flex", flexDirection: "column", gap: 2, cursor: "default" }}>
                          {actions.map(ac => (
                            <Link key={ac.label} role="menuitem" href={ac.href} className={s.hoverOption} onClick={e => { e.stopPropagation(); set({ tileMenu: null }); if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); leaveTo(ac.href); } }}
                              style={{ display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 6px", border: 0, borderRadius: "var(--r-sm)", background: "transparent", ...INHERIT_FONT, fontSize: "var(--fs-md)", fontWeight: 600, color: "var(--text)", textAlign: "left", textDecoration: "none", cursor: "pointer" }}>
                              <span style={{ width: 24, height: 24, borderRadius: 6, background: ac.bg, color: ac.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><Glyph name={ac.icon} size={12} /></span>
                              {ac.label}
                            </Link>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
              {col.hidden.length > 0 && (
                <button className={s.hoverMore} onClick={() => set({ openCols: { ...st.openCols, [col.key]: !col.open } })}
                  style={{ display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 10px", border: "1px dashed var(--border-strong)", borderRadius: "var(--r-md)", background: "transparent", ...INHERIT_FONT, fontSize: "var(--fs-sm)", fontWeight: 600, color: "var(--text-dim)", cursor: "pointer" }}>
                  <span style={{ display: "flex", gap: 3 }}>{col.hidden.map(x => <span key={x.t.id} style={{ width: 7, height: 7, borderRadius: 2, background: TC[x.t.st] }} />)}</span>
                  <span style={{ flex: 1, textAlign: "left", whiteSpace: "nowrap" }}>{col.open ? "Show Less" : `${col.hidden.length} more mastered`}</span>
                  <span style={{ display: "flex", flexShrink: 0, transform: col.open ? "rotate(180deg)" : "none" }}><Icon name="chevron-down" size={10} /></span>
                </button>
              )}
            </div>
          ))}
        </div>
        {graph && topics.length === 0 && <div style={{ fontSize: "var(--fs-md)", color: "var(--text-muted)" }}>Concepts from this course&apos;s knowledge graph will appear here.</div>}
      </section>

      {/* ── right column ── */}
      {/* The 40px side bleed (padding + negative margin, in the stylesheet so
          the narrow layout can drop it) gives the Quick Reviews pop-up's drop
          shadow room to fade out; it sits in the 56px column gap. */}
      <aside aria-label="Activity" className={s.areaRail} style={{ display: "flex", flexDirection: "column" }}>
        <section aria-label="Daily goal" style={{ display: "flex", flexDirection: "column", gap: 10, paddingBottom: 24 }}>
          <DailyGoalCard daily={daily} onSave={saveGoal} />

          {qr.length > 0 && (
            <div onMouseEnter={() => set({ qrOpen: true })} onMouseLeave={() => set({ qrOpen: false })} style={{ position: "relative" }}>
              <button className={s.hoverQr} onClick={() => leaveTo(cardsHref(qr.map(x => x.t.name)))} onFocus={() => set({ qrOpen: true })} onBlur={() => set({ qrOpen: false })} aria-expanded={st.qrOpen}
                style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "11px 11px", border: 0, borderRadius: "var(--r-md)", background: "var(--info-soft)", color: "var(--text)", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
                {/* Built like a Today's-plan row on the Dashboard: glyph, a
                    13px title over an 11px meta line, a chip, a chevron. */}
                <span aria-hidden="true" style={{ width: 18, display: "grid", placeItems: "center", flexShrink: 0, color: "var(--info)" }}><CardsIcon size={15} /></span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontSize: "var(--fs-md)", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{qr.length} Quick {qr.length === 1 ? "Review" : "Reviews"}</span>
                  <span style={{ display: "block", fontSize: "var(--fs-xs)", color: "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Flashcards on what&apos;s slipping</span>
                </span>
                <span className="chip chip--info" style={{ flexShrink: 0, background: "var(--bg-panel)" }}>{qr.length * 2} min</span>
                <span aria-hidden="true" style={{ display: "grid", flexShrink: 0, color: "var(--info)" }}><Icon name="chev" size={12} /></span>
              </button>
              {st.qrOpen && (
                <div style={{ position: "absolute", left: 0, right: 0, top: "100%", paddingTop: 8, zIndex: 31 }}>
                  <div role="dialog" aria-label="Quick reviews" className={s.pop} style={{ width: "100%", boxSizing: "border-box", ...popover, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                    <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: "var(--fs-base)", fontWeight: 600, color: "var(--text)" }}>{qr.length} Quick {qr.length === 1 ? "Review" : "Reviews"}</span>
                      <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{qr.length * 2} min · {exam ? `${qr.length} on ${exam.title}` : course?.course_code || course?.course_name}</span>
                    </span>
                    <span className={s.catScroll} style={{ display: "flex", flexDirection: "column", maxHeight: 200, overflowY: "auto", paddingRight: 4 }}>
                      {qr.map(x => (
                        <span key={x.t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid var(--border)" }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: TC[x.t.st], flexShrink: 0 }} />
                          <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-md)", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{x.t.name}</span>
                          <span style={{ fontSize: "var(--fs-xs)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>{x.ago >= 7 ? `Last seen ${x.ago} days ago` : `Slipping · ${x.t.m}%`}</span>
                        </span>
                      ))}
                    </span>
                    <button type="button" className="btn btn--primary" onClick={() => { set({ qrOpen: false }); leaveTo(cardsHref(qr.map(x => x.t.name))); }}
                      style={{ height: 36, justifyContent: "center" }}>Start Review</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <section aria-label="Recent activity" style={{ display: "flex", flexDirection: "column", gap: 2, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
          <span className="label-micro" style={{ marginBottom: 6 }}>Recent Activity</span>
          {recent.length === 0 && <span style={{ fontSize: "var(--fs-md)", color: "var(--text-muted)" }}>Quizzes, flashcards, and study guides for this course will show up here.</span>}
          {recent.slice(0, RECENT_SHOWN).map(recentRow)}
          {/* The rail never grows past these few rows (expanding it in
              place pushed the page far below the fold); the rest open in a
              modal that scrolls inside itself. */}
          {recent.length > RECENT_SHOWN && (
            <button type="button" className="btn btn--ghost btn--sm" data-testid="recent-toggle" aria-haspopup="dialog"
              onClick={() => set({ recentOpen: true })}
              // -10px: the ghost button's own side padding, so its label lines
              // up with the row icons above it.
              style={{ alignSelf: "flex-start", marginTop: 4, marginLeft: -10, color: "var(--text-dim)" }}>
              Show all {recent.length} <span aria-hidden="true">→</span>
            </button>
          )}
        </section>
      </aside>

      {/* ── all recent activity ── */}
      {st.recentOpen && (
        <StudyModal open onClose={() => set({ recentOpen: false })} label="Recent activity" width={480} maxHeight={640} top={isMobile ? 40 : 120} gap={4}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, paddingBottom: 8 }}>
            <span className="h-serif" style={{ fontSize: "var(--fs-2xl)" }}>Recent Activity</span>
            <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{course?.course_code || course?.course_name}</span>
          </div>
          {/* The LIST scrolls, not the dialog: the title and Close stay put,
              and the scrollbar sits inside the card (in the gutter this margin
              and padding make) instead of riding the dialog's rounded edge. */}
          <div className={s.catScroll} data-testid="recent-all"
            style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto", overscrollBehavior: "contain", marginRight: -14, paddingRight: 14 }}>
            {recent.map(recentRow)}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 12, marginTop: 8, borderTop: "1px solid var(--border)" }}>
            <button type="button" className="btn" onClick={() => set({ recentOpen: false })} style={{ height: 36, padding: "0 16px" }}>Close</button>
          </div>
        </StudyModal>
      )}

      {/* ── exams and deadlines modal ── */}
      {drafts && (
          <StudyModal open onClose={() => setDrafts(null)} label="Exams and deadlines" width={720} maxHeight={760} top={isMobile ? 40 : 120} gap={16} initialFocusRef={newNameRef}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
              <span className="h-serif" style={{ fontSize: "var(--fs-2xl)" }}>Exams and Deadlines</span>
              <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{course?.course_code ? `${course.course_code} · ${course.course_name}` : course?.course_name}</span>
            </div>
            <div className="label-micro" style={{ display: "grid", gridTemplateColumns: "140px minmax(0, 1fr) 170px 40px", gap: 10 }}><span>Type</span><span>Name</span><span>Date</span><span /></div>
            {drafts.map((dr, i) => {
              const field: React.CSSProperties = { height: 38, padding: "0 10px", border: "1px solid var(--border-strong)", borderRadius: "var(--r-sm)", background: "var(--bg-input)", ...INHERIT_FONT, fontSize: "var(--fs-md)", color: "var(--text)", boxSizing: "border-box", minWidth: 0 };
              return (
                <div key={dr.id} style={{ display: "grid", gridTemplateColumns: "140px minmax(0, 1fr) 170px 40px", gap: 10, alignItems: "center" }}>
                  <select value={dr.type} onChange={e => updDraft(i, { type: e.target.value as AssessType })} aria-label="Type" style={field}>
                    <option value="Exam">Exam</option><option value="Quiz">Quiz</option><option value="Homework">Homework</option>
                  </select>
                  <input ref={dr.isNew && i === drafts.length - 1 ? newNameRef : undefined} value={dr.title} onChange={e => updDraft(i, { title: e.target.value })} placeholder="e.g. Midterm 3" aria-label="Name" style={field} />
                  <input type="date" value={dr.iso} onChange={e => e.target.value && updDraft(i, { iso: e.target.value })} aria-label="Date" style={field} />
                  <button className={s.hoverRemove} onClick={() => setDrafts(d => (d ? d.filter((_, j) => j !== i) : d))} aria-label="Remove" title="Remove"
                    style={{ width: 38, height: 38, display: "flex", alignItems: "center", justifyContent: "center", border: 0, borderRadius: "var(--r-sm)", background: "transparent", color: "var(--err)", cursor: "pointer" }}>
                    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
                  </button>
                </div>
              );
            })}
            <button type="button" className="btn btn--sm" onClick={() => {
              setDrafts(ds => [...(ds || []), newDraft((ds || []).length)]);
              requestAnimationFrame(() => newNameRef.current?.focus());
            }}
              style={{ alignSelf: "flex-start", height: 34, padding: "0 12px", borderStyle: "dashed", borderColor: "var(--border-strong)", background: "transparent", color: "var(--brand-forest)", fontSize: "var(--fs-md)", fontWeight: 600 }}>+ Add Exam or Deadline</button>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
              <button type="button" className="btn btn--ghost" onClick={() => setDrafts(null)} style={{ height: 40, padding: "0 16px" }}>Cancel</button>
              <button type="button" className="btn btn--primary" onClick={saveManage} disabled={saving} style={{ height: 40, padding: "0 16px", cursor: saving ? "wait" : "pointer" }}>{saving ? "Saving" : "Save Dates"}</button>
            </div>
          </StudyModal>
      )}
    </div>
    </div>
  );
}
