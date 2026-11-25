"use client";
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { useScrollLock } from "@/lib/useScrollLock";
import { MiniStat } from "../MiniStat";
import { KnowledgeGraph } from "../graph/KnowledgeGraph";
import { useGraphSize } from "../graph/useGraphSize";
import { CoursesKey, courseProgressFor, type CourseProgressEntry } from "../graph/CoursesKey";
import { ManageCoursesModal } from "../ManageCoursesModal";
import { DashboardSkeleton } from "../Skeleton";
import { useFlag } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import { retentionHref } from "@/context/RetentionDueContext";
import { useRetentionNavDue } from "../useRetentionNav";
import { useIsMobile } from "@/lib/useIsMobile";
import { useLayoutPref } from "@/lib/useLayoutPref";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { useLatestRequest } from "@/lib/useLatestRequest";
import {
  getGraph,
  getCourses,
  getUpcomingAssignments,
  getSessions,
  fetchActivity,
  fetchGamificationMe,
  type EnrolledCourse,
  type Session,
  type Assignment,
} from "@/lib/api";
import { LEARNING_LOOP_FLAG } from "@/lib/learningLoopFlag";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "@/lib/types";
import { apiToGraphNode, learnHrefForNode, type GraphNode, type GraphEdge } from "@/lib/data";
import { IS_TEST_MODE, now } from "@/lib/testMode";
import { buildQuizHref } from "@/lib/quiz/source";
import { DashboardActions, TodayColumn } from "../dashboard/TodayColumn";
import { LearnNextCard, type Recommendation } from "../dashboard/LearnNextCard";
import { fetchLearnNext, type LearnNext } from "../dashboard/learnNext";
import {
  activeDaysFrom,
  assignmentUrgency,
  statsFromGraph,
  streakMarkState,
  type DashboardStats,
} from "../dashboard/dashboardModel";
import { StreakMark, getWeekDays } from "../dashboard/StreakMark";
import { AnimatedNumber } from "./AnimatedNumber";
import styles from "./Dashboard.module.css";

/** An assignment known to have a due date (gradebook/Gradescope items may not). */
type DatedAssignment = Assignment & { due_date: string };
const hasDueDate = (a: Assignment): a is DatedAssignment => !!a.due_date;

// The typewriter greeting's rhythm (the pre-revamp hero's, below). Its own
// clock, not a transition: one character per tick, a blinking caret, and a
// short settle before the caret goes and the quote fades in.
const TYPE_TICK_MS = 55;
const CARET_BLINK_MS = 530;
const TYPE_SETTLE_MS = 300;

const QUOTES = [
  "Learning is the only thing the mind never exhausts, never fears, and never regrets. — da Vinci",
  "The roots of education are bitter, but the fruit is sweet. — Aristotle",
  "Live as if you were to die tomorrow. Learn as if you were to live forever. — Gandhi",
  "An investment in knowledge pays the best interest. — Franklin",
  "The beautiful thing about learning is that no one can take it away from you. — B.B. King",
  "Tell me and I forget. Teach me and I remember. Involve me and I learn. — Franklin",
];

function apiToGraphEdge(e: ApiEdge): GraphEdge {
  return {
    source: e.source as string,
    target: e.target as string,
    strength: e.strength,
    relationship_type: e.relationship_type,
  };
}

function getGreetingPrefix(d: Date) {
  const h = d.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

// Pre-revamp typing animation (main@929658f:app/dashboard/page.tsx:257-284):
//  - Types one char every 55ms.
//  - Thin forest-green vertical bar '|' cursor, weight 200, blinks 530ms.
//  - When the text finishes typing, wait 300ms then hide the cursor
//    entirely (no perpetual blinking).
//  - Exposes an onDone callback so the parent can fade the quote in once
//    the greeting settles.
function Typewriter({
  text,
  speed = TYPE_TICK_MS,
  onDone,
}: {
  text: string;
  speed?: number;
  onDone?: () => void;
}) {
  const [shown, setShown] = React.useState("");
  const [done, setDone] = React.useState(false);
  const [cursorOn, setCursorOn] = React.useState(true);

  // Keep onDone in a ref so the typing effect only restarts when text
  // or speed changes — not on every parent re-render.
  const onDoneRef = React.useRef(onDone);
  React.useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  React.useEffect(() => {
    setShown("");
    setDone(false);
    setCursorOn(true);
    let i = 0;
    let settleTimer: ReturnType<typeof setTimeout> | null = null;
    const iv = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(iv);
        settleTimer = setTimeout(() => {
          setDone(true);
          onDoneRef.current?.();
        }, TYPE_SETTLE_MS);
      }
    }, speed);
    return () => {
      clearInterval(iv);
      if (settleTimer) clearTimeout(settleTimer);
    };
  }, [text, speed]);

  React.useEffect(() => {
    if (done) { setCursorOn(false); return; }
    const blink = setInterval(() => setCursorOn((v) => !v), CARET_BLINK_MS);
    return () => clearInterval(blink);
  }, [done]);

  return (
    <span>
      {shown}
      <span aria-hidden className={styles.cursor} data-on={!done && cursorOn}>
        |
      </span>
    </span>
  );
}

