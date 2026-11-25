"use client";
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { useScrollLock } from "@/lib/useScrollLock";
import { FilterPills } from "@/components/ui";
import { KnowledgeGraph } from "../graph/KnowledgeGraph";
import { useGraphSize } from "../graph/useGraphSize";
import { FullHeightScreen } from "../FullHeightScreen";
import { GraphPanelSkeleton } from "../Skeleton";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { getGraph, getCourses, getSessions, addGraphNode, deleteGraphNode, type EnrolledCourse, type Session } from "@/lib/api";
import { CoursesKey, courseProgressFor } from "../graph/CoursesKey";
import { useToast } from "../ToastProvider";
import { useConfirm, type ConfirmHandle } from "@/lib/useConfirm";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "@/lib/types";
import { useFlag } from "@/context/FlagsContext";
import { apiToGraphNode, type GraphNode, type GraphEdge } from "@/lib/data";
import { LEARNING_LOOP_FLAG } from "@/lib/learningLoopFlag";
import { listAttempts } from "@/lib/quiz/api";
import { relativeStudied } from "@/lib/quiz/relativeTime";
import type { AttemptSummary } from "@/lib/quiz/types";
import { treeNodeActions, type TreeNodeAction } from "@/lib/treeNodeActions";
import { motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import { deleteButtonStyle, highlightIdFor, selectedCourseIdOf } from "./treeHelpers";
import { AnimatedNumber } from "./AnimatedNumber";
import styles from "./Tree.module.css";

type Tier = "all" | "mastered" | "learning" | "struggling" | "unexplored";

/** One page of history is enough to find a single concept's attempts: the
 *  endpoint has no concept filter (gap G2), so the page is filtered client-side
 *  and 100 rows covers far more than the five we show. */
const ATTEMPT_HISTORY_LIMIT = 100;
/** Rows in the node panel's "Recent quizzes" block. */
const RECENT_QUIZ_ROWS = 5;

/** `p_delta` is a 0–1 fraction (`routes/quiz.py::attempt history`,
 *  `mastery_after - mastery_before`); the panel speaks in whole percent, the
 *  same unit as the Mastery tile above it. `null` is "the attempt recorded no
 *  move", not zero — say so with an em dash rather than inventing a number. */
function formatMasteryDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || Number.isNaN(delta)) return "—";
  const pct = Math.round(delta * 100);
  return `${pct < 0 ? "−" : "+"}${Math.abs(pct)}%`;
}

/** Completed attempts sort by when they FINISHED; `created_at` is the fallback
 *  for a row whose `completed_at` never landed. */
function attemptTime(a: AttemptSummary): number {
  const t = new Date(a.completed_at || a.created_at).getTime();
  return Number.isNaN(t) ? 0 : t;
}

const TIER_META: Record<Exclude<Tier, "all">, { label: string; color: string }> = {
  mastered: { label: "Mastered", color: "var(--state-mastery)" },
  learning: { label: "Learning", color: "var(--state-progress)" },
  struggling: { label: "Struggling", color: "var(--state-struggle)" },
  unexplored: { label: "Unexplored", color: "var(--state-neutral)" },
};

