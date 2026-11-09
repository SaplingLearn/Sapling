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
 *   roadmap categories . getTopicChecklist (routes/topic_checklist.py)
 *
 * Its three tool buttons leave for pages of their own (@/lib/toolHrefs):
 * Study Guide -> the Library, Flashcards -> /flashcards, Quiz -> /quiz.
 */
import React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Icon } from "../Icon";
import { useToast } from "../ToastProvider";
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
import { getTopicChecklist, type ChecklistTopic } from "@/lib/topicChecklistApi";
import { studyGuideHref, flashcardsHref } from "@/lib/toolHrefs";
import { StudyHubSkeleton } from "../Skeleton";
import s from "./StudyHub.module.css";
import { StudyModal } from "./StudyModal";
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
  studyQueue,
  squaresOrder,
  quickReviews,
  pace,
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

const SERIF = "var(--font-serif), 'Aleo', georgia, serif";
const SANS = "var(--font-sans), 'SUSE', system-ui, sans-serif";
const MONO = "var(--font-mono), 'IBM Plex Mono', monospace";
const TYPE_DOT: Record<AssessType, string> = { Exam: "#A8443F", Quiz: "#6A3E68", Homework: "#2E5F96" };
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
function WarnIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
      <path
        fill="#D9A93A"
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
  { key: "cards", title: "Flashcards", icon: "cards", bg: "#E1ECD7", fg: "#445D22" },
  { key: "guide", title: "Study Guide", icon: "file", bg: "#F1E3C4", fg: "#8A6420" },
] as const;