type Navigate = (href: string) => void;

function fetchDashboard(userId: string, activeSemester: string, useLearnerNext: boolean) {
  // Empty `activeSemester` means "All semesters" — the DEFAULT — so the
  // fetch goes out unscoped. Scoping is opt-in: it only applies once the
  // user picks a term in the Courses & Semesters hub (nothing auto-resolves
  // a default term; an auto-picked term hides cross-term data — vetoed by
  // the e2e lane, #360).
  return Promise.all([
    getGraph(userId, activeSemester || undefined),
    getCourses(userId),
    getUpcomingAssignments(userId),
    getSessions(userId, 10),
    fetchLearnNext(userId, activeSemester, useLearnerNext),
  ]);
}

type DashboardFetch = Awaited<ReturnType<typeof fetchDashboard>>;

type DashboardSetters = {
  setCourses: (v: EnrolledCourse[]) => void;
  setNodes: (v: GraphNode[]) => void;
  setEdges: (v: GraphEdge[]) => void;
  setStats: (v: DashboardStats) => void;
  setAssignments: (v: DatedAssignment[]) => void;
  setSessions: (v: Session[]) => void;
  setLearnNext: (v: LearnNext) => void;
  setActiveDays: (v: Set<string>) => void;
};

/** Writes one load's replies into state, in the order load() always has. */
function applyDashboardResult(
  [graphRes, coursesRes, assignsRes, sessionsRes, learnNext]: DashboardFetch,
  set: DashboardSetters,
) {
  const cs = coursesRes.courses || [];
  set.setCourses(cs);
  const rawNodes: ApiNode[] = graphRes.nodes || [];
  const gNodes: GraphNode[] = rawNodes.map((n) => apiToGraphNode(n, cs));
  set.setNodes(gNodes);
  set.setEdges((graphRes.edges || []).map(apiToGraphEdge));
  set.setStats(statsFromGraph(graphRes.stats));
  // /upcoming already filters due_date >= today; drop undated rows here too
  // so the urgency chips can never compute from new Date(null) (1970).
  set.setAssignments((assignsRes.assignments || []).filter(hasDueDate));
  set.setSessions(sessionsRes.sessions || []);
  set.setLearnNext(learnNext);
  set.setActiveDays(activeDaysFrom(gNodes));
}

/** Everything the dashboard loads: the graph, courses, upcoming work,
 *  sessions and recommendations (load), plus the streak extras. */
function useDashboardData({
  userId, userReady, activeSemester, semesterHydrated,
}: {
  userId: string | null | undefined;
  userReady: boolean;
  activeSemester: string;
  semesterHydrated: boolean;
}) {
  // Same sibling gate as Study Hub Focus / GET /api/study/{id}/next (W8.3).
  // Both hooks run on every render: the flags load async, so a
  // short-circuited second call would change the hook order once they land.
  const loopFlag = useFlag(LEARNING_LOOP_FLAG);
  const planFlag = useFlag("quiz_concept_plan");
  const useLearnerNext = loopFlag === "on" && planFlag === "on";
  const [nodes, setNodes] = React.useState<GraphNode[]>([]);
  const [edges, setEdges] = React.useState<GraphEdge[]>([]);
  const [stats, setStats] = React.useState<DashboardStats>({
    streak: 0, mastered: 0, total: 0, learning: 0, struggling: 0, unexplored: 0,
  });
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [sessions, setSessions] = React.useState<Session[]>([]);
  const [assignments, setAssignments] = React.useState<DatedAssignment[]>([]);
  // Learn-next and the Today plan's quiz item read this one answer (W8.6).
  const [learnNext, setLearnNext] = React.useState<LearnNext>({ recommendations: [], next: null });
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [activeDays, setActiveDays] = React.useState<Set<string>>(new Set());
  // Days with XP this week (gamification /activity) and the longest streak
  // (/me). XP and the streak are written by the same post-commit hook, so an
  // XP day is a streak day. Best-effort: the column falls back to session and
  // concept dates when these don't load.
  const [xpDays, setXpDays] = React.useState<Set<string>>(new Set());
  const [bestStreak, setBestStreak] = React.useState<number | null>(null);
  // Bumped by every load() so the streak extras refresh with the rest of the
  // dashboard (Retry, a semester switch, a course change), not just on mount.
  const [extrasKey, setExtrasKey] = React.useState(0);

  // Latest load wins (#769): a semester switch mid-flight, or a Retry /
  // course change racing the first load, must not let the OLDER reply
  // repaint the screen (or its finally clear the newer load's skeleton).
  const loadReq = useLatestRequest();
  const load = React.useCallback(async () => {
    if (!userId) return;
    const run = loadReq.begin();
    setExtrasKey((k) => k + 1);
    setLoading(true);
    setLoadError(null);
    try {
      const res = await fetchDashboard(userId, activeSemester, useLearnerNext);
      if (!run.isCurrent()) return;
      applyDashboardResult(res, {
        setCourses, setNodes, setEdges, setStats, setAssignments, setSessions, setLearnNext, setActiveDays,
      });
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("dashboard load failed", err);
      setLoadError(String(err));
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
  }, [userId, activeSemester, loadReq, useLearnerNext]);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    (async () => {
      try {
        const [activity, me] = await Promise.all([
          fetchActivity(userId).catch(() => null),
          fetchGamificationMe(userId).catch(() => null),
        ]);
        if (cancelled) return;
        setXpDays(new Set((activity?.week ?? []).filter((d) => d.xp > 0).map((d) => d.date)));
        setBestStreak(me ? me.longest_streak : null);
      } catch {
        /* streak extras are decoration; the dashboard renders without them */
      }
    })();
    return () => { cancelled = true; };
  }, [userReady, userId, extrasKey]);

  React.useEffect(() => {
    // Wait for the active-semester read from localStorage before the first load,
    // so returning users fetch scoped once instead of unscoped-then-scoped.
    if (userReady && userId && semesterHydrated) load();
  }, [userReady, userId, semesterHydrated, load]);

  return {
    nodes, edges, stats, courses, sessions, assignments,
    recommendations: learnNext.recommendations, learnerNext: learnNext.next,
    loading, loadError, activeDays, xpDays, bestStreak, load,
  };
}