export function Tree() {
  const router = useRouter();
  const search = useSearchParams();
  const { userId, userReady } = useUser();
  const [activeSemester, , semesterHydrated] = useActiveSemester();
  const isMobile = useIsMobile();
  const suggest = search.get("suggest");
  // `?node=<id>` — the quiz's return path (#537 R-10). `?suggest=` is the older,
  // fuzzier twin (a concept NAME) and is untouched by this; they are written by
  // different callers and are not expected together.
  const focusNodeId = search.get("node");
  // `?course=<id>` — Library W8.1b handoff: centre the map on that course.
  const focusCourseId = search.get("course");

  const [courseFilter, setCourseFilter] = React.useState<string>("all");
  // The "My courses" key and the graph, wired together: hovering a course row
  // fades the other courses; hovering a concept lights its course's row;
  // clicking a row filters to that course (the same state as the dropdown).
  const [keyHoverCourse, setKeyHoverCourse] = React.useState<string | null>(null);
  const [graphHoverCourse, setGraphHoverCourse] = React.useState<string | null>(null);
  const [tier, setTier] = React.useState<Tier>("all");
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<GraphNode | null>(null);
  const [fullscreen, setFullscreen] = React.useState(false);

  // Measured before the first paint; the graph waits for it (`useGraphSize`).
  const [ref, size] = useGraphSize<HTMLDivElement>({ w: 900, h: 600 });

  const [nodes, setNodes] = React.useState<GraphNode[]>([]);
  const [edges, setEdges] = React.useState<GraphEdge[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [sessions, setSessions] = React.useState<Session[]>([]);
  const [loading, setLoading] = React.useState(true);

  // Quiz history for the node panel's "Recent quizzes" block. `null` = not
  // fetched yet (the block says "Loading…", never the lie "No quizzes yet");
  // the ref records which user the cached page belongs to.
  const [attempts, setAttempts] = React.useState<AttemptSummary[] | null>(null);
  const attemptsFor = React.useRef<string | null>(null);

  // Manual add-concept composer (#330) — only offered when a course is picked
  // in the key: "all" gives no course to attribute the new node to.
  const [addingConcept, setAddingConcept] = React.useState(false);
  const [newConceptName, setNewConceptName] = React.useState("");
  const [savingConcept, setSavingConcept] = React.useState(false);

  const toast = useToast();
  // W8.2: Cards + Guide join Teach/Quiz when the loop is on; hide_* still
  // suppress destinations the nav already gates.
  const loopOn = useFlag(LEARNING_LOOP_FLAG) === "on";
  const quizShown = useFlag("hide_quiz") !== "on";
  const studyShown = useFlag("hide_study") !== "on";

  const load = React.useCallback(async () => {
    if (!userId) return;
    try {
      const [graphRes, coursesRes, sessionsRes] = await Promise.all([
        getGraph(userId, activeSemester || undefined),
        getCourses(userId),
        getSessions(userId, 50).catch(() => ({ sessions: [] })),
      ]);
      const cs = coursesRes.courses || [];
      setCourses(cs);
      setNodes((graphRes.nodes || []).map((n: ApiNode) => apiToGraphNode(n, cs)));
      setEdges(
        (graphRes.edges || []).map((e: ApiEdge) => ({
          source: e.source as string,
          target: e.target as string,
          strength: e.strength,
          relationship_type: e.relationship_type,
        })),
      );
      setSessions(sessionsRes.sessions || []);
    } catch (err) {
      console.error("tree load failed", err);
    } finally {
      setLoading(false);
    }
  }, [userId, activeSemester]);

  const loadAttempts = React.useCallback(async () => {
    if (!userId) return;
    attemptsFor.current = userId;
    try {
      const page = await listAttempts(userId, { limit: ATTEMPT_HISTORY_LIMIT });
      setAttempts(page.attempts || []);
    } catch (err) {
      // History is decoration on a panel that already works; a failed read
      // must never blank the panel. Keep whatever we hold, and settle `null`
      // to `[]` so the block stops claiming it is still loading.
      console.error("tree attempt history load failed", err);
      setAttempts((prev) => prev ?? []);
    }
  }, [userId]);

  // Fetched LAZILY, on the first concept-node selection: a student who only
  // pans the graph never pays for a history page. Once per user for the
  // screen's lifetime — the panel opens and closes constantly.
  React.useEffect(() => {
    if (!userId || !selected || selected.is_subject_root) return;
    if (attemptsFor.current === userId) return;
    setAttempts(null);
    loadAttempts();
  }, [userId, selected, loadAttempts]);

  // A quiz submit announces itself (`lib/quiz/useQuizSession.ts`), which is the
  // one moment this page's history goes stale while it is on screen. Only
  // refresh a page we already hold; the lazy path above still owns the first
  // fetch.
  React.useEffect(() => {
    const onGraphChanged = () => {
      if (attemptsFor.current) loadAttempts();
    };
    window.addEventListener("sapling:graph-changed", onGraphChanged);
    return () => window.removeEventListener("sapling:graph-changed", onGraphChanged);
  }, [loadAttempts]);

  // Manual add-concept (#330): create-or-merge server-side (the backend
  // dedups case/whitespace-insensitively), then reload so the canonical row
  // and its anchor edge render from DB truth. The selected node anchors the
  // edge when it belongs to the chosen course; otherwise the course root
  // does, server-side.
  const submitAddConcept = async () => {
    const name = newConceptName.trim();
    if (!name || courseFilter === "all" || !userId || savingConcept) return;
    setSavingConcept(true);
    try {
      const res = await addGraphNode(userId, {
        concept_name: name,
        course_id: courseFilter,
        anchor_node_id: selected && selected.course_id === courseFilter ? selected.id : undefined,
      });
      toast.success(res.already_existed ? `Merged into your existing “${name}” node.` : `Added “${name}”.`);
      setNewConceptName("");
      setAddingConcept(false);
      await load();
    } catch {
      toast.error("Couldn't add the concept.");
    } finally {
      setSavingConcept(false);
    }
  };

  React.useEffect(() => {
    // Wait for the active-semester read from localStorage before the first load,
    // so returning users fetch scoped once instead of unscoped-then-scoped.
    if (userReady && userId && semesterHydrated) load();
  }, [userReady, userId, semesterHydrated, load]);

  // Auto-select node matching ?suggest= once data loads.
  React.useEffect(() => {
    if (!suggest || !nodes.length) return;
    const target = nodes.find(n => n.name.toLowerCase() === suggest.toLowerCase());
    if (target) setSelected(target);
  }, [suggest, nodes]);

  // `?node=<id>` focus (#537 §6): select that node exactly as a tap would, so
  // the detail panel opens on desktop and the bottom sheet slides up on mobile
  // off the same `selected` state. That IS the whole focus gesture — neither
  // graph renderer exposes a camera, only `highlightId` (a paint), so there is
  // nothing here to centre on. An unknown id is ignored in silence: a student
  // returning from a quiz on a concept they have since deleted should land on
  // an ordinary tree, not an error.
  // Applied once per param VALUE, unlike `?suggest=`: a graph reload (add or
  // delete a concept) rebuilds `nodes`, and re-opening a panel the student
  // deliberately closed would be a haunting.
  const focusApplied = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!focusNodeId || !nodes.length) return;
    if (focusApplied.current === focusNodeId) return;
    const target = nodes.find(n => n.id === focusNodeId);
    if (!target) return;
    focusApplied.current = focusNodeId;
    setSelected(target);
  }, [focusNodeId, nodes]);

  useScrollLock(fullscreen);

  React.useEffect(() => {
    if (!fullscreen) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    document.addEventListener("keydown", h);
    return () => {
      document.removeEventListener("keydown", h);
    };
  }, [fullscreen]);

  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter((c) => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );

  const courseProgress = React.useMemo(
    () => courseProgressFor(scopedCourses, nodes),
    [scopedCourses, nodes],
  );
  // Picking a course in the key centres the graph on it and fades the other
  // courses behind it (they stay on the map); picking it again zooms back out.
  const [zoomRequest, setZoomRequest] = React.useState<{ courseId: string | null; seq: number } | null>(null);
  const pickCourse = (courseId: string) => {
    const next = courseFilter === courseId ? "all" : courseId;
    setCourseFilter(next);
    setZoomRequest((r) => ({ courseId: next === "all" ? null : next, seq: (r?.seq ?? 0) + 1 }));
    setAddingConcept(false);
    setNewConceptName("");
  };

  // `?course=<id>` focus (W8.1b): same once-per-value rule as `?node=`. An
  // unknown / unenrolled id is ignored so a stale Library link still lands on
  // an ordinary tree. Applied after courses load — the key only needs enrollments.
  const courseFocusApplied = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!focusCourseId || !courses.length) return;
    if (courseFocusApplied.current === focusCourseId) return;
    if (!courses.some((c) => c.course_id === focusCourseId)) return;
    courseFocusApplied.current = focusCourseId;
    setCourseFilter(focusCourseId);
    setZoomRequest((r) => ({ courseId: focusCourseId, seq: (r?.seq ?? 0) + 1 }));
  }, [focusCourseId, courses]);

  const filteredNodes = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return nodes.filter(n => {
      if (tier !== "all" && !n.is_subject_root && n.mastery_tier !== tier) return false;
      if (q && !n.name.toLowerCase().includes(q) && !n.subject.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [nodes, tier, query]);

  const filteredEdges = React.useMemo(() => {
    const ids = new Set(filteredNodes.map(n => n.id));
    return edges.filter(e => ids.has(typeof e.source === "string" ? e.source : "") && ids.has(typeof e.target === "string" ? e.target : ""));
  }, [edges, filteredNodes]);


  const sessionsForSelected = React.useMemo(() => {
    if (!selected) return [];
    const name = selected.name.toLowerCase();
    return sessions.filter(s => (s.topic || "").toLowerCase() === name);
  }, [selected, sessions]);

  // `GET /api/quiz/attempts` is user-scoped and unfiltered (gaps G2/G3), so the
  // concept and the completed-status filter both happen here. Subject roots
  // have no attempts of their own — a course is never a `concept_node_id`.
  const recentQuizzes = React.useMemo(() => {
    if (!attempts || !selected || selected.is_subject_root) return [];
    return attempts
      .filter(a => a.concept_node_id === selected.id && a.status === "completed")
      .sort((a, b) => attemptTime(b) - attemptTime(a))
      .slice(0, RECENT_QUIZ_ROWS);
  }, [attempts, selected]);

  const suggestId = React.useMemo(() => {
    if (!suggest) return undefined;
    const n = nodes.find(x => x.name.toLowerCase() === suggest.toLowerCase());
    return n?.id;
  }, [suggest, nodes]);

  const nodeActions = React.useMemo(
    () => (selected
      ? treeNodeActions(selected, { loopOn, quizShown, studyShown })
      : []),
    [selected, loopOn, quizShown, studyShown],
  );

  const del = useConfirm(async () => {
    if (!userId || !selected) return;
    try {
      await deleteGraphNode(userId, selected.id);
      toast.success(`Deleted "${selected.name}".`);
      setSelected(null);
      await load();
    } catch (err: any) {
      toast.error(`Delete failed: ${String(err?.message || err)}`);
    }
  });

  const detailPanel = selected && (
    <NodeDetailPanel
      node={selected}
      del={del}
      attempts={attempts}
      recentQuizzes={recentQuizzes}
      sessions={sessionsForSelected}
      actions={nodeActions}
      onClose={() => setSelected(null)}
      onAction={(href) => router.push(href)}
      onOpenSession={(id) => router.push(`/learn?resume=${encodeURIComponent(id)}`)}
    />
  );

  const selectedCourseId = selectedCourseIdOf(courseFilter);
  const highlightId = highlightIdFor(suggestId, selected);

  return (
    <FullHeightScreen className={styles.root}>
      <TopBar
        title="Your Knowledge Tree"
        subtitle="The living map of what you've learned, organized by course."
      />

      {/* One toolbar. Left: search, course, and Add concept (it needs a single
          course). Right: the mastery-status pills, kept as pills because their
          colours double as the graph's legend. Course is a dropdown so the row
          never wraps however many courses a student has. */}
      <div data-testid="tree-toolbar" className={styles.toolbar}>
        <div className={styles.search}>
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search concepts…"
            aria-label="Search concepts"
            className={`${styles.field} ${styles.searchInput}`}
          />
          <span className={styles.searchIcon}>
            <Icon name="search" size={12} />
          </span>
        </div>
        {courseFilter !== "all" && (
          <AddConceptControl
            adding={addingConcept}
            name={newConceptName}
            saving={savingConcept}
            onNameChange={setNewConceptName}
            onSubmit={submitAddConcept}
            onOpen={() => setAddingConcept(true)}
            onCancel={() => { setAddingConcept(false); setNewConceptName(""); }}
          />
        )}
        {/* Right side: the mastery-status filter (its colours are the legend). */}
        <div className={styles.pillsSlot}>
          <FilterPills
            options={[
              { value: "all" as Tier, label: "All" },
              ...(Object.keys(TIER_META) as Array<Exclude<Tier, "all">>).map((t) => ({
                value: t as Tier,
                label: TIER_META[t].label,
                color: TIER_META[t].color,
              })),
            ]}
            value={tier}
            onChange={setTier}
          />
        </div>
      </div>


      {/* The graph row absorbs whatever `<main>` has left after the TopBar and
          the filter row. `flex: 1` + `minHeight: 0` rather than a viewport
          subtraction: this row's child is the ResizeObserver target whose
          contentRect becomes <KnowledgeGraph width height>, so a hardcoded
          `calc(100vh - …)` mis-sized the CANVAS in whichever shell layout the
          constant wasn't calibrated for (#341). */}
      <div className={styles.graphRow}>
        <div ref={ref} className={styles.graphArea}>
          {loading || !size ? (
            <GraphPanelSkeleton />
          ) : (
            <>
              <KnowledgeGraph
                nodes={filteredNodes}
                edges={filteredEdges}
                width={size.w}
                height={size.h}
                highlightId={highlightId}
                onNodeClick={(n) => setSelected(n)}
                zoomControlsTop={FULLSCREEN_BTN.top + FULLSCREEN_BTN.h + 6}
                legible
                focusCourseId={keyHoverCourse ?? selectedCourseId}
                onHoverCourse={setGraphHoverCourse}
                zoomRequest={zoomRequest}
              />
              {/* The course key picks the Tree's course: click one to centre it
                  (others fade behind) and add concepts to it; again for all. */}
              {scopedCourses.length > 0 && (
                <CoursesKey
                  courseProgress={courseProgress}
                  placement="top-left"
                  testIdPrefix="tree"
                  rowTestId={(id) => `graph-course-filter-${id}`}
                  activeCourseId={keyHoverCourse ?? graphHoverCourse}
                  selectedCourseId={selectedCourseId}
                  onHoverCourse={setKeyHoverCourse}
                  onSelectCourse={pickCourse}
                  selectHint="Click to center this course, again to zoom out"
                />
              )}
              {/* The graph's own top-right corner: a Fullscreen icon the
                  width of the zoom stack, which sits directly below it. */}
              <button
                type="button"
                data-testid="graph-fullscreen"
                aria-label="Fullscreen"
                title="Fullscreen"
                onClick={() => setFullscreen(true)}
                className={`btn btn--ghost btn--sm ${styles.fullscreenBtn}`}
                style={FULLSCREEN_BTN_VARS}
              >
                <Icon name="max" size={13} />
              </button>
            </>
          )}
        </div>
        {selected && !isMobile && (
          // Keyed by the concept: picking another node fades its panel in
          // afresh rather than swapping the content in place.
          <aside key={selected.id} className={`fade-in ${styles.aside}`}>
            {detailPanel}
          </aside>
        )}
      </div>

      {selected && isMobile && (
        <div
          onClick={() => setSelected(null)}
          className={`fade-in ${styles.scrim}`}
        >
          <div
            onClick={e => e.stopPropagation()}
            className={`slide-up ${styles.sheet}`}
          >
            {detailPanel}
          </div>
        </div>
      )}

      {fullscreen && (
        <div className={`fade-in ${styles.fullscreen}`}>
          <div className={styles.fullscreenHead}>
            <div>
              <div className="label-micro">Knowledge tree — fullscreen</div>
              <div className={`h-serif ${styles.fullscreenTitle}`}>Press Esc to exit</div>
            </div>
            <button className="btn btn--ghost btn--sm" onClick={() => setFullscreen(false)}>
              <Icon name="x" size={14} />
            </button>
          </div>
          <FullscreenGraph
            nodes={filteredNodes}
            edges={filteredEdges}
            highlightId={highlightId}
            onNodeClick={(n) => { setSelected(n); setFullscreen(false); }}
          />
        </div>
      )}
    </FullHeightScreen>
  );
}

/** The toolbar's manual add-concept composer (#330): an opener button, or the
 *  name input + Add once open. Enter submits, Escape cancels. */
function AddConceptControl({
  adding, name, saving, onNameChange, onSubmit, onOpen, onCancel,
}: {
  adding: boolean;
  name: string;
  saving: boolean;
  onNameChange: (name: string) => void;
  onSubmit: () => void;
  onOpen: () => void;
  onCancel: () => void;
}) {
  return adding ? (
    <span className={`fade-in ${styles.addConcept}`}>
      <input
        data-testid="graph-add-concept-input"
        autoFocus
        value={name}
        placeholder="Concept name"
        onChange={(e) => onNameChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmit();
          if (e.key === "Escape") onCancel();
        }}
        className={`${styles.field} ${styles.addInput}`}
      />
      <button
        data-testid="graph-add-concept-submit"
        className="btn btn--sm btn--primary"
        disabled={!name.trim() || saving}
        onClick={onSubmit}
      >
        Add
      </button>
    </span>
  ) : (
    <button
      data-testid="graph-add-concept"
      className="btn btn--sm"
      onClick={onOpen}
    >
      ＋ Add concept
    </button>
  );
}

