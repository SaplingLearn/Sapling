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
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useLayoutPref } from "@/lib/useLayoutPref";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { useLatestRequest } from "@/lib/useLatestRequest";
import {
  getGraph,
  getCourses,
  getUpcomingAssignments,
  getSessions,
  getRecommendations,
  fetchActivity,
  fetchGamificationMe,
  type EnrolledCourse,
  type Session,
  type Assignment,
} from "@/lib/api";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "@/lib/types";
import { apiToGraphNode, learnHrefForNode, type GraphNode, type GraphEdge } from "@/lib/data";
import { IS_TEST_MODE, now } from "@/lib/testMode";
import { buildQuizHref } from "@/lib/quiz/source";
import { DashboardActions, TodayColumn } from "../dashboard/TodayColumn";
import {
  activeDaysFrom,
  assignmentUrgency,
  statsFromGraph,
  streakMarkState,
  type DashboardStats,
} from "../dashboard/dashboardModel";
import { cn } from "@/lib/cn";

/** An assignment known to have a due date (gradebook/Gradescope items may not). */
type DatedAssignment = Assignment & { due_date: string };
const hasDueDate = (a: Assignment): a is DatedAssignment => !!a.due_date;

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
  speed = 55,
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
        }, 300);
      }
    }, speed);
    return () => {
      clearInterval(iv);
      if (settleTimer) clearTimeout(settleTimer);
    };
  }, [text, speed]);

  React.useEffect(() => {
    if (done) { setCursorOn(false); return; }
    const blink = setInterval(() => setCursorOn((v) => !v), 530);
    return () => clearInterval(blink);
  }, [done]);

  return (
    <span>
      {shown}
      <span
        aria-hidden
        className="ml-px text-accent font-extralight [transition:opacity_0.1s]" style={{ opacity: done ? 0 : cursorOn ? 1 : 0 }}
      >
        |
      </span>
    </span>
  );
}

const STREAK_SHIELD_PATH =
  "M8 2.5 L23.5 3.8 Q28.8 4.3 28.3 9.6 L27 24.2 Q26.4 29.2 21.2 28.5 L8.2 27.4 Q3 26.9 3.6 21.7 L4.9 7.6 Q5.5 2.5 10.4 2.7 Z";