const sameName = (a?: string | null, b?: string | null) =>
  !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();

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
  /** The selected course's topic checklist, which names the roadmap columns.
   *  `[]` means "asked, nothing usable" — the roadmap falls back to layers. */
  const [outline, setOutline] = React.useState<ChecklistTopic[]>([]);

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
    menu: "course" | "bell" | null; tileMenu: string | null; openCols: Record<string, boolean>;
    moreOpen: boolean; qrOpen: boolean; aiOpen: boolean; goalOpen: boolean;
  }>({ exam: null, topic: null, hover: null, lvl: null, menu: null, tileMenu: null, openCols: {}, moreOpen: false, qrOpen: false, aiOpen: false, goalOpen: false });
  const set = (patch: Partial<typeof st>) => setSt(prev => ({ ...prev, ...patch }));
  const [drafts, setDrafts] = React.useState<Draft[] | null>(null);
  /** What the open modal's drafts were made from. Save diffs against THIS, never
   *  the live list: a list that loads or reloads while the modal is open would
   *  otherwise read every row the drafts never saw as "removed" and delete it. */
  const manageBase = React.useRef<{ cid: string; rows: Map<string, Assessment> } | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [goalDraft, setGoalDraft] = React.useState("");

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

  const pickCourse = (id: string) => {
    setCourseId(id);
    set({ exam: null, topic: null, hover: null, lvl: null, menu: null, tileMenu: null });
  };

  /* ── concepts ─────────────────────────────────────────────────────────── */
  // The outline is per course, so it reloads with the course dropdown. A course
  // with no enrollment or no generated checklist answers with nothing to place,
  // which is not an error the student needs to see: the roadmap falls back to
  // prerequisite layers and the rest of the page is unaffected.
  React.useEffect(() => {
    if (!userId || !cid || !semesterReady) { setOutline([]); return; }
    let live = true;
    setOutline([]);
    getTopicChecklist(userId, cid, semester || undefined)
      .then(r => { if (live) setOutline(r.topics || []); })
      .catch(err => { if (live) console.error("study checklist load failed", err); });
    return () => { live = false; };
  }, [userId, cid, semester, semesterReady]);

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
  const { pct, trend } = readiness(topics);
  const days = exam ? daysTo(exam.iso, today) : -1;

  const completed = React.useMemo(
    () => attempts.filter(a => a.status === "completed" && a.score != null && a.total),
    [attempts],
  );
  const lastQuizOn = (id: string) => completed.find(a => a.concept_node_id === id) || null;
  const cardsFor = (name: string) => cards.filter(c => sameName(c.topic, name)).length;

  const weekMinutes = (daily?.days || []).reduce((n, d) => n + d.minutes, 0);
  const ai = exam && topics.length
    ? pace({ examTitle: exam.title, days, readiness: pct, weekGain: trend, weekMinutes, nextConcept: rec?.name })
    : null;
  const due = upcoming.find(e => e.type === "Homework" && daysTo(e.iso, today) <= 2) || null;
  const soon = upcoming.filter(e => daysTo(e.iso, today) <= 7).length;

  /* ── navigation to the tool pages ─────────────────────────────────────── */
  // Every Quiz / Flashcards control here goes straight to the tool and asks it
  // to START (`start=1`): the quiz begins on the concept, or on the course's
  // queue, and flashcards open on the concept's deck, generating it when there
  // are no cards yet. There used to be a concept picker in between, whose only
  // effect was this same navigation one click later.
  const quizHref = (ids: string[]) =>
    buildQuizHref(ids.length === 1 ? { concept: ids[0] } : { course: cid }, { kind: "link", returnTo: "/study" }, { start: true });
  const cardsHref = (names: string[]) => flashcardsHref(cid, names, { start: true });
  // Study guides are Library documents now. For one concept this opens the
  // course's material FOR that concept; with no concept, the course's
  // study-guide shelf. (The selected exam has nothing to narrow there.)
  const guideHref = (concept?: string) => studyGuideHref(cid, concept);
  // The top tool buttons cover what the picker used to preselect: the
  // struggling and learning concepts. One of them is a concept quiz; none or
  // several is the course's quiz (a quiz is one concept or the whole course).
  const goTool = (k: "quiz" | "cards" | "guide") => {
    if (k === "guide") { router.push(guideHref()); return; }
    const weak = topics.filter(t => t.st === "review" || t.st === "progress");
    router.push(k === "quiz" ? quizHref(weak.map(t => t.id)) : cardsHref(weak.map(t => t.name)));
  };

  /* ── exams and deadlines modal ────────────────────────────────────────── */
  const openManage = () => {
    manageBase.current = { cid, rows: new Map(list.map(e => [e.id, e])) };
    setDrafts(list.map(e => ({ id: e.id, type: e.type, rawType: e.rawType, title: e.title, iso: e.iso })));
    set({ menu: null });
  };
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

  const saveGoal = async () => {
    const n = Math.round(Number(goalDraft));
    if (!userId || !Number.isFinite(n) || n < 5 || n > 600) {
      toast.warn("Pick a goal between 5 and 600 minutes.");
      return;
    }
    try {
      const r = await setStudyDailyGoal(userId, n);
      setDaily(d => (d ? { ...d, goal_minutes: r.goal_minutes } : d));
      set({ goalOpen: false });
    } catch (err) {
      console.error("daily goal save failed", err);
      toast.error(humanizeError(err, "Couldn't save your daily goal."));
    }
  };

  /* ── roadmap columns ──────────────────────────────────────────────────── */
  const groups = roadmapGroups(topics);
  const LIM = 4;
  // The open tile menu closes on Esc (focus returns to its tile) or on a press
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
      close();
      tileMenuOwner.current?.focus();
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
      out.push({ key: `c${k}`, at: d.at, kind: "cards", title: d.topic, meta: `Flashcards · ${fmtWhen(new Date(d.at).toISOString(), today)}`, result: `${d.n} ${d.n === 1 ? "card" : "cards"}`, resultColor: "#3F3B31", chips: [] });
    }
    for (const g of guides) {
      if (g.course_id !== cid) continue;
      out.push({ key: `g${g.id}`, at: Date.parse(g.generated_at), kind: "guide", title: `${g.exam_title || "Exam"} Study Guide`, meta: `Study Guide · ${fmtWhen(g.generated_at, today)}`, result: "", resultColor: "#3F3B31", chips: [] });
    }
    return out.filter(r => Number.isFinite(r.at)).sort((a, b) => b.at - a.at).slice(0, 5);
  }, [completed, cards, guides, topics, cid, course, today]);

  const qr = quickReviews(topics, today);

  /* ── render helpers ───────────────────────────────────────────────────── */
  const iconBtn: React.CSSProperties = { width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", border: 0, borderRadius: 12, background: "transparent", color: "#3F3B31", cursor: "pointer", position: "relative" };
  const pillBase: React.CSSProperties = { display: "flex", alignItems: "center", gap: 10, height: 44, padding: "0 16px 0 6px", border: 0, borderRadius: 22, ...INHERIT_FONT, fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", cursor: "pointer" };
  const pillDot: React.CSSProperties = { width: 32, height: 32, borderRadius: "50%", background: "#FFFFFF", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 };
  const monoLabel: React.CSSProperties = { fontFamily: MONO, fontSize: 12, letterSpacing: "0.14em", textTransform: "uppercase", color: "#6F6857" };
  const popover: React.CSSProperties = { background: "#FDFCF9", border: "1px solid rgba(42,39,31,0.14)", borderRadius: 14, boxShadow: "0 16px 40px rgba(25,37,11,0.18)" };

  // The hub paints nothing real until it knows the student's courses AND has
  // their concepts: without this it rendered the "Add a course" empty state,
  // then the chrome, then the roadmap, in three visible steps.
  if (!coursesReady || !semesterReady || (!!courses.length && !graph)) {
    return <StudyHubSkeleton isMobile={isMobile} />;
  }

  if (!courses.length) {
    return (
      <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "#FAF8F3", fontFamily: SANS, color: "#1A1814", padding: 32 }}>
        <div style={{ textAlign: "center", maxWidth: 420 }}>
          <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: 34, fontWeight: 600 }}>Study</h1>
          <p style={{ fontSize: 15, color: "#3F3B31" }}>Add a course to get a study roadmap, readiness for each exam, and quick reviews.</p>
        </div>
      </div>
    );
  }

  const focusPres = focus ? focus.pre.map(id => byId.get(id)!).filter(Boolean) : [];
  let kS = 0;
  {
    let w = 0;
    for (; kS < focusPres.length; kS++) {
      const cw = 34 + focusPres[kS].name.length * 7.4 + 6;
      const reserve = kS < focusPres.length - 1 ? 80 : 0;
      if (w + cw + reserve > 400) break;
      w += cw;
    }
    kS = Math.max(kS, Math.min(1, focusPres.length));
  }
  const restP = focusPres.slice(kS);
  const lq = focus ? lastQuizOn(focus.id) : null;
  const lqp = lq ? Math.round(((lq.score || 0) / (lq.total || 1)) * 100) : 0;
  const quizColor = !lq ? "rgba(255,255,255,0.6)" : lqp >= 80 ? "#A1BC83" : lqp >= 60 ? "#F0C75E" : "#F08A80";
  const focusArc = !focus ? "" : focus.st === "mastered" ? "#A1BC83" : focus.st === "progress" ? "#F0C75E" : focus.st === "review" ? "#F08A80" : "rgba(255,255,255,0.4)";
  const warnInCard = !!focus && !!focus.gap && focus.st === "new";
  const warnLeft = !!focus && !!focus.gap && focus.st !== "mastered" && focus.st !== "new";

  const goal = daily?.goal_minutes ?? 30;
  const week = daily?.days || [];
  const todayRow = week[week.length - 1];
  const done = todayRow?.minutes ?? 0;
  const MAX = Math.max(goal * 1.5, ...week.map(d => d.minutes), 1);
  const hit = week.slice(0, 6).filter(d => d.minutes >= goal).length;

  return (
    <div className={s.shell} style={{ background: "#FAF8F3" }}>
    <div
      className={s.hub}
      style={{
        color: "#1A1814", fontFamily: SANS, fontSize: 15, lineHeight: 1.45,
        WebkitFontSmoothing: "antialiased",
      }}
    >
      {/* ── header ── */}
      <header className={s.areaHeader} style={{ display: "flex", alignItems: "center", gap: 20, paddingBottom: 18 }}>
        <h1 style={{ margin: 0, fontFamily: SERIF, fontSize: 34, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.15 }}>Study</h1>
        {/* Was a hard 320px, which ellipsed "Introduction to Computer Science"
            even on a 1920 screen with room to spare. It now takes what the
            header has and caps only so a long name can't crowd out the bell
            and settings beside it. */}
        <div style={{ position: "relative", flex: isMobile ? "1 1 100%" : "0 1 auto", minWidth: 0, maxWidth: 560 }}>
          <button className={s.hoverCourse} onClick={() => set({ menu: st.menu === "course" ? null : "course" })} aria-haspopup="listbox" aria-expanded={st.menu === "course"}
            style={{ display: "inline-flex", alignItems: "center", gap: 10, maxWidth: "100%", height: 44, padding: "0 12px", border: 0, borderRadius: 12, background: "transparent", ...INHERIT_FONT, color: "#1A1814", cursor: "pointer" }}>
            <span style={{ width: 11, height: 11, borderRadius: "50%", background: course?.color || "#6F6857", flexShrink: 0 }} />
            <span style={{ fontSize: 17, fontWeight: 700, whiteSpace: "nowrap" }}>{course?.course_code || course?.course_name}</span>
            {course?.course_code && <span style={{ minWidth: 0, fontSize: 16, color: "#3F3B31", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{course.course_name}</span>}
            <Icon name="chevron-down" size={11} />
          </button>
          {st.menu === "course" && (
            <>
              <div onClick={() => set({ menu: null })} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
              <div role="listbox" aria-label="Courses" style={{ position: "absolute", left: 0, top: 50, zIndex: 31, width: 280, ...popover, borderRadius: 12, boxShadow: "0 14px 36px rgba(25,37,11,0.16)", padding: 6, display: "flex", flexDirection: "column", gap: 1 }}>
                {courses.map(o => {
                  const on = o.course_id === cid;
                  const n = assessFor(o.course_id).filter(e => daysTo(e.iso, today) >= 0).length;
                  return (
                    <button key={o.course_id} role="option" aria-selected={on} className={s.hoverOption} onClick={() => pickCourse(o.course_id)}
                      style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 10px", border: 0, borderRadius: 8, background: on ? "#F2F6EE" : "transparent", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
                      <span style={{ width: 9, height: 9, borderRadius: "50%", background: o.color || "#6F6857", flexShrink: 0 }} />
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "block", fontSize: 14, fontWeight: 700 }}>{o.course_code || o.course_name}</span>
                        <span style={{ display: "block", fontSize: 13, color: "#6F6857" }}>{o.course_name} · {n} upcoming</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>

        <div aria-label="Notifications" style={{ flex: 1, minWidth: 0, display: "flex", justifyContent: "flex-start", alignItems: "center", gap: 10 }}>
          {ai && (
            <div onMouseEnter={() => set({ aiOpen: true })} onMouseLeave={() => set({ aiOpen: false })} style={{ position: "relative" }}>
              <div role="button" tabIndex={0} aria-expanded={st.aiOpen} onFocus={() => set({ aiOpen: true })} onBlur={() => set({ aiOpen: false })}
                style={{ ...pillBase, background: "#F2F6EE", color: "#293C0E" }}>
                <span style={{ ...pillDot, color: "#445D22" }}><Icon name="clover" size={16} /></span>{ai.title}
              </div>
              {st.aiOpen && (
                <div style={{ position: "absolute", right: isMobile ? "auto" : 0, left: isMobile ? 0 : "auto", top: "100%", paddingTop: 8, zIndex: 31 }}>
                  <div role="tooltip" style={{ width: isMobile ? 300 : 400, ...popover, borderRadius: 16, boxShadow: "0 16px 40px rgba(25,37,11,0.16)", padding: "16px 18px", display: "flex", gap: 12 }}>
                    <span style={{ width: 34, height: 34, borderRadius: "50%", background: "#F2F6EE", color: "#445D22", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}><Icon name="clover" size={17} /></span>
                    <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <span style={{ fontSize: 16, fontWeight: 700, color: "#293C0E" }}>{ai.title}</span>
                      <span style={{ fontSize: 15, color: "#3F3B31", textWrap: "pretty" } as React.CSSProperties}>{ai.body}</span>
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
          {due && (() => {
            const n = daysTo(due.iso, today);
            const when = n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`;
            return (
              <button className={s.hoverDue} onClick={() => router.push("/calendar")} title={`Due ${when} · ${fmtDow(due.iso)}`}
                style={{ ...pillBase, background: "#FBF1DC", color: "#8A6420" }}>
                <span style={{ ...pillDot, color: "#8A6420" }}><Icon name="calendar" size={15} /></span>
                <span>{due.title} due {when}</span>
              </button>
            );
          })()}
        </div>

        <div style={{ position: "relative" }}>
          <button className={s.hoverIcon} onClick={() => set({ menu: st.menu === "bell" ? null : "bell" })} aria-label={`Upcoming deadlines, ${soon} this week`} aria-expanded={st.menu === "bell"} title="Upcoming deadlines"
            style={{ ...iconBtn, background: st.menu === "bell" ? "#F0ECE3" : "transparent" }}>
            <Icon name="nofitication" size={22} />
            {soon > 0 && (
              <span style={{ position: "absolute", top: 4, right: 3, minWidth: 18, height: 18, padding: "0 5px", boxSizing: "border-box", borderRadius: 9, background: "#C4534B", color: "#FFFFFF", fontSize: 11, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 0 2px #FAF8F3" }}>{soon}</span>
            )}
          </button>
          {st.menu === "bell" && (
            <>
              <div onClick={() => set({ menu: null })} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
              <div role="dialog" aria-label="Upcoming deadlines" style={{ position: "absolute", right: 0, top: 52, zIndex: 31, width: 380, maxWidth: "calc(100vw - 32px)", ...popover, padding: 8, display: "flex", flexDirection: "column" }}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "8px 10px 10px" }}>
                  <span style={{ fontFamily: SERIF, fontSize: 18, fontWeight: 600 }}>Upcoming Deadlines</span>
                  <span style={{ fontSize: 13, color: "#6F6857" }}>{course?.course_code || course?.course_name}</span>
                </div>
                {upcoming.length === 0 && <div style={{ padding: "4px 10px 12px", fontSize: 14, color: "#6F6857" }}>Nothing due for this course.</div>}
                {upcoming.map(e => {
                  const n = daysTo(e.iso, today);
                  return (
                    <button key={e.id} className={s.hoverOption} onClick={() => set(e.type === "Homework" ? { menu: null } : { menu: null, exam: e.id, topic: null, lvl: null })}
                      style={{ display: "flex", alignItems: "center", gap: 12, padding: 10, border: 0, borderRadius: 10, background: "transparent", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: TYPE_DOT[e.type], flexShrink: 0 }} />
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "block", fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.title}</span>
                        <span style={{ display: "block", fontSize: 13, color: "#6F6857" }}>{e.type} · {fmtDow(e.iso)}</span>
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 700, color: countFg(n), whiteSpace: "nowrap" }}>{countdown(n)}</span>
                    </button>
                  );
                })}
                <button onClick={openManage} style={{ marginTop: 4, padding: 10, border: 0, borderTop: "1px solid rgba(42,39,31,0.10)", borderRadius: "0 0 8px 8px", background: "transparent", color: "#445D22", ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>Manage Dates</button>
              </div>
            </>
          )}
        </div>
        <button className={s.hoverIcon} onClick={openManage} aria-label="Manage exams and deadlines" title="Add or change exams and deadlines" style={iconBtn}>
          <Icon name="setting" size={22} />
        </button>
      </header>

      {/* ── exam tabs + tools ── */}
      <div key={cid} className={`${s.areaTabs} ${s.paneEnter}`} style={{ display: "flex", alignItems: "center", gap: 20, borderBottom: "1px solid rgba(42,39,31,0.10)", minWidth: 0 }}>
        <div role="tablist" aria-label="Exams" style={{ flex: 1, minWidth: 0, alignSelf: "stretch", display: "flex", gap: 36, overflowX: "auto", overflowY: "hidden" }}>
          {exams.map(e => {
            const on = !!exam && e.id === exam.id;
            return (
              <button key={e.id} role="tab" aria-selected={on} className={on ? undefined : s.hoverTab} onClick={() => set({ exam: e.id, topic: null, hover: null, lvl: null })}
                style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 1, flexShrink: 0, padding: "4px 0 12px", border: 0, borderBottom: `3px solid ${on ? "#445D22" : "transparent"}`, background: "transparent", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
                <span style={{ fontSize: 17, fontWeight: 700, color: on ? "#1A1814" : "#6F6857", whiteSpace: "nowrap" }}>{e.title}</span>
                <span style={{ fontSize: 13, color: "#6F6857", whiteSpace: "nowrap" }}>{fmtDow(e.iso, today)}</span>
              </button>
            );
          })}
          {exams.length === 0 && (
            <button onClick={openManage} style={{ alignSelf: "center", padding: "0 0 10px", border: 0, background: "transparent", ...INHERIT_FONT, fontSize: 15, fontWeight: 700, color: "#445D22", cursor: "pointer" }}>+ Add Exam or Deadline</button>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0, paddingBottom: 10 }}>
          {TOOLS.map(tl => (
            <button key={tl.key} className={s.hoverTool} onClick={() => goTool(tl.key)}
              style={{ display: "inline-flex", alignItems: "center", gap: 10, height: 44, padding: "0 16px 0 6px", border: "1px solid rgba(42,39,31,0.14)", borderRadius: 12, background: "#FDFCF9", color: "#1A1814", ...INHERIT_FONT, fontSize: 15, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}>
              <span style={{ width: 32, height: 32, borderRadius: 9, background: tl.bg, color: tl.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><Glyph name={tl.icon} size={16} /></span>
              {tl.title}
            </button>
          ))}
        </div>
      </div>

      {/* ── readiness band ── */}
      <section aria-label="Readiness" key={`${cid}:${exam?.id ?? ""}`} className={`${s.areaReady} ${s.readyGrid} ${s.examEnter}`} style={{ padding: "24px 0", borderBottom: "1px solid rgba(42,39,31,0.10)" }}>
        {/* Top-anchored, not centred: the prerequisite warning below the legend
            appears and disappears with the selected concept, and centring made
            the readiness % jump ~35px whenever it did. */}
        <div style={{ position: "relative", alignSelf: "stretch", display: "flex", flexDirection: "column", justifyContent: "flex-start", gap: 22, minWidth: 0, paddingTop: 10 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 22 }}>
            <span data-testid="readiness-pct" style={{ fontFamily: SERIF, fontSize: 88, fontWeight: 600, lineHeight: 0.9, letterSpacing: "-0.03em" }}>{graph ? `${pct}%` : "–"}</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, paddingBottom: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700 }}>{exam ? `Ready for ${exam.title}` : `${course?.course_code || course?.course_name} Mastery`}</span>
              {trend !== 0 && (
                <span style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 15, color: "#3F3B31" }}>
                  <span style={{ height: 24, padding: "0 9px", borderRadius: 12, background: trend > 0 ? "#E1ECD7" : "#F6E3E1", color: trend > 0 ? "#49671D" : "#A8443F", fontSize: 13, fontWeight: 700, display: "inline-flex", alignItems: "center" }}>
                    {trend > 0 ? "+" : "−"}{Math.abs(trend)}% this week
                  </span>
                </span>
              )}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div role="img" aria-label={`Overall mastery ${pct} percent`} style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {squaresOrder(topics).map(t => (
                <button key={t.id} className={s.hoverSeg} onClick={() => set({ topic: sel && sel.id === t.id ? null : t.id })} title={`${t.name} · ${ST_LABEL[t.st]}`} aria-label={`${t.name} · ${ST_LABEL[t.st]}`}
                  style={{ width: 20, height: 20, flexShrink: 0, padding: 0, border: 0, borderRadius: 5, background: TC[t.st], opacity: st.lvl && t.st !== st.lvl ? 0.3 : 1, boxShadow: sel && sel.id === t.id ? "0 0 0 2px #FAF8F3, 0 0 0 3.5px #445D22" : "none", cursor: "pointer" }} />
              ))}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {STATUS_ORDER.map(k => {
                const on = st.lvl === k;
                return (
                  <button key={k} aria-pressed={on} className={on ? undefined : s.hoverLegend} onClick={() => set({ lvl: on ? null : k })} title="Highlight these on the roadmap"
                    style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 32, padding: "0 12px 0 10px", border: 0, borderRadius: 16, background: on ? "#E1ECD7" : "#F0ECE3", ...INHERIT_FONT, fontSize: 14, color: "#1A1814", cursor: "pointer" }}>
                    <span style={{ width: 11, height: 11, borderRadius: 3, background: TC[k] }} />
                    <span style={{ fontWeight: 700 }}>{topics.filter(t => t.st === k).length}</span>
                    <span style={{ color: "#3F3B31" }}>{ST_LABEL[k]}</span>
                  </button>
                );
              })}
            </div>
          </div>
          {/* In flow under the legend (the design pins it absolute at the
              column bottom, which covers the legend chips once a real course
              has more than one row of content). The slot RESERVES two lines,
              filled or empty, so picking a concept with or without a
              prerequisite gap doesn't shift the band for the ordinary case —
              but it is a minimum, not a cap: the sentence gets as many lines
              as it needs. It used to be a hard height with a two-line clamp,
              which on a narrow column (or with the side nav expanded) cut the
              warning off mid-word and left the reason hidden behind a
              tooltip. */}
          <div aria-hidden={!(warnLeft && focus) || undefined} style={{ marginTop: -8, minHeight: 61, flexShrink: 0 }}>
            {warnLeft && focus && (
              <div
                data-testid="focus-gap-warning"
                style={{ minHeight: 61, boxSizing: "border-box", display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 12, background: "#FBF1DC", fontSize: 14, lineHeight: 1.45, color: "#6B4E12" }}
              >
                <WarnIcon />
                <span style={{ textWrap: "pretty" } as React.CSSProperties}>
                  <strong style={{ fontWeight: 700 }}>{focus.name}</strong> · {focus.gap}
                </span>
              </div>
            )}
          </div>
        </div>

        {focus ? (
          <div data-testid="focus-card" style={{ position: "relative", borderRadius: 20, background: "var(--sidenav-bg)", color: "#FFFFFF", padding: "22px 26px", display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontFamily: MONO, fontSize: 12, letterSpacing: "0.14em", textTransform: "uppercase", color: "#E1ECD7" }}>{rec && focus.id === rec.id ? "Up Next" : focus.group}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <span style={{ position: "relative", width: 68, height: 68, flexShrink: 0 }}>
                <svg width="68" height="68" viewBox="0 0 68 68" aria-hidden="true" style={{ display: "block", transform: "rotate(-90deg)" }}>
                  <circle cx="34" cy="34" r="29" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="6" />
                  <circle cx="34" cy="34" r="29" fill="none" stroke={focusArc} strokeWidth="6" strokeLinecap="round" strokeDasharray={ring(focus.m, 29)} />
                </svg>
                <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17, fontWeight: 700 }}>{focus.m}%</span>
              </span>
              <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontFamily: SERIF, fontSize: 28, fontWeight: 600, lineHeight: 1.15, letterSpacing: "-0.01em" }}>{focus.name}</span>
                <div style={{ display: "flex", flexWrap: "nowrap", alignItems: "center", gap: 6, fontSize: 14, color: "rgba(255,255,255,0.86)" }}>
                  {focusPres.length === 0 && <span style={{ flexShrink: 0, whiteSpace: "nowrap" }}>No prerequisites</span>}
                  {focusPres.slice(0, kS).map(t => (
                    <span key={t.id} title={`${t.name} · ${ST_LABEL[t.st]}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 26, padding: "0 10px", borderRadius: 13, background: "rgba(255,255,255,0.12)", color: "#FFFFFF", fontSize: 13, fontWeight: 600, whiteSpace: "nowrap" }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: TC[t.st] }} />{t.name}
                    </span>
                  ))}
                  {restP.length > 0 && (
                    <span onMouseEnter={() => set({ moreOpen: true })} onMouseLeave={() => set({ moreOpen: false })} style={{ position: "relative", flexShrink: 0 }}>
                      <span tabIndex={0} onFocus={() => set({ moreOpen: true })} onBlur={() => set({ moreOpen: false })} style={{ display: "inline-flex", alignItems: "center", height: 26, padding: "0 10px", borderRadius: 13, background: "rgba(255,255,255,0.22)", color: "#FFFFFF", fontSize: 13, fontWeight: 700, whiteSpace: "nowrap", cursor: "default" }}>+{restP.length} more</span>
                      {st.moreOpen && (
                        <span style={{ position: "absolute", left: 0, top: "100%", paddingTop: 6, zIndex: 25 }}>
                          <span style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 200, padding: "10px 12px", ...popover, borderRadius: 12, boxShadow: "0 14px 36px rgba(25,37,11,0.16)" }}>
                            {restP.map(t => (
                              <span key={t.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 600, color: "#1A1814", whiteSpace: "nowrap" }}>
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
            {warnInCard ? (
              <div style={{ minHeight: 78, boxSizing: "border-box", display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 12, background: "#FBF1DC", fontSize: 14, lineHeight: 1.4, color: "#6B4E12" }}>
                <WarnIcon /><span style={{ textWrap: "pretty" } as React.CSSProperties}>{focus.gap}</span>
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", alignItems: "center", columnGap: 16, rowGap: 8, height: 78, boxSizing: "border-box", padding: "12px 14px", borderRadius: 12, background: "rgba(0,0,0,0.16)" }}>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: "block", fontFamily: MONO, fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: "#E1ECD7" }}>Last Quiz</span>
                  <span style={{ display: "block", fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{lq ? `${lq.concept_name || focus.name} Quiz` : "No quiz yet"}</span>
                </span>
                <span style={{ textAlign: "right" }}>
                  <span style={{ display: "block", fontSize: 22, fontWeight: 700, lineHeight: 1.1, color: quizColor }}>{lq ? `${lqp}%` : "–"}</span>
                  <span style={{ display: "block", fontSize: 13, color: "rgba(255,255,255,0.8)" }}>{lq ? `${lq.score}/${lq.total} correct · ${fmtWhen(lq.completed_at || lq.created_at, today)}` : "Take one to measure it"}</span>
                </span>
                <span style={{ gridColumn: "1 / 3", height: 6, borderRadius: 3, background: "rgba(255,255,255,0.16)", overflow: "hidden" }}>
                  <span style={{ display: "block", width: lq ? `${lqp}%` : "0%", height: "100%", borderRadius: 3, background: quizColor }} />
                </span>
              </div>
            )}
          </div>
        ) : (
          <div style={{ borderRadius: 20, background: "var(--sidenav-bg)", color: "#FFFFFF", padding: 26, display: "flex", flexDirection: "column", justifyContent: "center", gap: 6 }}>
            {topics.length ? (
              <>
                <span style={{ fontFamily: SERIF, fontSize: 26, fontWeight: 600 }}>Every concept is mastered</span>
                <span style={{ fontSize: 15, color: "rgba(255,255,255,0.86)" }}>Keep them fresh with a mixed quiz before the exam.</span>
              </>
            ) : (
              <>
                <span style={{ fontFamily: SERIF, fontSize: 26, fontWeight: 600 }}>{graph ? "No concepts yet" : "Loading concepts"}</span>
                <span style={{ fontSize: 15, color: "rgba(255,255,255,0.86)" }}>{graph ? "Upload course material in the Library to build this course's roadmap." : "One moment."}</span>
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
        style={{ position: "relative", zIndex: st.tileMenu ? 2 : undefined, padding: "22px 6px 28px 0" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16 }}>
          <span style={monoLabel}>Roadmap</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "26px 20px", alignItems: "start" }}>
          {/* Stacking: every column is its own stacking context (its colEnter
              opacity/transform animation), and so is any hovered (lifted) or
              dimmed tile. A z-index on the menu alone is therefore trapped
              and later tiles/columns paint over it, so the column AND the
              tile that own the open menu are lifted above their siblings. */}
          {columns.map((col, ci) => (
            <div key={col.key} className={s.colEnter}
              style={{ "--i": Math.min(ci, 6), position: "relative", zIndex: col.shown.some(x => x.t.id === st.tileMenu) ? 2 : undefined, display: "flex", flexDirection: "column", gap: 8, minWidth: 0 } as React.CSSProperties}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingBottom: 4 }}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
                  <span style={{ fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{col.label}</span>
                  <span style={{ fontSize: 13, color: "#6F6857", fontVariantNumeric: "tabular-nums" }}>{col.frac}</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(8, minmax(0, 1fr))", gap: "4px 3px" }}>
                  {col.bars.map((b, i) => <span key={i} className={s.bar} style={{ height: 4, borderRadius: 2, background: b }} />)}
                </div>
              </div>
              {col.shown.map(({ t, isSel, isNext, isHot, rel, dim }) => {
                const warn = !!t.gap && t.st !== "mastered" && !rel;
                const n = cardsFor(t.name);
                const actions = [
                  { label: "Quiz Me", icon: "bulb" as const, bg: "#EBDDEE", fg: "#7A4A78", href: quizHref([t.id]) },
                  { label: n ? `${n} Flashcards` : "Make Flashcards", icon: "cards" as const, bg: "#E1ECD7", fg: "#445D22", href: cardsHref([t.name]) },
                  { label: "Study Guide", icon: "file" as const, bg: "#F1E3C4", fg: "#8A6420", href: guideHref(t.name) },
                ];
                const menuOpen = st.tileMenu === t.id;
                return (
                  <div key={t.id} ref={menuOpen ? tileMenuOwner : undefined} role="button" tabIndex={0} aria-pressed={isSel} aria-haspopup="menu" aria-expanded={menuOpen} data-testid={`tile-${t.id}`} className={s.tile}
                    onClick={() => set({ topic: t.id, tileMenu: st.tileMenu === t.id ? null : t.id })}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); set({ topic: t.id, tileMenu: st.tileMenu === t.id ? null : t.id }); } }}
                    onMouseEnter={() => set({ hover: t.id })} onMouseLeave={() => set({ hover: null })}
                    style={{ position: "relative", zIndex: menuOpen ? 2 : undefined, display: "flex", alignItems: "center", gap: 12, padding: "10px 12px", borderRadius: 14, background: isSel ? "#F2F6EE" : "#FDFCF9", border: `1px solid ${isSel || isNext ? "#445D22" : "rgba(42,39,31,0.12)"}`, boxShadow: isSel ? "0 0 0 1px #445D22" : isNext ? "0 0 0 1px #445D22, 0 8px 20px rgba(68,93,34,0.16)" : isHot ? "0 6px 16px rgba(25,37,11,0.10)" : "none", opacity: dim ? 0.3 : 1, cursor: "pointer" }}>
                    <span style={{ position: "relative", width: 34, height: 34, flexShrink: 0 }}>
                      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true" style={{ display: "block", transform: "rotate(-90deg)" }}>
                        <circle cx="17" cy="17" r="14" fill="none" stroke="#E6E2D9" strokeWidth="3.5" />
                        <circle cx="17" cy="17" r="14" fill="none" stroke={TC[t.st]} strokeWidth="3.5" strokeLinecap="round" strokeDasharray={ring(t.m, 14)} />
                        <circle cx="17" cy="17" r="9.5" fill={t.st === "new" ? "transparent" : TC[t.st]} />
                      </svg>
                      <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#FFFFFF" }}>
                        {t.st === "mastered" && <Icon name="check" size={12} />}
                      </span>
                    </span>
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                      <span style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.25, textWrap: "pretty" } as React.CSSProperties}>{t.name}</span>
                      <span style={{ fontSize: 13, color: SC[t.st], whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.st === "new" ? "Not Started" : `${ST_LABEL[t.st]} · ${t.m}%`}</span>
                    </span>
                    {isNext && !isSel && <span style={{ position: "absolute", top: -10, right: 10, height: 20, padding: "0 8px", borderRadius: 10, background: "#445D22", color: "#FFFFFF", fontSize: 11, fontWeight: 700, display: "inline-flex", alignItems: "center", boxShadow: "0 0 0 2px #FAF8F3" }}>Next</span>}
                    {rel && <span style={{ position: "absolute", top: -10, right: 10, height: 20, padding: "0 8px", borderRadius: 10, background: rel === "Unlocks" ? "#E3ECF5" : "#F7EEDC", color: rel === "Unlocks" ? "#2E5F96" : "#7A5A1C", fontSize: 11, fontWeight: 700, display: "inline-flex", alignItems: "center", boxShadow: "0 0 0 2px #FAF8F3" }}>{rel}</span>}
                    {warn && <span title={t.gap} style={{ display: "block", lineHeight: 0, flexShrink: 0 }}><WarnIcon size={16} /></span>}
                    {menuOpen && (
                      <>
                        <div role="menu" aria-label={`${t.name} actions`} onClick={e => e.stopPropagation()}
                          // Enter/Space on an item must follow the link, not reach the tile's toggle.
                          onKeyDown={e => { if (e.key === "Enter" || e.key === " ") e.stopPropagation(); }}
                          style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 6px)", zIndex: 21, minWidth: 220, ...popover, borderRadius: 12, boxShadow: "0 14px 36px rgba(25,37,11,0.16)", padding: 6, display: "flex", flexDirection: "column", gap: 2, cursor: "default" }}>
                          {actions.map(ac => (
                            <Link key={ac.label} role="menuitem" href={ac.href} className={s.hoverOption} onClick={e => { e.stopPropagation(); set({ tileMenu: null }); }}
                              style={{ display: "flex", alignItems: "center", gap: 10, height: 40, padding: "0 8px", border: 0, borderRadius: 8, background: "transparent", ...INHERIT_FONT, fontSize: 14, fontWeight: 600, color: "#1A1814", textAlign: "left", textDecoration: "none", cursor: "pointer" }}>
                              <span style={{ width: 28, height: 28, borderRadius: 8, background: ac.bg, color: ac.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><Glyph name={ac.icon} size={14} /></span>
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
                  style={{ display: "flex", alignItems: "center", gap: 10, height: 40, padding: "0 12px", border: "1px dashed rgba(42,39,31,0.22)", borderRadius: 12, background: "transparent", ...INHERIT_FONT, fontSize: 14, fontWeight: 600, color: "#3F3B31", cursor: "pointer" }}>
                  <span style={{ display: "flex", gap: 3 }}>{col.hidden.map(x => <span key={x.t.id} style={{ width: 8, height: 8, borderRadius: 2, background: TC[x.t.st] }} />)}</span>
                  <span style={{ flex: 1, textAlign: "left", whiteSpace: "nowrap" }}>{col.open ? "Show Less" : `${col.hidden.length} more mastered`}</span>
                  <span style={{ display: "flex", flexShrink: 0, transform: col.open ? "rotate(180deg)" : "none" }}><Icon name="chevron-down" size={11} /></span>
                </button>
              )}
            </div>
          ))}
        </div>
        {graph && topics.length === 0 && <div style={{ fontSize: 14, color: "#6F6857" }}>Concepts from this course&apos;s knowledge graph will appear here.</div>}
      </section>

      {/* ── right column ── */}
      {/* The 40px side bleed (padding + negative margin, in the stylesheet so
          the narrow layout can drop it) gives the Quick Reviews pop-up's drop
          shadow room to fade out; it sits in the 56px column gap. */}
      <aside aria-label="Activity" className={s.areaRail} style={{ display: "flex", flexDirection: "column" }}>
        <section aria-label="Daily goal" style={{ display: "flex", flexDirection: "column", gap: 16, paddingBottom: 24 }}>
          <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 4 }}>
            <span style={monoLabel}>Daily Goal</span>
            <button aria-label="Edit daily goal" title="Edit daily goal" className={s.hoverIcon} onClick={() => { setGoalDraft(String(goal)); set({ goalOpen: !st.goalOpen }); }}
              style={{ width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", border: 0, borderRadius: 8, background: "transparent", color: "#6F6857", cursor: "pointer" }}>
              <Icon name="setting" size={16} />
            </button>
            {st.goalOpen && (
              <>
                <div onClick={() => set({ goalOpen: false })} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
                <div role="dialog" aria-label="Daily goal" style={{ position: "absolute", left: 0, top: 34, zIndex: 31, width: 260, ...popover, padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                  <label style={{ fontSize: 14, fontWeight: 700 }}>Minutes per day
                    <input type="number" min={5} max={600} value={goalDraft} onChange={e => setGoalDraft(e.target.value)} aria-label="Minutes per day"
                      style={{ display: "block", marginTop: 6, width: "100%", height: 40, padding: "0 10px", border: "1px solid rgba(42,39,31,0.16)", borderRadius: 9, background: "#FFFFFF", ...INHERIT_FONT, fontSize: 14, boxSizing: "border-box" }} />
                  </label>
                  <button onClick={saveGoal} style={{ height: 40, border: 0, borderRadius: 10, background: "#445D22", color: "#FFFFFF", ...INHERIT_FONT, fontSize: 15, fontWeight: 700, cursor: "pointer" }}>Save Goal</button>
                </div>
              </>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontFamily: SERIF, fontSize: 28, fontWeight: 600, lineHeight: 1 }}>{done}</span>
            <span style={{ fontFamily: SERIF, fontSize: 15, fontWeight: 600, color: "#1A1814" }}>of {goal} mins</span>
          </div>
          <div role="img" aria-label={`Goal met ${hit} of the last 6 days. Today ${done} of ${goal} minutes.`} style={{ position: "relative", display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 8, height: 96, alignItems: "end" }}>
            <span aria-hidden="true" style={{ position: "absolute", left: 0, right: 0, bottom: `${(goal / MAX) * 100}%`, borderTop: "1.5px dashed rgba(68,93,34,0.45)" }} />
            <span aria-hidden="true" style={{ position: "absolute", right: 0, bottom: `${(goal / MAX) * 100}%`, transform: "translateY(-4px)", fontFamily: MONO, fontSize: 11, color: "#6F6857", background: "#FAF8F3", paddingLeft: 4 }}>{goal} mins</span>
            {week.map((d, i) => {
              const isToday = i === week.length - 1;
              return (
                <span key={d.date} title={`${fmtDow(d.date).split(",")[0]}: ${d.minutes} min`} style={{ position: "relative", height: `${(Math.min(d.minutes, MAX) / MAX) * 100}%`, borderRadius: "6px 6px 3px 3px", overflow: "hidden" }}>
                  <span style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: "100%", background: isToday ? "#445D22" : d.minutes >= goal ? "#A1BC83" : "#E2DDD2" }} />
                </span>
              );
            })}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 8, marginTop: -8 }}>
            {week.map((d, i) => {
              const isToday = i === week.length - 1;
              return <span key={d.date} style={{ textAlign: "center", fontFamily: MONO, fontSize: 12, fontWeight: isToday ? 700 : 500, color: isToday ? "#1A1814" : "#6F6857" }}>{fmtDow(d.date).split(",")[0]}</span>;
            })}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              { label: "Quiz", min: todayRow?.quiz ?? 0, dot: "#7A4A78" },
              { label: "Flashcards", min: todayRow?.flashcards ?? 0, dot: "#597536" },
              { label: "Tutor", min: todayRow?.tutor ?? 0, dot: "#B8873F" },
            ].map(gp => (
              <div key={gp.label} style={{ display: "grid", gridTemplateColumns: "96px minmax(0, 1fr) 84px", alignItems: "center", gap: 12, fontSize: 14 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: gp.dot }} />{gp.label}</span>
                <span style={{ height: 6, borderRadius: 3, background: "#E6E2D9", overflow: "hidden" }}><span style={{ display: "block", width: `${Math.min(100, (gp.min / goal) * 100)}%`, height: "100%", borderRadius: 3, background: gp.dot }} /></span>
                <span style={{ textAlign: "right", color: "#3F3B31", fontVariantNumeric: "tabular-nums" }}>{gp.min} min</span>
              </div>
            ))}
          </div>

          {qr.length > 0 && (
            <div onMouseEnter={() => set({ qrOpen: true })} onMouseLeave={() => set({ qrOpen: false })} style={{ position: "relative" }}>
              <button className={s.hoverQr} onClick={() => router.push(cardsHref(qr.map(x => x.t.name)))} onFocus={() => set({ qrOpen: true })} onBlur={() => set({ qrOpen: false })} aria-expanded={st.qrOpen}
                style={{ width: "100%", display: "flex", alignItems: "center", gap: 12, height: 56, padding: "0 8px", border: "1px solid #C9DAEC", borderRadius: 14, background: "#E3ECF5", color: "#1E3F6B", ...INHERIT_FONT, textAlign: "left", cursor: "pointer", whiteSpace: "nowrap" }}>
                <span style={{ width: 40, height: 40, borderRadius: 10, background: "#2E5F96", color: "#FFFFFF", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}><CardsIcon size={18} /></span>
                {/* minWidth 0 lets the label give way (ellipsis) instead of
                    pushing the pill past the border at the rail's width; the
                    pill never shrinks, and its inset matches the tile's. */}
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", fontSize: 17, fontWeight: 700 }}>{qr.length} Quick {qr.length === 1 ? "Review" : "Reviews"}</span>
                <span style={{ flexShrink: 0, height: 38, padding: "0 12px", borderRadius: 10, background: "#2E5F96", color: "#FFFFFF", fontSize: 17, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>
                  {qr.length * 2} min
                  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </span>
              </button>
              {st.qrOpen && (
                <div style={{ position: "absolute", left: 0, right: 0, top: "100%", paddingTop: 8, zIndex: 31 }}>
                  <div role="dialog" aria-label="Quick reviews" style={{ width: "100%", boxSizing: "border-box", ...popover, borderRadius: 16, boxShadow: "0 16px 40px rgba(25,37,11,0.16)", padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
                    <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: 16, fontWeight: 700, color: "#23497A" }}>{qr.length} Quick {qr.length === 1 ? "Review" : "Reviews"}</span>
                      <span style={{ fontSize: 14, color: "#3F3B31" }}>{qr.length * 2} min · {exam ? `${qr.length} on ${exam.title}` : course?.course_code || course?.course_name}</span>
                    </span>
                    <span className={s.catScroll} style={{ display: "flex", flexDirection: "column", maxHeight: 200, overflowY: "auto", paddingRight: 4 }}>
                      {qr.map(x => (
                        <span key={x.t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid rgba(42,39,31,0.08)" }}>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: TC[x.t.st], flexShrink: 0 }} />
                          <span style={{ flex: 1, minWidth: 0, fontSize: 15, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{x.t.name}</span>
                          <span style={{ fontSize: 13, color: "#6F6857", whiteSpace: "nowrap" }}>{x.ago >= 7 ? `Last seen ${x.ago} days ago` : `Slipping · ${x.t.m}%`}</span>
                        </span>
                      ))}
                    </span>
                    <button className={s.hoverQrStart} onClick={() => { set({ qrOpen: false }); router.push(cardsHref(qr.map(x => x.t.name))); }}
                      style={{ height: 40, border: 0, borderRadius: 10, background: "#2E5F96", color: "#FFFFFF", ...INHERIT_FONT, fontSize: 15, fontWeight: 700, cursor: "pointer" }}>Start Review</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        <section aria-label="Recent activity" style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 22, borderTop: "1px solid rgba(42,39,31,0.10)" }}>
          <span style={{ ...monoLabel, marginBottom: 8 }}>Recent Activity</span>
          {recent.length === 0 && <span style={{ fontSize: 14, color: "#6F6857" }}>Quizzes, flashcards, and study guides for this course will show up here.</span>}
          {recent.map(rc => {
            const ic = rc.kind === "quiz" ? { bg: "#EBDDEE", fg: "#7A4A78", name: "bulb" as const } : rc.kind === "cards" ? { bg: "#E1ECD7", fg: "#445D22", name: "cards" as const } : { bg: "#F1E3C4", fg: "#8A6420", name: "file" as const };
            return (
              <div key={rc.key} style={{ display: "grid", gridTemplateColumns: "32px minmax(0, 1fr)", columnGap: 12, padding: "10px 0" }}>
                <span style={{ width: 32, height: 32, borderRadius: 9, background: ic.bg, color: ic.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><Glyph name={ic.name} size={15} /></span>
                <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: "block", fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{rc.title}</span>
                      <span style={{ display: "block", fontSize: 13, color: "#6F6857" }}>{rc.meta}</span>
                    </span>
                    {rc.result && <span style={{ fontSize: 15, fontWeight: 700, color: rc.resultColor, whiteSpace: "nowrap" }}>{rc.result}</span>}
                  </div>
                  {rc.chips.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {rc.chips.map(ch => (
                        <button key={ch.id} onClick={() => byId.has(ch.id) && set({ topic: ch.id })} title="Mastery change from this quiz"
                          style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 26, padding: "0 9px", border: 0, borderRadius: 13, background: ch.delta >= 0 ? "#E1ECD7" : "#F6E3E1", color: "#1A1814", ...INHERIT_FONT, fontSize: 13, whiteSpace: "nowrap", flexShrink: 0, cursor: "pointer" }}>
                          {ch.name}<span style={{ fontWeight: 700, color: ch.delta >= 0 ? "#49671D" : "#A8443F" }}>{ch.delta >= 0 ? "+" : "−"}{Math.abs(ch.delta)}%</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </section>
      </aside>

      {/* ── exams and deadlines modal ── */}
      {drafts && (
          <StudyModal open onClose={() => setDrafts(null)} label="Exams and deadlines" width={720} maxHeight={760} top={isMobile ? 40 : 120} gap={16}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontFamily: SERIF, fontSize: 26, fontWeight: 600 }}>Exams and Deadlines</span>
              <span style={{ fontSize: 14, color: "#6F6857" }}>{course?.course_code ? `${course.course_code} · ${course.course_name}` : course?.course_name}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "140px minmax(0, 1fr) 170px 40px", gap: 10, fontSize: 13, fontWeight: 600, color: "#6F6857" }}><span>Type</span><span>Name</span><span>Date</span><span /></div>
            {drafts.map((dr, i) => {
              const field: React.CSSProperties = { height: 40, padding: "0 10px", border: "1px solid rgba(42,39,31,0.16)", borderRadius: 9, background: "#FFFFFF", ...INHERIT_FONT, fontSize: 14, color: "#1A1814", boxSizing: "border-box", minWidth: 0 };
              return (
                <div key={dr.id} style={{ display: "grid", gridTemplateColumns: "140px minmax(0, 1fr) 170px 40px", gap: 10, alignItems: "center" }}>
                  <select value={dr.type} onChange={e => updDraft(i, { type: e.target.value as AssessType })} aria-label="Type" style={field}>
                    <option value="Exam">Exam</option><option value="Quiz">Quiz</option><option value="Homework">Homework</option>
                  </select>
                  <input value={dr.title} onChange={e => updDraft(i, { title: e.target.value })} placeholder="e.g. Midterm 3" aria-label="Name" style={field} />
                  <input type="date" value={dr.iso} onChange={e => e.target.value && updDraft(i, { iso: e.target.value })} aria-label="Date" style={field} />
                  <button className={s.hoverRemove} onClick={() => setDrafts(d => (d ? d.filter((_, j) => j !== i) : d))} aria-label="Remove" title="Remove"
                    style={{ width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", border: 0, borderRadius: 9, background: "transparent", color: "#A8443F", cursor: "pointer" }}>
                    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
                  </button>
                </div>
              );
            })}
            <button className={s.hoverAdd} onClick={() => {
              const d = new Date(today.getTime() + 7 * 86400000);
              const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
              setDrafts(ds => [...(ds || []), { id: `new-${Date.now()}-${(ds || []).length}`, type: "Exam", rawType: "exam", title: "", iso, isNew: true }]);
            }}
              style={{ alignSelf: "flex-start", height: 40, padding: "0 14px", border: "1.5px dashed rgba(68,93,34,0.4)", borderRadius: 10, background: "transparent", color: "#445D22", ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>+ Add Exam or Deadline</button>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, paddingTop: 6, borderTop: "1px solid rgba(42,39,31,0.10)" }}>
              <button onClick={() => setDrafts(null)} style={{ height: 44, padding: "0 18px", border: 0, borderRadius: 11, background: "transparent", color: "#3F3B31", ...INHERIT_FONT, fontSize: 15, cursor: "pointer" }}>Cancel</button>
              <button onClick={saveManage} disabled={saving} style={{ height: 44, padding: "0 22px", border: 0, borderRadius: 11, background: "#445D22", color: "#FFFFFF", ...INHERIT_FONT, fontSize: 15, fontWeight: 700, cursor: saving ? "wait" : "pointer", opacity: saving ? 0.7 : 1 }}>{saving ? "Saving" : "Save Dates"}</button>
            </div>
          </StudyModal>
      )}
    </div>
    </div>
  );
}