/** The selected node's detail panel: the desktop `<aside>` and the mobile
 *  bottom sheet render the same content. */
const ACTION_ICON: Record<TreeNodeAction["key"], string> = {
  teach: "brain",
  quiz: "bolt",
  cards: "book",
  guide: "doc",
};

function NodeDetailPanel({
  node, del, attempts, recentQuizzes, sessions, actions, onClose, onAction, onOpenSession,
}: {
  node: GraphNode;
  del: ConfirmHandle;
  attempts: AttemptSummary[] | null;
  recentQuizzes: AttemptSummary[];
  sessions: Session[];
  actions: TreeNodeAction[];
  onClose: () => void;
  onAction: (href: string) => void;
  onOpenSession: (sessionId: string) => void;
}) {
  const m = useMotionPresets();
  return (
    <>
      {/* Course on the left, close in the top-right corner. */}
      <div className={styles.panelHead}>
        <div className={styles.panelCourse}>
          <span className={styles.dot} style={nodeColorVar(node.color)} />
          <span className={`label-micro ${styles.ellipsis}`}>
            {node.subject}
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="Close detail panel"
          className={`btn btn--ghost btn--sm ${styles.close}`}
        >
          <Icon name="x" size={14} />
        </button>
      </div>
      <h2 className={`h-serif ${styles.nodeTitle}`}>
        {node.name}
      </h2>
      <div className={styles.tiles}>
        <div className={`card ${styles.tile}`}>
          <div className="label-micro">Mastery</div>
          <div className={`mono ${styles.mastery}`} style={nodeColorVar(node.color)}>
            <AnimatedNumber value={Math.round((node.mastery_score || 0) * 100)} format={formatPct} />
          </div>
        </div>
        <div className={`card ${styles.tile}`}>
          <div className="label-micro">Tier</div>
          <div className={styles.tier}>
            {node.mastery_tier}
          </div>
        </div>
      </div>
      <div className={styles.lastStudied}>
        <div className={`label-micro ${styles.lastStudiedLabel}`}>Last studied</div>
        <div className={styles.lastStudiedValue}>
          {node.last_studied_at ? new Date(node.last_studied_at).toLocaleString() : "never"}
        </div>
      </div>
      {/* W8.2: one action menu — Teach / Quiz (+ Cards / Guide when the loop is on). */}
      <nav
        aria-label={`Study ${node.name}`}
        data-testid="tree-node-actions"
        className={styles.actions}
        data-cols={actions.length > 2 ? 2 : 1}
      >
        {actions.map(ac => (
          <button
            key={ac.key}
            type="button"
            className={`${ac.primary ? "btn btn--primary" : "btn"} ${styles.actionBtn}`}
            data-testid={`tree-node-action-${ac.key}`}
            onClick={() => onAction(ac.href)}
          >
            <Icon name={ACTION_ICON[ac.key]} size={14} /> {ac.label}
          </button>
        ))}
      </nav>
      {!node.is_subject_root && (
        <button
          onClick={del.trigger}
          className="btn"
          style={deleteButtonStyle(del.armed)}
        >
          <Icon name="x" size={13} /> {del.armed ? "Click again to confirm" : "Delete concept"}
        </button>
      )}
      {!node.is_subject_root && (
        <RecentQuizzes attempts={attempts} recentQuizzes={recentQuizzes} />
      )}
      {sessions.length > 0 && (
        <div className={styles.section}>
          <div className={`label-micro ${styles.sectionLabel}`}>Sessions for this concept</div>
          <motion.div variants={m.list.container} initial="hidden" animate="shown">
            {sessions.slice(0, 4).map(s => (
              <motion.button
                key={s.id}
                variants={m.list.item}
                onClick={() => onOpenSession(s.id)}
                className={`${styles.row} ${styles.sessionBtn}`}
              >
                <div className={styles.sessionText}>
                  <div className={styles.sessionMode}>{s.mode}</div>
                  <div className={styles.sessionMeta}>
                    {s.message_count} msgs · {new Date(s.started_at).toLocaleDateString()}
                  </div>
                </div>
                <Icon name="chev" size={12} />
              </motion.button>
            ))}
          </motion.div>
        </div>
      )}
    </>
  );
}