/** The "My courses" key and the graph, wired together: hovering a course row
 *  fades the other courses; hovering a concept lights its course's row;
 *  clicking a row zooms the graph to that course, clicking it again zooms
 *  back out. */
function useCourseFocus() {
  const [keyHoverCourse, setKeyHoverCourse] = React.useState<string | null>(null);
  const [graphHoverCourse, setGraphHoverCourse] = React.useState<string | null>(null);
  const [zoomRequest, setZoomRequest] = React.useState<{ courseId: string | null; seq: number } | null>(null);
  const zoomedCourse = zoomRequest?.courseId ?? null;
  const zoomToCourse = (courseId: string) =>
    setZoomRequest((r) => ({ courseId: r?.courseId === courseId ? null : courseId, seq: (r?.seq ?? 0) + 1 }));
  return {
    keyHoverCourse, setKeyHoverCourse, graphHoverCourse, setGraphHoverCourse,
    zoomRequest, zoomedCourse, zoomToCourse,
  };
}

type CourseFocus = ReturnType<typeof useCourseFocus>;

/** The hero greeting: "<time-of-day>, <first name>" once both are known. */
function useGreeting(userName: string | null | undefined) {
  const firstName = userName ? userName.split(" ")[0] : "";
  const [greetingPrefix, setGreetingPrefix] = React.useState<string>("Welcome back");
  React.useEffect(() => {
    setGreetingPrefix(getGreetingPrefix(new Date(now())));
  }, []);
  const greetingText = firstName ? `${greetingPrefix}, ${firstName}` : "Welcome back";
  // WHICH greeting finished typing (#769), not a one-way latch: the text
  // changes after mount (the name and the time-of-day prefix arrive late),
  // the Typewriter restarts, and the quote must hide again until the NEW
  // text settles.
  const [greetingDoneFor, setGreetingDoneFor] = React.useState<string | null>(null);
  const greetingDone = greetingDoneFor === greetingText;
  return { greetingText, greetingDone, setGreetingDoneFor };
}