function StreakMark({ state, day }: { state: "done" | "today" | "missed" | "future"; day: number }) {
  if (state === "done") {
    return (
      <svg viewBox="0 0 32 32" width="30" height="30" aria-label="completed">
        <path d={STREAK_SHIELD_PATH} fill="var(--alert-warn)" />
        <path
          d="M10.5 16.5 L14.2 20.2 L22 12.4"
          stroke="#fff"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (state === "today") {
    return (
      <svg viewBox="0 0 32 32" width="30" height="30" aria-label="today">
        <circle cx="16" cy="16" r="13" fill="var(--alert-err)" />
        <path
          d="M16 10 V22 M10 16 H22"
          stroke="#fff"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-label={state === "missed" ? "missed" : "upcoming"}>
      <path
        d={STREAK_SHIELD_PATH}
        fill="none"
        stroke="var(--border)"
        strokeWidth="1.5"
      />
      <text
        x="16"
        y="20"
        textAnchor="middle"
        fontSize="11"
        fontWeight="500"
        fill="var(--text-muted)"
        opacity={state === "future" ? 0.5 : 1}
      >
        {day}
      </text>
    </svg>
  );
}

function getWeekDays(today: Date) {
  // Monday-first ISO week.
  const start = new Date(today);
  start.setHours(0, 0, 0, 0);
  const dow = (start.getDay() + 6) % 7; // 0=Mon
  start.setDate(start.getDate() - dow);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

type Navigate = (href: string) => void;
type Recommendation = { concept_name: string; reason?: string };

function fetchDashboard(userId: string, activeSemester: string) {
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
    getRecommendations(userId, activeSemester || undefined).catch(() => ({ recommendations: [] })),
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
  setRecommendations: (v: Recommendation[]) => void;
  setActiveDays: (v: Set<string>) => void;
};

/** Writes one load's replies into state, in the order load() always has. */
function applyDashboardResult(
  [graphRes, coursesRes, assignsRes, sessionsRes, recsRes]: DashboardFetch,
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
  set.setRecommendations(recsRes.recommendations || []);
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
  const [nodes, setNodes] = React.useState<GraphNode[]>([]);
  const [edges, setEdges] = React.useState<GraphEdge[]>([]);
  const [stats, setStats] = React.useState<DashboardStats>({
    streak: 0, mastered: 0, total: 0, learning: 0, struggling: 0, unexplored: 0,
  });
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [sessions, setSessions] = React.useState<Session[]>([]);
  const [assignments, setAssignments] = React.useState<DatedAssignment[]>([]);
  const [recommendations, setRecommendations] = React.useState<Recommendation[]>([]);
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
      const res = await fetchDashboard(userId, activeSemester);
      if (!run.isCurrent()) return;
      applyDashboardResult(res, {
        setCourses, setNodes, setEdges, setStats, setAssignments, setSessions, setRecommendations, setActiveDays,
      });
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("dashboard load failed", err);
      setLoadError(String(err));
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
  }, [userId, activeSemester, loadReq]);

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
    nodes, edges, stats, courses, sessions, assignments, recommendations,
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
    nodes, edges, stats, courses, sessions, assignments, recommendations,
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
      <div className="min-h-full flex flex-col">
        <DashboardSkeleton />
      </div>
    );
  }

  if (loadError && !courses.length) {
    return (
      <div>
        <TopBar title="Couldn't load dashboard" />
        <div className="p-8 text-md">
          <div className="text-err mb-2.5">{loadError}</div>
          <button className="btn btn--primary" onClick={load}>Retry</button>
        </div>
      </div>
    );
  }

  const navigate: Navigate = (href) => router.push(href);
  const highlightId = suggestNode?.id;

  const graphPanel = (
    <div className="flex flex-col gap-4 min-w-0 flex-1 min-h-0">
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
          <div ref={gRefCb} className="relative flex-1 min-h-105">
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
          ? courseProgress.map((entry) => <CourseProgressRow key={entry.course.course_id} entry={entry} spacing={0} />)
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

  const mainColumn = (
    <div
      className="flex flex-col gap-3.5 min-w-0 min-h-0 self-stretch"
    >
      {heroBlock}
      {renderMobileMetaRow({ isMobile, navigate })}
      {suggestBlock}
      {graphPanel}
    </div>
  );

  return (
    <div className="min-h-full flex flex-col">
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
        <div className="pt-2 px-5 pb-4 grid gap-4 grid-cols-[1fr] [align-items:start]">
          {mainColumn}
          {rightPanel}
        </div>
      ) : (
        // Desktop sidebar layout: the greeting and the actions share one header
        // row, so the graph and the right column start on the same line and
        // stretch to the same bottom edge.
        <div className="pt-4.5 px-8 pb-6 flex flex-col gap-3.5 flex-1 min-h-0">
          <div className="flex items-stretch justify-between gap-4">
            <div className="min-w-0">{heroBlock}</div>
            {/* Bottom-aligned with the quote: both sides of the header end on
                one line, the same distance above the cards. */}
            <div
              className="pb-4.5 flex items-end shrink-0"
            >
              <DashboardActions navigate={navigate} />
            </div>
          </div>
          {suggestBlock}
          <div
            className="grid gap-4 grid-cols-[minmax(0,_1fr)_minmax(280px,_360px)] items-stretch flex-1 min-h-0"
          >
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
  return (
    // Flex-column so the inner gRef can flex: 1 and fill whatever
    // height the grid row decides (courses + upcoming stacked on the
    // left determines the row height via align-items: stretch).
    <div
      className="card p-0 overflow-hidden relative min-h-105 flex flex-col flex-1"
    >
      <div className="flex items-center justify-between py-4 px-5.5 border-b border-b-border">
        <div>
          <div className="label-micro">Your knowledge graph</div>
          <div className="h-serif text-[20px] mt-0.5">
            {stats.total || nodes.filter((n) => !n.is_subject_root).length} concepts across {scopedCourses.length} courses
          </div>
        </div>
        <div className="flex gap-2.5 flex-wrap items-center">
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
                className={cn("flex items-center gap-1.5 text-xs bg-transparent border-0 py-0.5 px-1 cursor-pointer [font-family:inherit]", lit ? "text-text" : "text-text-dim", lit ? "font-semibold" : "font-normal")}
              >
                <span className="w-2.5 h-2.5 rounded-[50%]" style={{ background: c.color || "var(--accent)" }} />
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
    <div
      className={cn(centered ? "text-center" : "text-left", isMobile ? "py-3.5 px-1" : "pt-1.5 px-0 pb-4.5")}
    >
      <h1
        className={cn("h-serif", "m-0 font-semibold text-text tracking-[-0.02em] leading-[1.15]", isMobile ? "text-[34px]" : "text-[42px]")}
      >
        <Typewriter text={greetingText} onDone={onGreetingDone} />
      </h1>
      {quote && (
        <p
          aria-hidden={!greetingDone}
          className={cn("body-serif", "max-w-160 text-base italic text-text-dim leading-[1.55] [transition:opacity_0.55s_var(--ease)_0.15s,_transform_0.55s_var(--ease)_0.15s]", centered ? "mt-2 mx-auto mb-0" : "mt-2 mx-0 mb-0", greetingDone ? "opacity-100" : "opacity-0", greetingDone ? "[transform:translateY(0)]" : "[transform:translateY(-6px)]")}
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
    <div className="flex flex-col gap-2">
      <div
        className="flex items-center justify-end gap-2 flex-wrap"
      >
        <button
          className="btn btn--sm btn--primary py-[7px] px-3.5 text-sm"
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
    <div className="card fade-in py-3.5 px-4.5 flex gap-3.5 items-center border-accent-border [background:var(--accent-soft)]">
      <Icon name="sparkle" size={16} />
      <div className="flex-1 text-md">
        <strong>Try this next:</strong> {node.name}
        {node.subject && <span className="text-text-dim"> · {node.subject}</span>}
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

function renderMobileTabs({
  mobileTab, setMobileTab,
}: {
  mobileTab: "courses" | "stats";
  setMobileTab: (t: "courses" | "stats") => void;
}) {
  return (
    <div className="flex gap-1.5 pt-3.5 px-5 pb-0">
      {(["courses", "stats"] as const).map(t => (
        <button
          key={t}
          onClick={() => setMobileTab(t)}
          className={cn("flex-1 py-2 px-3 rounded-sm border border-border text-sm font-semibold capitalize", mobileTab === t ? "bg-accent-soft" : "bg-bg-panel", mobileTab === t ? "text-accent" : "text-text-dim")}
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
    <div
      className={cn("grid gap-4 min-h-0", isMobile ? "pt-2 px-5 pb-4" : "pt-4.5 px-8 pb-6", isMobile ? "grid-cols-[1fr]" : "grid-cols-[minmax(240px,_280px)_minmax(0,_1fr)_minmax(240px,_300px)]", isMobile ? "[align-items:start]" : "items-stretch", isMobile ? "flex-[0_0_auto]" : "flex-1")}
    >
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
    <div className="flex flex-col gap-4 min-w-0">
      <div className="card p-(--pad-lg)">
        <div className="flex justify-between items-center mb-3">
          <div className="label-micro">My courses</div>
          <button className="btn btn--ghost btn--sm" onClick={onOpenCourses}>
            <Icon name="cog" size={12} /> Courses & Semesters
          </button>
        </div>
        {!hasCourses ? (
          <div className="text-sm text-text-muted">No enrolled courses yet.</div>
        ) : courseProgress.length === 0 ? (
          <div className="text-sm text-text-muted">
            Nothing enrolled this semester.
          </div>
        ) : null}
        {courseProgress.map((entry) => (
          <CourseProgressRow key={entry.course.course_id} entry={entry} />
        ))}
      </div>

      <div className="card p-(--pad-lg)">
        <div className="flex justify-between items-center mb-3">
          <div className="label-micro">Upcoming</div>
          <button className="btn btn--ghost btn--sm" onClick={() => navigate("/calendar")}>Calendar →</button>
        </div>
        {assignments.length === 0 && (
          <div className="text-sm text-text-muted">No upcoming assignments.</div>
        )}
        {assignments.slice(0, 4).map((a) => {
          const { chipClass, label } = assignmentUrgency(a.due_date, now());
          return (
            <div key={a.id} className="flex items-center gap-3 py-2 px-0 border-b border-b-border">
              <div className="flex-1 min-w-0">
                <div className="text-md font-medium">{a.title}</div>
                <div className="text-xs text-text-muted">
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
    <div className="flex flex-col gap-4 min-w-0">
      {!isMobile && (
        <div className="py-0 px-0.5 flex justify-end gap-2 min-h-7">
          <button
            className="btn btn--sm btn--primary py-[7px] px-3.5 text-sm"
            onClick={() => navigate("/learn")}
          >
            <Icon name="sparkle" size={13} /> Start learning
          </button>
        </div>
      )}
      <div className="card p-(--pad-lg)">
        <div className="label-micro mb-2">This week</div>
        <div className="body-serif text-lg mb-3.5 text-text">
          {stats.streak > 0 ? (
            <>You&apos;re on a <span className="h-serif text-warn font-semibold">{stats.streak}-day</span> streak.</>
          ) : (
            <>Ready when you are. Open any session to begin a streak.</>
          )}
        </div>
        <div className="grid grid-cols-[repeat(7,_1fr)] gap-1.5">
          {weekDays.map(d => {
            const key = d.toISOString().slice(0, 10);
            return (
              <div key={key} className="text-center">
                <div className="label-micro text-xs">
                  {d.toLocaleDateString("en-US", { weekday: "short" }).slice(0, 2)}
                </div>
                <div className="mt-1.5 grid place-items-center">
                  <StreakMark state={streakMarkState(d, today, activeDays)} day={d.getDate()} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card p-0 grid grid-cols-[1fr_1fr]">
        <MiniStat
          label="Mastered"
          value={stats.mastered}
          sub={stats.total ? `of ${stats.total} concepts` : undefined}
        />
        <MiniStat
          label="Learning"
          value={stats.learning + stats.struggling}
          sub={`${stats.unexplored} unexplored`}
        />
      </div>

      <div className="card p-(--pad-lg)">
        <div className="flex justify-between items-center mb-3">
          <div className="label-micro">Learn next</div>
          <button className="btn btn--ghost btn--sm" onClick={() => navigate("/tree")}>Tree →</button>
        </div>
        {recommendations.length === 0 && (
          <div className="text-sm text-text-muted">Nothing suggested yet — start a session.</div>
        )}
        {recommendations.slice(0, 3).map((r, i) => (
          <button
            key={`${r.concept_name}-${i}`}
            onClick={() => navigate(`/learn?topic=${encodeURIComponent(r.concept_name)}&mode=socratic`)}
            className="flex items-start gap-2.5 w-full py-2.5 px-3 rounded-md bg-bg-subtle mb-1.5 text-left"
          >
            <Icon name="sparkle" size={14} />
            <div className="flex-1 min-w-0">
              <div className="text-md font-semibold">{r.concept_name}</div>
              {r.reason && <div className="text-xs text-text-muted">{r.reason}</div>}
            </div>
            <Icon name="chev" size={12} />
          </button>
        ))}
        <div className="flex gap-1.5 mt-2.5">
          <button className="btn btn--sm flex-1" onClick={() => navigate("/social")}>
            <Icon name="users" size={12} /> Study room
          </button>
        </div>
      </div>
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
    <div
      className="fixed inset-0 z-150 bg-bg flex flex-col"
    >
      <div className="flex justify-between items-center py-3.5 px-5 border-b border-b-border">
        <div>
          <div className="label-micro">Knowledge graph — fullscreen</div>
          <div className="h-serif text-xl">Press Esc to exit</div>
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
    <div ref={ref} className="flex-1 relative">
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

// One "My courses" line: colour dot, course code, mastery percentage and the
// four-segment mastery bar.
function CourseProgressRow({
  entry,
  spacing = 12,
}: {
  entry: CourseProgressEntry;
  /** Space below the row. 0 when the parent spaces its rows itself. */
  spacing?: number;
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

  const body = (
    <>
      <div className="flex justify-between items-center text-sm mb-1">
        <span className="inline-flex items-center gap-2 min-w-0">
          <span className="w-2.5 h-2.5 rounded-[50%] shrink-0" style={{ background: baseColor }} />
          <strong className="overflow-hidden text-ellipsis whitespace-nowrap">
            {course.course_code || course.course_name}
          </strong>
        </span>
        <span className="mono text-text-dim text-xs shrink-0 ml-2">
          {pct}%
        </span>
      </div>
      {total > 0 ? (
        <div
          className="flex h-2 bg-bg-soft rounded-[var(--r-full)] overflow-hidden"
          title={segments.filter(s => s.count > 0).map(s => `${s.label}: ${s.count}`).join(" · ")}
        >
          {segments.map((s) => s.count > 0 && (
            <div
              key={s.key}
              className="[transition:width_var(--dur)_var(--ease)]" style={{ width: `${(s.count / total) * 100}%`, background: s.color, opacity: s.opacity }}
            />
          ))}
        </div>
      ) : (
        <div className="h-2 bg-bg-soft rounded-[var(--r-full)]" />
      )}
    </>
  );

  return <div style={{ marginBottom: spacing }}>{body}</div>;
}