/** The concept's colour as a custom property (its dot and Mastery figure). */
function nodeColorVar(color: string | null | undefined): React.CSSProperties | undefined {
  return color ? ({ "--node-color": color } as React.CSSProperties) : undefined;
}

const formatPct = (v: number) => `${Math.round(v)}%`;

/** The node panel's "Recent quizzes" block. `attempts === null` is "not
 *  fetched yet", never "none". */
function RecentQuizzes({
  attempts, recentQuizzes,
}: {
  attempts: AttemptSummary[] | null;
  recentQuizzes: AttemptSummary[];
}) {
  const m = useMotionPresets();
  return (
    <div data-testid="tree-node-recent-quizzes" className={styles.section}>
      <div className={`label-micro ${styles.sectionLabel}`}>Recent quizzes</div>
      {attempts === null ? (
        <div className={styles.note}>Loading…</div>
      ) : recentQuizzes.length === 0 ? (
        // No second CTA here on purpose: the Quiz action is a few pixels up
        // and is the action this empty state would ask for.
        <div className={styles.note}>No quizzes yet</div>
      ) : (
        // The history arrives after the panel opens ("Loading…" first), so
        // its rows stagger in.
        <motion.div variants={m.list.container} initial="hidden" animate="shown">
        {recentQuizzes.map(a => (
          <motion.div
            key={a.quiz_id}
            variants={m.list.item}
            data-testid={`tree-node-recent-quiz-${a.quiz_id}`}
            className={`${styles.row} ${styles.quizRow}`}
          >
            {/* Not a link: there is no finished-attempt review endpoint —
                `GET /attempts/{id}` answers `resumable: false, questions: []`
                for a completed row (gap G5). A row that navigated nowhere
                would be a broken promise. */}
            <span className={styles.quizWhen}>
              {relativeStudied(a.completed_at || a.created_at)}
            </span>
            <span className={`mono ${styles.quizScore}`}>
              {a.score ?? "—"}/{a.total ?? "—"} · {formatMasteryDelta(a.p_delta)} mastery
            </span>
          </motion.div>
        ))}
        </motion.div>
      )}
    </div>
  );
}

function FullscreenGraph({
  nodes, edges, highlightId, onNodeClick,
}: {
  nodes: GraphNode[]; edges: GraphEdge[];
  highlightId?: string;
  onNodeClick: (n: GraphNode) => void;
}) {
  const [ref, size] = useGraphSize<HTMLDivElement>({ w: 1200, h: 700 });
  return (
    <div ref={ref} className={styles.fullscreenGraph}>
      {size && (
        <KnowledgeGraph
          nodes={nodes}
          edges={edges}
          width={size.w}
          height={size.h}
          highlightId={highlightId}
          onNodeClick={onNodeClick}
          legible
        />
      )}
    </div>
  );
}

/** The graph-corner Fullscreen icon: as wide as the 2D zoom stack (36px:
 *  4px padding + 26px buttons + 1px borders) so the two read as one column. */
const FULLSCREEN_BTN = { top: 12, w: 36, h: 32 };
/** FULLSCREEN_BTN for Tree.module.css's .fullscreenBtn (unitless px). */
const FULLSCREEN_BTN_VARS = {
  "--btn-top": FULLSCREEN_BTN.top,
  "--btn-w": FULLSCREEN_BTN.w,
  "--btn-h": FULLSCREEN_BTN.h,
} as React.CSSProperties;