export function Dashboard() {
  const router = useRouter();
  const search = useSearchParams();
  const { userId, userName, userReady } = useUser();
  // Spec §13 A126: a delayed retention check is open (the shell's one read);
  // never while hide_study hides Study, the page the card sends the student to
  const { due: retentionDue, courseIds: retentionCourseIds } = useRetentionNavDue();
  const [activeSemester, , semesterHydrated] = useActiveSemester();
  const isMobile = useIsMobile();
  const [layoutPref] = useLayoutPref();
  // Top-nav layout keeps the pre-revamp 3-column dashboard with the
  // streak widget, Learn-next recommendations, and My Courses as a
  // proper panel on the left. Sidebar layout uses the new 2-column
  // design with the CoursesKey overlay inside the graph panel.
  const useLegacyPanels = layoutPref === "topnav";

  const [coursesOpen, setCoursesOpen] = React.useState(false);
  const [fullscreen, setFullscreen] = React.useState(false);
  const focus = useCourseFocus();
  const [mobileTab, setMobileTab] = React.useState<"courses" | "stats">("courses");

  // The graph container is flex-filled, so its size is known only once it
  // is laid out: measured as it mounts, before the first paint, and the
  // graph waits for it rather than opening at a guess and re-laying itself
  // out a frame later. 720 × 420 stands in only where nothing can be
  // measured (a test DOM).
  const [gRefCb, size] = useGraphSize<HTMLDivElement>({ w: 720, h: 420 });

  const suggest = search.get("suggest");
  const [suggestDismissed, setSuggestDismissed] = React.useState(false);
  React.useEffect(() => { setSuggestDismissed(false); }, [suggest]);

  // Client-only to avoid SSR/CSR hydration mismatch on the greeting and the
  // random quote (server's timezone/RNG result would drift from the client's).
  const [quote, setQuote] = React.useState<string>(QUOTES[0]);
  const [today, setToday] = React.useState<Date>(() => {
    const d = new Date(0); d.setHours(0, 0, 0, 0); return d;
  });
  React.useEffect(() => {
    // Test mode freezes the quote to index 0 and the clock to the fixed
    // test instant so the hero copy is byte-stable across loads.
    setQuote(IS_TEST_MODE ? QUOTES[0] : QUOTES[Math.floor(Math.random() * QUOTES.length)]);
    const t = new Date(now()); t.setHours(0, 0, 0, 0); setToday(t);
  }, []);
  const weekDays = React.useMemo(() => getWeekDays(today), [today]);

  const {
    nodes, edges, stats, courses, sessions, assignments, recommendations, learnerNext,
    loading, loadError, activeDays, xpDays, bestStreak, load,
  } = useDashboardData({ userId, userReady, activeSemester, semesterHydrated });

  useScrollLock(fullscreen);

  React.useEffect(() => {
    if (!fullscreen) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    document.addEventListener("keydown", h);
    return () => {
      document.removeEventListener("keydown", h);
    };
  }, [fullscreen]);

  const { greetingText, greetingDone, setGreetingDoneFor } = useGreeting(userName);
  // Greeting + quote render as a centered hero below the TopBar (see
  // return JSX), not as TopBar title/subtitle. Leaving the TopBar lean
  // makes the Dashboard feel like an arrival page, not a tool page.

  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter((c) => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );

  const courseProgress = React.useMemo(
    () => courseProgressFor(scopedCourses, nodes),
    [scopedCourses, nodes],
  );

  const suggestNode = React.useMemo(() => {
    if (!suggest) return null;
    return nodes.find(n => n.name.toLowerCase() === suggest.toLowerCase()) || null;
  }, [suggest, nodes]);

  const dismissSuggest = () => {
    setSuggestDismissed(true);
    const next = new URLSearchParams(search.toString());
    next.delete("suggest");
    const qs = next.toString();
    router.replace(qs ? `/dashboard?${qs}` : "/dashboard");
  };

  if (loading && !courses.length) {
    return (
      <div className={styles.root}>
        <DashboardSkeleton />
      </div>
    );
  }

  if (loadError && !courses.length) {
    return (
      <div>
        <TopBar title="Couldn't load dashboard" />
        <div className={styles.error}>
          <div className={styles.errorText}>{loadError}</div>
          <button className="btn btn--primary" onClick={load}>Retry</button>
        </div>
      </div>
    );
  }

  const navigate: Navigate = (href) => router.push(href);
  const highlightId = suggestNode?.id;

  const graphPanel = (
    <div className={styles.graphPanel}>
      {renderGraphCard({
        stats,
        nodes,
        scopedCourses,
        useLegacyPanels,
        focus,
        onFullscreen: () => setFullscreen(true),
        // The callback ref stays in this JSX (React may not see it handed to
        // a render-time call); the layers inside are a plain render call.
        graphArea: (
          // The card grows with its content, so the graph's own height counts:
          // at least 420, as it has always opened (the pre-measurement guess
          // used to hold the card at that height).
          <div ref={gRefCb} className={styles.graphArea}>
            {size && renderGraphLayers({
              nodes,
              edges,
              courseProgress,
              useLegacyPanels,
              focus,
              size,
              highlightId,
              onNodeClick: (n) => router.push(learnHrefForNode(n)),
            })}
          </div>
        ),
      })}
    </div>
  );

  const relTime = (iso: string | null | undefined) => {
    if (!iso) return "—";
    const diff = now() - new Date(iso).getTime();
    const mins = Math.round(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    if (days === 1) return "yesterday";
    if (days < 7) return `${days}d ago`;
    return new Date(iso).toLocaleDateString();
  };

  const courseNameFor = (id: string | null) => {
    if (!id) return null;
    const c = courses.find((co) => co.course_id === id);
    return c?.course_code || c?.course_name || null;
  };

  const rightPanel = (
    <TodayColumn
      sessions={sessions}
      nodes={nodes}
      learnerNext={learnerNext}
      assignments={assignments}
      hasCourses={courses.length > 0}
      stats={stats}
      bestStreak={bestStreak}
      xpDays={xpDays}
      today={today}
      weekDays={weekDays}
      nowMs={now()}
      courseLabel={(id) => courseNameFor(id ?? null)}
      relTime={relTime}
      navigate={navigate}
      openCourses={() => setCoursesOpen(true)}
      courseRows={
        courseProgress.length > 0
          ? courseProgress.map((entry) => <CourseProgressRow key={entry.course.course_id} entry={entry} spaced={false} />)
          : undefined
      }
    />
  );

  // The panels below are plain render calls, not components: React must see
  // the same element tree (the same <div>s in the same slots) the inline JSX
  // always produced, so a layout flip or a mobile tab switch patches nodes in
  // place instead of remounting them (the graph, the typing greeting).
  const heroBlock = renderHeroBlock({
    centered: useLegacyPanels && !isMobile,
    isMobile,
    greetingText,
    greetingDone,
    onGreetingDone: () => setGreetingDoneFor(greetingText),
    quote,
  });

  const suggestBlock = suggestDismissed ? null : renderSuggestCard({ node: suggestNode, navigate, onDismiss: dismissSuggest });
  const retentionBlock = renderRetentionCard({ due: retentionDue, courseIds: retentionCourseIds, navigate });

  const mainColumn = (
    <div className={styles.mainColumn}>
      {heroBlock}
      {renderMobileMetaRow({ isMobile, navigate })}
      {retentionBlock}
      {suggestBlock}
      {graphPanel}
    </div>
  );

  return (
    <div className={styles.root}>
      {isMobile && useLegacyPanels && renderMobileTabs({ mobileTab, setMobileTab })}

      {useLegacyPanels ? (
        renderLegacyGrid({
          isMobile,
          mobileTab,
          mainColumn,
          coursesPanel: renderLegacyCoursesPanel({
            hasCourses: courses.length > 0,
            courseProgress,
            assignments,
            onOpenCourses: () => setCoursesOpen(true),
            navigate,
          }),
          rightPanel: renderLegacyRightPanel({
            isMobile,
            stats,
            weekDays,
            today,
            activeDays,
            recommendations,
            navigate,
          }),
        })
      ) : isMobile ? (
        <div className={styles.mobileStack}>
          {mainColumn}
          {rightPanel}
        </div>
      ) : (
        // Desktop sidebar layout: the greeting and the actions share one header
        // row, so the graph and the right column start on the same line and
        // stretch to the same bottom edge.
        <div className={styles.desktop}>
          <div className={styles.desktopHeader}>
            <div className={styles.minW0}>{heroBlock}</div>
            {/* Bottom-aligned with the quote: both sides of the header end on
                one line, the same distance above the cards. */}
            <div className={styles.headerActions}>
              <DashboardActions navigate={navigate} />
            </div>
          </div>
          {retentionBlock}
          {suggestBlock}
          <div className={styles.desktopGrid}>
            {graphPanel}
            {rightPanel}
          </div>
        </div>
      )}


      {fullscreen && renderFullscreenOverlay({
        nodes,
        edges,
        highlightId,
        onClose: () => setFullscreen(false),
        onNodeClick: (n) => {
          setFullscreen(false);
          router.push(learnHrefForNode(n));
        },
      })}

      <ManageCoursesModal
        open={coursesOpen}
        userId={userId}
        courses={courses}
        onClose={() => setCoursesOpen(false)}
        onChanged={load}
      />
    </div>
  );
}

function renderGraphCard({
  stats, nodes, scopedCourses, useLegacyPanels, focus, onFullscreen, graphArea,
}: {
  stats: DashboardStats;
  nodes: GraphNode[];
  scopedCourses: EnrolledCourse[];
  useLegacyPanels: boolean;
  focus: CourseFocus;
  onFullscreen: () => void;
  /** The measured graph container (carries the ResizeObserver ref). */
  graphArea: React.ReactNode;
}) {
  const { keyHoverCourse, setKeyHoverCourse, graphHoverCourse, zoomedCourse, zoomToCourse } = focus;
  const conceptCount = stats.total || nodes.filter((n) => !n.is_subject_root).length;
  return (
    // Flex-column so the inner gRef can flex: 1 and fill whatever
    // height the grid row decides (courses + upcoming stacked on the
    // left determines the row height via align-items: stretch).
    <div className={`card ${styles.graphCard}`}>
      <div className={styles.graphCardHead}>
        <div>
          <div className="label-micro">Your knowledge map</div>
          <div className={`h-serif ${styles.graphTitle}`}>
            {`${conceptCount} ${conceptCount === 1 ? "concept" : "concepts"} across ${scopedCourses.length} ${scopedCourses.length === 1 ? "course" : "courses"}`}
          </div>
        </div>
        <div className={styles.chips}>
          {useLegacyPanels && scopedCourses.slice(0, 5).map((c) => {
            const lit = (keyHoverCourse ?? graphHoverCourse ?? zoomedCourse) === c.course_id;
            return (
              <button
                key={c.course_id}
                type="button"
                data-testid="dashboard-graph-course-chip"
                data-course-id={c.course_id}
                title={zoomedCourse === c.course_id ? "Click to zoom back out" : "Click to zoom to this course"}
                aria-pressed={zoomedCourse === c.course_id}
                onPointerEnter={() => setKeyHoverCourse(c.course_id)}
                onPointerLeave={() => setKeyHoverCourse(null)}
                onFocus={() => setKeyHoverCourse(c.course_id)}
                onBlur={() => setKeyHoverCourse(null)}
                onClick={() => zoomToCourse(c.course_id)}
                className={styles.chip}
                data-lit={lit}
              >
                <span className={styles.dot} style={dotColor(c.color)} />
                {c.course_code || c.course_name}
              </button>
            );
          })}
          <button
            className="btn btn--ghost btn--sm"
            onClick={onFullscreen}
            aria-label="Fullscreen graph"
          >
            <Icon name="max" size={12} />
          </button>
        </div>
      </div>
      {graphArea}
    </div>
  );
}

function renderGraphLayers({
  nodes, edges, courseProgress, useLegacyPanels, focus, size, highlightId, onNodeClick,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  courseProgress: CourseProgressEntry[];
  useLegacyPanels: boolean;
  focus: CourseFocus;
  size: { w: number; h: number };
  highlightId: string | undefined;
  onNodeClick: (n: GraphNode) => void;
}) {
  const {
    keyHoverCourse, setKeyHoverCourse, graphHoverCourse, setGraphHoverCourse,
    zoomRequest, zoomedCourse, zoomToCourse,
  } = focus;
  return (
    <>
      <KnowledgeGraph
        legible
        nodes={nodes}
        edges={edges}
        width={size.w}
        height={size.h}
        highlightId={highlightId}
        onNodeClick={onNodeClick}
        focusCourseId={keyHoverCourse ?? zoomedCourse}
        onHoverCourse={setGraphHoverCourse}
        zoomRequest={zoomRequest}
      />
      {/* Courses key — sidebar layout only. Top-nav layout uses the
          full My Courses panel in the left column instead. */}
      {!useLegacyPanels && (
        <CoursesKey
          courseProgress={courseProgress}
          activeCourseId={keyHoverCourse ?? graphHoverCourse}
          onHoverCourse={setKeyHoverCourse}
          selectedCourseId={zoomedCourse}
          onSelectCourse={zoomToCourse}
          selectHint="Click to zoom to this course, again to zoom out"
        />
      )}
    </>
  );
}

function renderHeroBlock({
  centered, isMobile, greetingText, greetingDone, onGreetingDone, quote,
}: {
  /** Legacy (top-nav) desktop centres the hero. */
  centered: boolean;
  isMobile: boolean;
  greetingText: string;
  greetingDone: boolean;
  onGreetingDone: () => void;
  quote: string;
}) {
  return (
    <div className={styles.hero} data-centered={centered} data-mobile={isMobile}>
      <h1 className={`h-serif ${styles.heroTitle}`}>
        <Typewriter text={greetingText} onDone={onGreetingDone} />
      </h1>
      {quote && (
        <p
          aria-hidden={!greetingDone}
          className={`body-serif ${styles.quote}`}
          data-shown={greetingDone}
        >
          "{quote}"
        </p>
      )}
    </div>
  );
}

function renderMobileMetaRow({ isMobile, navigate }: { isMobile: boolean; navigate: Navigate }) {
  if (!isMobile) return null;
  return (
    <div className={styles.metaRow}>
      <div className={styles.metaActions}>
        <button
          className={`btn btn--sm btn--primary ${styles.startBtn}`}
          onClick={() => navigate("/learn")}
        >
          <Icon name="sparkle" size={13} /> Start learning
        </button>
      </div>
    </div>
  );
}

function renderSuggestCard({
  node, navigate, onDismiss,
}: {
  node: GraphNode | null;
  navigate: Navigate;
  onDismiss: () => void;
}) {
  if (!node) return null;
  return (
    <div className={`card fade-in ${styles.nudge}`}>
      <Icon name="sparkle" size={16} />
      <div className={styles.nudgeText}>
        <strong>Try this next:</strong> {node.name}
        {node.subject && <span className={styles.dim}> · {node.subject}</span>}
      </div>
      <button
        className="btn btn--sm btn--primary"
        onClick={() => navigate(
          buildQuizHref(
            { concept: node.id },
            { kind: "dashboard", returnTo: "/dashboard" },
          ),
        )}
      >
        Start quiz
      </button>
      <button className="btn btn--sm btn--ghost" onClick={onDismiss}>Dismiss</button>
    </div>
  );
}

/** Spec §13 A126: a nudge, never the check itself — opening one commits its
 *  pose, so only the student's click on Study does that. */
function renderRetentionCard({ due, courseIds, navigate }: { due: boolean; courseIds: string[]; navigate: Navigate }) {
  if (!due) return null;
  return (
    <div
      data-testid="dashboard-retention-due"
      role="status"
      className={`card fade-in ${styles.nudge} ${styles.nudgeWrap}`}
    >
      <Icon name="bell" size={16} />
      <div className={`${styles.nudgeText} ${styles.nudgeTextMin}`}>
        <strong>A retention check is due.</strong> A few questions on what you studied a while ago, with no hints.
      </div>
      <button
        className="btn btn--sm btn--primary"
        data-testid="dashboard-retention-open"
        onClick={() => navigate(retentionHref(courseIds))}
      >
        Check what you remember
      </button>
    </div>
  );
}

function renderMobileTabs({
  mobileTab, setMobileTab,
}: {
  mobileTab: "courses" | "stats";
  setMobileTab: (t: "courses" | "stats") => void;
}) {
  return (
    <div className={styles.mobileTabs}>
      {(["courses", "stats"] as const).map(t => (
        <button
          key={t}
          onClick={() => setMobileTab(t)}
          className={styles.mobileTab}
          data-active={mobileTab === t}
        >
          {t === "courses" ? "My Courses" : "Stats & More"}
        </button>
      ))}
    </div>
  );
}

// ── Legacy (top-nav) layout panels ──────────────────────────────────────
// Pre-revamp 3-column dashboard: My Courses + Upcoming on the left,
// hero + graph in the middle, streak widget + MiniStat + Learn next
// on the right. Only rendered when layoutPref === "topnav".
function renderLegacyGrid({
  isMobile, mobileTab, mainColumn, coursesPanel, rightPanel,
}: {
  isMobile: boolean;
  mobileTab: "courses" | "stats";
  mainColumn: React.ReactNode;
  coursesPanel: React.ReactNode;
  rightPanel: React.ReactNode;
}) {
  return (
    <div className={styles.legacyGrid} data-mobile={isMobile}>
      {isMobile ? (
        mobileTab === "courses" ? (
          <>
            {mainColumn}
            {coursesPanel}
          </>
        ) : (
          <>
            {mainColumn}
            {rightPanel}
          </>
        )
      ) : (
        <>
          {coursesPanel}
          {mainColumn}
          {rightPanel}
        </>
      )}
    </div>
  );
}

function renderLegacyCoursesPanel({
  hasCourses, courseProgress, assignments, onOpenCourses, navigate,
}: {
  hasCourses: boolean;
  courseProgress: CourseProgressEntry[];
  assignments: DatedAssignment[];
  onOpenCourses: () => void;
  navigate: Navigate;
}) {
  return (
    <div className={styles.panelColumn}>
      <div className={`card ${styles.legacyCard}`}>
        <div className={styles.legacyCardHead}>
          <div className="label-micro">My courses</div>
          <button className="btn btn--ghost btn--sm" onClick={onOpenCourses}>
            <Icon name="cog" size={12} /> Courses & Semesters
          </button>
        </div>
        {!hasCourses ? (
          <div className={styles.empty}>No enrolled courses yet.</div>
        ) : courseProgress.length === 0 ? (
          <div className={styles.empty}>
            Nothing enrolled this semester.
          </div>
        ) : null}
        {courseProgress.map((entry) => (
          <CourseProgressRow key={entry.course.course_id} entry={entry} />
        ))}
      </div>

      <div className={`card ${styles.legacyCard}`}>
        <div className={styles.legacyCardHead}>
          <div className="label-micro">Upcoming</div>
          <button className="btn btn--ghost btn--sm" onClick={() => navigate("/calendar")}>Calendar →</button>
        </div>
        {assignments.length === 0 && (
          <div className={styles.empty}>No upcoming assignments.</div>
        )}
        {assignments.slice(0, 4).map((a) => {
          const { chipClass, label } = assignmentUrgency(a.due_date, now());
          return (
            <div key={a.id} className={styles.assignment}>
              <div className={styles.assignmentBody}>
                <div className={styles.assignmentTitle}>{a.title}</div>
                <div className={styles.assignmentMeta}>
                  {a.course_name || "—"} · {a.assignment_type || "task"}
                </div>
              </div>
              <span className={`chip ${chipClass}`}>{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function renderLegacyRightPanel({
  isMobile, stats, weekDays, today, activeDays, recommendations, navigate,
}: {
  isMobile: boolean;
  stats: DashboardStats;
  weekDays: Date[];
  today: Date;
  activeDays: Set<string>;
  recommendations: Recommendation[];
  navigate: Navigate;
}) {
  return (
    <div className={styles.panelColumn}>
      {!isMobile && (
        <div className={styles.legacyActions}>
          <button
            className={`btn btn--sm btn--primary ${styles.startBtn}`}
            onClick={() => navigate("/learn")}
          >
            <Icon name="sparkle" size={13} /> Start learning
          </button>
        </div>
      )}
      <div className={`card ${styles.legacyCard}`}>
        <div className={`label-micro ${styles.weekLabel}`}>This week</div>
        <div className={`body-serif ${styles.weekLine}`}>
          {stats.streak > 0 ? (
            <>You&apos;re on a <span className={`h-serif ${styles.streakDays}`}>{stats.streak}-day</span> streak.</>
          ) : (
            <>Ready when you are. Open any session to begin a streak.</>
          )}
        </div>
        <div className={styles.weekGrid}>
          {weekDays.map(d => {
            const key = d.toISOString().slice(0, 10);
            return (
              <div key={key} className={styles.weekDay}>
                <div className={`label-micro ${styles.weekDayLabel}`}>
                  {d.toLocaleDateString("en-US", { weekday: "short" }).slice(0, 2)}
                </div>
                <div className={styles.weekMark}>
                  <StreakMark state={streakMarkState(d, today, activeDays)} day={d.getDate()} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className={`card ${styles.statsCard}`}>
        <MiniStat
          label="Mastered"
          value={<AnimatedNumber value={stats.mastered} />}
          sub={stats.total ? `of ${stats.total} concepts` : undefined}
        />
        <MiniStat
          label="Learning"
          value={<AnimatedNumber value={stats.learning + stats.struggling} />}
          sub={`${stats.unexplored} unexplored`}
        />
      </div>

      <LearnNextCard recommendations={recommendations} navigate={navigate} />
    </div>
  );
}

function renderFullscreenOverlay({
  nodes, edges, highlightId, onClose, onNodeClick,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlightId: string | undefined;
  onClose: () => void;
  onNodeClick: (n: GraphNode) => void;
}) {
  return (
    <div className={`fade-in ${styles.fullscreen}`}>
      <div className={styles.fullscreenHead}>
        <div>
          <div className="label-micro">Knowledge map — fullscreen</div>
          <div className={`h-serif ${styles.fullscreenTitle}`}>Press Esc to exit</div>
        </div>
        <button className="btn btn--ghost btn--sm" onClick={onClose}>
          <Icon name="x" size={14} />
        </button>
      </div>
      <FullscreenGraph
        nodes={nodes}
        edges={edges}
        highlightId={highlightId}
        onNodeClick={onNodeClick}
      />
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
          legible
          nodes={nodes}
          edges={edges}
          width={size.w}
          height={size.h}
          highlightId={highlightId}
          onNodeClick={onNodeClick}
        />
      )}
    </div>
  );
}


/** A course's colour as the dot's custom property (the dot falls back to
 *  --accent when the course has none). */
function dotColor(color: string | null | undefined): React.CSSProperties | undefined {
  return color ? ({ "--dot-color": color } as React.CSSProperties) : undefined;
}

// One "My courses" line: colour dot, course code, mastery percentage and the
// four-segment mastery bar. The percentage counts and the segments slide when
// a reload moves the course's mix.
function CourseProgressRow({
  entry,
  spaced = true,
}: {
  entry: CourseProgressEntry;
  /** Space below the row. false when the parent spaces its rows itself. */
  spaced?: boolean;
}) {
  const { course, mastered, learning, struggling, unexplored, total, progress } = entry;
  const pct = Math.round(progress * 100);
  const baseColor = course.color || "var(--accent)";
  const segments = [
    { key: "mastered",   count: mastered,   color: baseColor, opacity: 1,    label: "Mastered" },
    { key: "learning",   count: learning,   color: baseColor, opacity: 0.78, label: "Learning" },
    { key: "struggling", count: struggling, color: baseColor, opacity: 0.55, label: "Struggling" },
    { key: "unexplored", count: unexplored, color: "var(--bg-soft)", opacity: 1, label: "Unexplored" },
  ];

  return (
    <div className={styles.courseRow} data-spaced={spaced}>
      <div className={styles.courseHead}>
        <span className={styles.courseName}>
          <span className={styles.dot} style={dotColor(course.color)} />
          <strong className={styles.ellipsis}>
            {course.course_code || course.course_name}
          </strong>
        </span>
        <AnimatedNumber className={`mono ${styles.coursePct}`} value={pct} format={formatPct} />
      </div>
      {total > 0 ? (
        <div
          className={styles.bar}
          title={segments.filter(s => s.count > 0).map(s => `${s.label}: ${s.count}`).join(" · ")}
        >
          {segments.map((s) => s.count > 0 && (
            <div
              key={s.key}
              className={styles.segment}
              style={{
                "--seg-w": `${(s.count / total) * 100}%`,
                "--seg-color": s.color,
                "--seg-opacity": s.opacity,
              } as React.CSSProperties}
            />
          ))}
        </div>
      ) : (
        <div className={styles.bar} />
      )}
    </div>
  );
}

const formatPct = (v: number) => `${Math.round(v)}%`;
