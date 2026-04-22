"use client";
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { MiniStat } from "../MiniStat";
import { KnowledgeGraph } from "../KnowledgeGraph";
import { ManageCoursesModal } from "../ManageCoursesModal";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useLayoutPref } from "@/lib/useLayoutPref";
import {
  getGraph,
  getCourses,
  getUpcomingAssignments,
  getSessions,
  getRecommendations,
  type EnrolledCourse,
  type Session,
  type Assignment,
} from "@/lib/api";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "@/lib/types";
import type { GraphNode, GraphEdge } from "@/lib/data";

const QUOTES = [
  "Learning is the only thing the mind never exhausts, never fears, and never regrets. — da Vinci",
  "The roots of education are bitter, but the fruit is sweet. — Aristotle",
  "Live as if you were to die tomorrow. Learn as if you were to live forever. — Gandhi",
  "An investment in knowledge pays the best interest. — Franklin",
  "The beautiful thing about learning is that no one can take it away from you. — B.B. King",
  "Tell me and I forget. Teach me and I remember. Involve me and I learn. — Franklin",
];

function apiToGraphNode(n: ApiNode, courses: EnrolledCourse[]): GraphNode {
  const course = courses.find((c) => c.course_name === n.subject);
  return {
    id: n.id,
    name: n.concept_name,
    subject: n.subject,
    color: n.course_color || course?.color || "var(--c-sage)",
    is_subject_root: n.is_subject_root,
    mastery_tier: n.mastery_tier === "subject_root" ? "mastered" : n.mastery_tier,
    mastery_score: n.mastery_score,
    course_id: n.course_id || course?.course_id || "",
    last_studied_at: n.last_studied_at || undefined,
  };
}

function apiToGraphEdge(e: ApiEdge): GraphEdge {
  return { source: e.source as string, target: e.target as string, strength: e.strength };
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
        style={{
          opacity: done ? 0 : cursorOn ? 1 : 0,
          marginLeft: 1,
          color: "var(--accent)",
          fontWeight: 200,
          transition: "opacity 0.1s",
        }}
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
        <path d={STREAK_SHIELD_PATH} fill="#e87734" />
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
        <circle cx="16" cy="16" r="13" fill="#e94b5c" />
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

export function Dashboard() {
  const router = useRouter();
  const search = useSearchParams();
  const { userId, userName, userReady } = useUser();
  const isMobile = useIsMobile();
  const [layoutPref] = useLayoutPref();
  // Top-nav layout keeps the pre-revamp 3-column dashboard with the
  // streak widget, Learn-next recommendations, and My Courses as a
  // proper panel on the left. Sidebar layout uses the new 2-column
  // design with the CoursesKey overlay inside the graph panel.
  const useLegacyPanels = layoutPref === "topnav";

  const [nodes, setNodes] = React.useState<GraphNode[]>([]);
  const [edges, setEdges] = React.useState<GraphEdge[]>([]);
  const [stats, setStats] = React.useState<{ streak: number; mastered: number; total: number; learning: number; struggling: number; unexplored: number }>({
    streak: 0, mastered: 0, total: 0, learning: 0, struggling: 0, unexplored: 0,
  });
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [sessions, setSessions] = React.useState<Session[]>([]);
  const [assignments, setAssignments] = React.useState<Assignment[]>([]);
  const [recommendations, setRecommendations] = React.useState<{ concept_name: string; reason?: string }[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [activeDays, setActiveDays] = React.useState<Set<string>>(new Set());

  const [coursesOpen, setCoursesOpen] = React.useState(false);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [mobileTab, setMobileTab] = React.useState<"courses" | "stats">("courses");

  // Graph container is now flex-filled, so there's no "correct" initial
  // height — 420 is a reasonable pre-measurement guess that lines up
  // with the new minHeight. ResizeObserver corrects it on mount.
  const [size, setSize] = React.useState({ w: 720, h: 420 });
  // Callback ref so the ResizeObserver (re)attaches every time the graph
  // container mounts — the loading branch renders before the graph exists,
  // so a plain useRef + useEffect misses the attachment.
  const roRef = React.useRef<ResizeObserver | null>(null);
  const gRefCb = React.useCallback((el: HTMLDivElement | null) => {
    roRef.current?.disconnect();
    roRef.current = null;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setSize({ w: e.contentRect.width, h: e.contentRect.height });
      }
    });
    ro.observe(el);
    roRef.current = ro;
  }, []);

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
    setQuote(QUOTES[Math.floor(Math.random() * QUOTES.length)]);
    const t = new Date(); t.setHours(0, 0, 0, 0); setToday(t);
  }, []);
  const weekDays = React.useMemo(() => getWeekDays(today), [today]);


  const load = React.useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [graphRes, coursesRes, assignsRes, sessionsRes, recsRes] = await Promise.all([
        getGraph(userId),
        getCourses(userId),
        getUpcomingAssignments(userId),
        getSessions(userId, 10),
        getRecommendations(userId).catch(() => ({ recommendations: [] })),
      ]);
      const cs = coursesRes.courses || [];
      setCourses(cs);
      const gNodes: GraphNode[] = (graphRes.nodes || []).map((n: ApiNode) => apiToGraphNode(n, cs));
      setNodes(gNodes);
      setEdges((graphRes.edges || []).map(apiToGraphEdge));
      setStats({
        streak: graphRes.stats?.streak ?? 0,
        mastered: graphRes.stats?.mastered ?? 0,
        total: graphRes.stats?.total_nodes ?? 0,
        learning: graphRes.stats?.learning ?? 0,
        struggling: graphRes.stats?.struggling ?? 0,
        unexplored: graphRes.stats?.unexplored ?? 0,
      });
      setAssignments(assignsRes.assignments || []);
      setSessions(sessionsRes.sessions || []);
      setRecommendations(recsRes.recommendations || []);

      const days = new Set<string>();
      for (const n of gNodes) {
        if (!n.last_studied_at) continue;
        const d = new Date(n.last_studied_at);
        if (!isNaN(d.getTime())) days.add(d.toISOString().slice(0, 10));
      }
      setActiveDays(days);
    } catch (err) {
      console.error("dashboard load failed", err);
      setLoadError(String(err));
    } finally {
      setLoading(false);
    }
  }, [userId]);

  React.useEffect(() => {
    if (userReady && userId) load();
  }, [userReady, userId, load]);

  React.useEffect(() => {
    if (!fullscreen) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    document.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", h);
      document.body.style.overflow = "";
    };
  }, [fullscreen]);

  const firstName = userName ? userName.split(" ")[0] : "";
  const [greetingPrefix, setGreetingPrefix] = React.useState<string>("Welcome back");
  React.useEffect(() => {
    setGreetingPrefix(getGreetingPrefix(new Date()));
  }, []);
  const greetingText = firstName ? `${greetingPrefix}, ${firstName}` : "Welcome back";
  const [greetingDone, setGreetingDone] = React.useState(false);
  // Greeting + quote render as a centered hero below the TopBar (see
  // return JSX), not as TopBar title/subtitle. Leaving the TopBar lean
  // makes the Dashboard feel like an arrival page, not a tool page.

  const courseProgress = React.useMemo(() => {
    return courses.map(c => {
      const courseNodes = nodes.filter(n => n.course_id === c.course_id && !n.is_subject_root);
      const mastered = courseNodes.filter(n => n.mastery_tier === "mastered").length;
      const learning = courseNodes.filter(n => n.mastery_tier === "learning").length;
      const struggling = courseNodes.filter(n => n.mastery_tier === "struggling").length;
      const unexplored = courseNodes.filter(n => n.mastery_tier === "unexplored" || !n.mastery_tier).length;
      const total = courseNodes.length;
      return {
        course: c,
        mastered,
        learning,
        struggling,
        unexplored,
        total,
        progress: total ? mastered / total : 0,
      };
    });
  }, [courses, nodes]);

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
      <div>
        <TopBar breadcrumb="Home / Dashboard" title="Loading…" />
        <div style={{ padding: 32, color: "var(--text-muted)", fontSize: 13 }}>Gathering your knowledge…</div>
      </div>
    );
  }

  if (loadError && !courses.length) {
    return (
      <div>
        <TopBar breadcrumb="Home / Dashboard" title="Couldn't load dashboard" />
        <div style={{ padding: 32, fontSize: 13 }}>
          <div style={{ color: "var(--err)", marginBottom: 10 }}>{loadError}</div>
          <button className="btn btn--primary" onClick={load}>Retry</button>
        </div>
      </div>
    );
  }

  const graphBlock = (
    // Flex-column so the inner gRef can flex: 1 and fill whatever
    // height the grid row decides (courses + upcoming stacked on the
    // left determines the row height via align-items: stretch).
    <div
      className="card"
      style={{
        padding: 0, overflow: "hidden", position: "relative",
        minHeight: 420,
        display: "flex", flexDirection: "column",
        flex: 1,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 22px", borderBottom: "1px solid var(--border)" }}>
        <div>
          <div className="label-micro">Your knowledge graph</div>
          <div className="h-serif" style={{ fontSize: 20, marginTop: 2 }}>
            {stats.total || nodes.filter((n) => !n.is_subject_root).length} concepts across {courses.length} courses
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          {useLegacyPanels && courses.slice(0, 5).map((c) => (
            <div key={c.course_id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-dim)" }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: c.color || "var(--accent)" }} />
              {c.course_code || c.course_name}
            </div>
          ))}
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setFullscreen(true)}
            aria-label="Fullscreen graph"
          >
            <Icon name="max" size={12} />
          </button>
        </div>
      </div>
      <div ref={gRefCb} style={{ position: "relative", flex: 1, minHeight: 260 }}>
        <KnowledgeGraph
          nodes={nodes}
          edges={edges}
          width={size.w}
          height={size.h}
          highlightId={suggestNode?.id}
          onNodeClick={(n) => {
            const p = new URLSearchParams();
            p.set("topic", n.name);
            p.set("mode", "socratic");
            if (n.course_id) p.set("course_id", n.course_id);
            router.push(`/learn?${p.toString()}`);
          }}
        />
        {/* Courses key — sidebar layout only. Top-nav layout uses the
            full My Courses panel in the left column instead. */}
        {!useLegacyPanels && (
          <CoursesKey
            courseProgress={courseProgress}
            onManage={() => setCoursesOpen(true)}
          />
        )}
        <div style={{ position: "absolute", left: 16, bottom: 14, display: "flex", gap: 12, fontSize: 11, color: "var(--text-muted)" }}>
          {([
            ["mastered", "#4a7d5c"],
            ["learning", "#c89b5e"],
            ["struggling", "#b25855"],
            ["unexplored", "#9a9a9a"],
          ] as const).map(([t, color]) => (
            <div key={t} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: color }} />
              {t}
            </div>
          ))}
        </div>
      </div>
    </div>
  );


  const graphPanel = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0, flex: 1, minHeight: 0 }}>
      {graphBlock}
    </div>
  );

  const relTime = (iso: string | null | undefined) => {
    if (!iso) return "—";
    const diff = Date.now() - new Date(iso).getTime();
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
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
      {!isMobile && (
        <div style={{ padding: "0 2px", display: "flex", justifyContent: "flex-end", gap: 8, minHeight: 30 }}>
          <button className="btn btn--sm" onClick={() => router.push("/library")}>
            <Icon name="search" size={13} /> Search
          </button>
          <button className="btn btn--sm btn--primary" onClick={() => router.push("/learn")}>
            <Icon name="sparkle" size={13} /> Start learning
          </button>
        </div>
      )}

      {/* Panel 1 — Streak + Mastered, split 50/50 like the design reference. */}
      <div className="card" style={{ padding: 0, display: "grid", gridTemplateColumns: "1fr 1fr" }}>
        <div style={{ padding: "16px 18px", borderRight: "1px solid var(--border)" }}>
          <div className="label-micro" style={{ marginBottom: 6 }}>Streak</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span
              className="h-serif"
              style={{ fontSize: 32, fontWeight: 600, color: stats.streak > 0 ? "var(--warn)" : "var(--text)", lineHeight: 1 }}
            >
              {stats.streak}
            </span>
            <span style={{ fontSize: 13, color: "var(--text-dim)" }}>days</span>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
            Personal best: {Math.max(stats.streak, 0)}
          </div>
        </div>
        <div style={{ padding: "16px 18px" }}>
          <div className="label-micro" style={{ marginBottom: 6 }}>Mastered</div>
          <div
            className="h-serif"
            style={{ fontSize: 32, fontWeight: 600, lineHeight: 1 }}
          >
            {stats.mastered}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
            {stats.total ? `of ${stats.total} concepts` : "no concepts yet"}
          </div>
        </div>
      </div>

      {/* Panel 2 — Where you left off (recent sessions). */}
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <div className="label-micro">Today</div>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => router.push("/learn")}
          >
            View all
          </button>
        </div>
        <div className="h-serif" style={{ fontSize: 16, marginBottom: 12 }}>Where you left off</div>
        {sessions.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            No recent sessions — start learning to fill this in.
          </div>
        ) : (
          sessions.slice(0, 3).map((s) => (
            <button
              key={s.id}
              onClick={() => router.push(`/learn?resume=${encodeURIComponent(s.id)}`)}
              style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                padding: "10px 12px", borderRadius: "var(--r-md)",
                background: "var(--bg-subtle)", marginBottom: 6, textAlign: "left",
              }}
            >
              <Icon name="brain" size={14} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 13, fontWeight: 600,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}
                >
                  {s.topic}
                </div>
                <div
                  style={{
                    fontSize: 11, color: "var(--text-muted)",
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}
                >
                  {[courseNameFor(s.course_id), s.mode, relTime(s.started_at)].filter(Boolean).join(" · ")}
                </div>
              </div>
              <Icon name="chev" size={12} />
            </button>
          ))
        )}
      </div>

      {/* Panel 3 — Upcoming assignments. */}
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div className="label-micro">Upcoming</div>
          <button className="btn btn--ghost btn--sm" onClick={() => router.push("/calendar")}>Calendar →</button>
        </div>
        {assignments.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No upcoming assignments.</div>
        )}
        {assignments.slice(0, 4).map((a) => {
          const diffMs = new Date(a.due_date).getTime() - Date.now();
          const hours = diffMs / (1000 * 60 * 60);
          const days = Math.ceil(diffMs / 86400000);
          let chipClass = "chip--info";
          let label = `${days}D`;
          if (hours <= 0) {
            chipClass = "chip--err";
            label = "OVERDUE";
          } else if (hours <= 24) {
            chipClass = "chip--err";
            label = hours < 1 ? "NOW" : `${Math.max(1, Math.round(hours))}H`;
          } else if (days <= 2) {
            chipClass = "chip--warn";
          }
          return (
            <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{a.title}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
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

  const heroBlock = (
    <div style={{ textAlign: "center", padding: isMobile ? "14px 4px 0" : "6px 0 0" }}>
      <h1
        className="h-serif"
        style={{
          margin: 0,
          fontSize: isMobile ? 34 : 42,
          fontWeight: 600,
          color: "var(--text)",
          letterSpacing: "-0.02em",
          lineHeight: 1.15,
        }}
      >
        <Typewriter text={greetingText} onDone={() => setGreetingDone(true)} />
      </h1>
      {quote && (
        <p
          aria-hidden={!greetingDone}
          className="body-serif"
          style={{
            margin: "14px auto 0",
            maxWidth: 640,
            fontSize: 14,
            fontStyle: "italic",
            color: "var(--text-dim)",
            lineHeight: 1.55,
            opacity: greetingDone ? 1 : 0,
            transform: greetingDone ? "translateY(0)" : "translateY(-6px)",
            transition:
              "opacity 0.55s var(--ease) 0.15s, transform 0.55s var(--ease) 0.15s",
          }}
        >
          "{quote}"
        </p>
      )}
    </div>
  );

  const mobileMetaRow = isMobile ? (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        flexWrap: "wrap",
      }}
    >
      <span className="label-micro">Home / Dashboard</span>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn--sm" onClick={() => router.push("/library")}>
          <Icon name="search" size={13} /> Library
        </button>
        <button className="btn btn--sm btn--primary" onClick={() => router.push("/learn")}>
          <Icon name="sparkle" size={13} /> Start learning
        </button>
      </div>
    </div>
  ) : null;

  const suggestBlock = suggestNode && !suggestDismissed ? (
    <div className="card fade-in" style={{ padding: "14px 18px", display: "flex", gap: 14, alignItems: "center", borderColor: "var(--accent-border)", background: "var(--accent-soft)" }}>
      <Icon name="sparkle" size={16} />
      <div style={{ flex: 1, fontSize: 13 }}>
        <strong>Try this next:</strong> {suggestNode.name}
        {suggestNode.subject && <span style={{ color: "var(--text-dim)" }}> · {suggestNode.subject}</span>}
      </div>
      <button className="btn btn--sm btn--primary" onClick={() => router.push(`/learn?topic=${encodeURIComponent(suggestNode.name)}&mode=quiz`)}>
        Start quiz
      </button>
      <button className="btn btn--sm btn--ghost" onClick={dismissSuggest}>Dismiss</button>
    </div>
  ) : null;

  const mainColumn = (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
        minWidth: 0,
        minHeight: 0,
        alignSelf: "stretch",
      }}
    >
      {!isMobile && !useLegacyPanels && (
        <div style={{ padding: "0 2px", display: "flex", alignItems: "center", minHeight: 30 }}>
          <span className="label-micro">Home / Dashboard</span>
        </div>
      )}
      {heroBlock}
      {mobileMetaRow}
      {suggestBlock}
      {graphPanel}
    </div>
  );

  // ── Legacy (top-nav) layout panels ──────────────────────────────────────
  // Pre-revamp 3-column dashboard: My Courses + Upcoming on the left,
  // hero + graph in the middle, streak widget + MiniStat + Learn next
  // on the right. Only rendered when layoutPref === "topnav".
  const legacyCoursesPanel = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
      {!isMobile && (
        <div style={{ padding: "0 2px", display: "flex", alignItems: "center", minHeight: 30 }}>
          <span className="label-micro">Home / Dashboard</span>
        </div>
      )}
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div className="label-micro">My courses</div>
          <button className="btn btn--ghost btn--sm" onClick={() => setCoursesOpen(true)}>
            <Icon name="cog" size={12} /> Manage
          </button>
        </div>
        {courseProgress.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No enrolled courses yet.</div>
        )}
        {courseProgress.map(({ course, mastered, learning, struggling, unexplored, total, progress }) => {
          const pct = Math.round(progress * 100);
          const baseColor = course.color || "var(--accent)";
          const segments = [
            { key: "mastered",   count: mastered,   color: baseColor, opacity: 1,    label: "Mastered" },
            { key: "learning",   count: learning,   color: baseColor, opacity: 0.78, label: "Learning" },
            { key: "struggling", count: struggling, color: baseColor, opacity: 0.55, label: "Struggling" },
            { key: "unexplored", count: unexplored, color: "var(--bg-soft)", opacity: 1, label: "Unexplored" },
          ];
          return (
            <div key={course.course_id} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, marginBottom: 4 }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <span style={{ width: 10, height: 10, borderRadius: "50%", background: baseColor, flexShrink: 0 }} />
                  <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {course.course_code || course.course_name}
                  </strong>
                </span>
                <span className="mono" style={{ color: "var(--text-dim)", fontSize: 11, flexShrink: 0, marginLeft: 8 }}>
                  {pct}%
                </span>
              </div>
              {total > 0 ? (
                <div
                  style={{
                    display: "flex",
                    height: 8,
                    background: "var(--bg-soft)",
                    borderRadius: "var(--r-full)",
                    overflow: "hidden",
                  }}
                  title={segments.filter(s => s.count > 0).map(s => `${s.label}: ${s.count}`).join(" · ")}
                >
                  {segments.map((s) => s.count > 0 && (
                    <div
                      key={s.key}
                      style={{
                        width: `${(s.count / total) * 100}%`,
                        background: s.color,
                        opacity: s.opacity,
                        transition: "width var(--dur) var(--ease)",
                      }}
                    />
                  ))}
                </div>
              ) : (
                <div style={{ height: 8, background: "var(--bg-soft)", borderRadius: "var(--r-full)" }} />
              )}
            </div>
          );
        })}
      </div>

      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div className="label-micro">Upcoming</div>
          <button className="btn btn--ghost btn--sm" onClick={() => router.push("/calendar")}>Calendar →</button>
        </div>
        {assignments.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No upcoming assignments.</div>
        )}
        {assignments.slice(0, 4).map((a) => {
          const diffMs = new Date(a.due_date).getTime() - Date.now();
          const hours = diffMs / (1000 * 60 * 60);
          const days = Math.ceil(diffMs / 86400000);
          let chipClass = "chip--info";
          let label = `${days}D`;
          if (hours <= 0) {
            chipClass = "chip--err";
            label = "OVERDUE";
          } else if (hours <= 24) {
            chipClass = "chip--err";
            label = hours < 1 ? "NOW" : `${Math.max(1, Math.round(hours))}H`;
          } else if (days <= 2) {
            chipClass = "chip--warn";
          }
          return (
            <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{a.title}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
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

  const legacyRightPanel = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
      {!isMobile && (
        <div style={{ padding: "0 2px", display: "flex", justifyContent: "flex-end", gap: 8, minHeight: 30 }}>
          <button className="btn btn--sm" onClick={() => router.push("/library")}>
            <Icon name="search" size={13} /> Library
          </button>
          <button className="btn btn--sm btn--primary" onClick={() => router.push("/learn")}>
            <Icon name="sparkle" size={13} /> Start learning
          </button>
        </div>
      )}
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 8 }}>This week</div>
        <div className="body-serif" style={{ fontSize: 16, marginBottom: 14, color: "var(--text)" }}>
          {stats.streak > 0 ? (
            <>You&apos;re on a <span className="h-serif" style={{ color: "var(--warn)", fontWeight: 600 }}>{stats.streak}-day</span> streak.</>
          ) : (
            <>Ready when you are. Open any session to begin a streak.</>
          )}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6 }}>
          {weekDays.map(d => {
            const key = d.toISOString().slice(0, 10);
            const active = activeDays.has(key);
            const isToday = d.getTime() === today.getTime();
            const isPast = d.getTime() < today.getTime();
            const state: "done" | "today" | "missed" | "future" =
              active ? "done" : isToday ? "today" : isPast ? "missed" : "future";
            return (
              <div key={key} style={{ textAlign: "center" }}>
                <div className="label-micro" style={{ fontSize: 9 }}>
                  {d.toLocaleDateString("en-US", { weekday: "short" }).slice(0, 2)}
                </div>
                <div style={{ marginTop: 6, display: "grid", placeItems: "center" }}>
                  <StreakMark state={state} day={d.getDate()} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card" style={{ padding: 0, display: "grid", gridTemplateColumns: "1fr 1fr" }}>
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

      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div className="label-micro">Learn next</div>
          <button className="btn btn--ghost btn--sm" onClick={() => router.push("/tree")}>Tree →</button>
        </div>
        {recommendations.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Nothing suggested yet — start a session.</div>
        )}
        {recommendations.slice(0, 3).map((r, i) => (
          <button
            key={`${r.concept_name}-${i}`}
            onClick={() => router.push(`/learn?topic=${encodeURIComponent(r.concept_name)}&mode=socratic`)}
            style={{
              display: "flex", alignItems: "flex-start", gap: 10, width: "100%",
              padding: "10px 12px", borderRadius: "var(--r-md)",
              background: "var(--bg-subtle)", marginBottom: 6, textAlign: "left",
            }}
          >
            <Icon name="sparkle" size={14} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{r.concept_name}</div>
              {r.reason && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{r.reason}</div>}
            </div>
            <Icon name="chev" size={12} />
          </button>
        ))}
        <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
          <button className="btn btn--sm btn--primary" style={{ flex: 1 }} onClick={() => router.push("/learn?mode=quiz")}>
            <Icon name="bolt" size={12} /> Quick quiz
          </button>
          <button className="btn btn--sm" style={{ flex: 1 }} onClick={() => router.push("/social")}>
            <Icon name="users" size={12} /> Study room
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div>
      {isMobile && useLegacyPanels && (
        <div style={{ display: "flex", gap: 6, padding: "14px 20px 0" }}>
          {(["courses", "stats"] as const).map(t => (
            <button
              key={t}
              onClick={() => setMobileTab(t)}
              style={{
                flex: 1, padding: "8px 12px", borderRadius: "var(--r-sm)",
                background: mobileTab === t ? "var(--accent-soft)" : "var(--bg-panel)",
                color: mobileTab === t ? "var(--accent)" : "var(--text-dim)",
                border: "1px solid var(--border)", fontSize: 12, fontWeight: 600,
                textTransform: "capitalize",
              }}
            >
              {t === "courses" ? "My Courses" : "Stats & More"}
            </button>
          ))}
        </div>
      )}

      {useLegacyPanels ? (
        <div
          style={{
            padding: isMobile ? "8px 20px 16px" : "18px 32px 24px",
            display: "grid", gap: 16,
            gridTemplateColumns: isMobile ? "1fr" : "minmax(240px, 280px) minmax(0, 1fr) minmax(240px, 300px)",
            alignItems: isMobile ? "start" : "stretch",
          }}
        >
          {isMobile ? (
            mobileTab === "courses" ? (
              <>
                {mainColumn}
                {legacyCoursesPanel}
              </>
            ) : (
              <>
                {mainColumn}
                {legacyRightPanel}
              </>
            )
          ) : (
            <>
              {legacyCoursesPanel}
              {mainColumn}
              {legacyRightPanel}
            </>
          )}
        </div>
      ) : (
        <div
          style={{
            padding: isMobile ? "8px 20px 16px" : "18px 32px 24px",
            display: "grid", gap: 16,
            gridTemplateColumns: isMobile ? "1fr" : "minmax(0, 1fr) minmax(280px, 360px)",
            alignItems: isMobile ? "start" : "stretch",
          }}
        >
          {mainColumn}
          {rightPanel}
        </div>
      )}


      {fullscreen && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 150, background: "var(--bg)",
            display: "flex", flexDirection: "column",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
            <div>
              <div className="label-micro">Knowledge graph — fullscreen</div>
              <div className="h-serif" style={{ fontSize: 18 }}>Press Esc to exit</div>
            </div>
            <button className="btn btn--ghost btn--sm" onClick={() => setFullscreen(false)}>
              <Icon name="x" size={14} />
            </button>
          </div>
          <FullscreenGraph
            nodes={nodes}
            edges={edges}
            highlightId={suggestNode?.id}
            onNodeClick={(n) => {
              setFullscreen(false);
              router.push(`/learn?topic=${encodeURIComponent(n.name)}&mode=socratic${n.course_id ? `&course_id=${encodeURIComponent(n.course_id)}` : ""}`);
            }}
          />
        </div>
      )}

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

function FullscreenGraph({
  nodes, edges, highlightId, onNodeClick,
}: {
  nodes: GraphNode[]; edges: GraphEdge[];
  highlightId?: string;
  onNodeClick: (n: GraphNode) => void;
}) {
  const [size, setSize] = React.useState({ w: 1200, h: 700 });
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const ro = new ResizeObserver(e => setSize({ w: e[0].contentRect.width, h: e[0].contentRect.height }));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} style={{ flex: 1, position: "relative" }}>
      <KnowledgeGraph
        nodes={nodes}
        edges={edges}
        width={size.w}
        height={size.h}
        highlightId={highlightId}
        onNodeClick={onNodeClick}
      />
    </div>
  );
}

type CourseProgressEntry = {
  course: EnrolledCourse;
  mastered: number;
  learning: number;
  struggling: number;
  unexplored: number;
  total: number;
  progress: number;
};

function CoursesKey({
  courseProgress,
  onManage,
}: {
  courseProgress: CourseProgressEntry[];
  onManage: () => void;
}) {
  const [collapsed, setCollapsed] = React.useState(true);

  if (courseProgress.length === 0) return null;

  // A thick white outline painted BEHIND the glyphs, plus a soft halo.
  // `paint-order: stroke fill` pushes the stroke under the fill so
  // letters stay clean-edged. Works against any background colour
  // (graph nodes, edges, labels) without needing a backdrop.
  const legibleText: React.CSSProperties = {
    WebkitTextStroke: "3px rgba(255,255,255,0.95)",
    paintOrder: "stroke fill" as React.CSSProperties["paintOrder"],
    textShadow:
      "0 0 4px rgba(255,255,255,0.95), " +
      "0 0 2px rgba(255,255,255,1), " +
      "0 0 8px rgba(255,255,255,0.6)",
  };
  // Progress-bar track gets a white ring so the bar geometry reads
  // even when a colored graph node passes right behind it.
  const legibleBar: React.CSSProperties = {
    boxShadow: "0 0 0 1.5px rgba(255,255,255,0.95), 0 0 6px rgba(255,255,255,0.6)",
  };
  const legibleDot: React.CSSProperties = {
    boxShadow: "0 0 0 2px rgba(255,255,255,0.95)",
  };
  // Soft white halo around each icon — blurred drop-shadows stacked at
  // the same origin so the glow follows the icon's shape with no hard
  // edges. Button itself stays transparent.
  const paddedIconBtn: React.CSSProperties = {
    padding: 0,
    background: "transparent",
    border: "none",
    fontSize: 10,
    lineHeight: 0,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    filter:
      "drop-shadow(0 0 2px rgba(255,255,255,1)) " +
      "drop-shadow(0 0 4px rgba(255,255,255,0.85)) " +
      "drop-shadow(0 0 6px rgba(255,255,255,0.55))",
  };

  return (
    <div
      style={{
        position: "absolute",
        bottom: 12,
        right: 12,
        width: collapsed ? "auto" : 220,
        maxWidth: "calc(100% - 24px)",
        background: "transparent",
        border: "none",
        borderRadius: 0,
        boxShadow: "none",
        padding: collapsed ? "6px 10px" : "10px 12px 8px",
        zIndex: 2,
        fontSize: 11,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          marginBottom: collapsed ? 0 : 8,
        }}
      >
        <div className="label-micro" style={{ fontSize: 9, ...legibleText }}>My courses</div>
        <div style={{ display: "flex", gap: 4 }}>
          {!collapsed && (
            <button
              className="btn btn--ghost btn--sm"
              onClick={onManage}
              title="Manage courses"
              style={paddedIconBtn}
            >
              <Icon name="cog" size={10} />
            </button>
          )}
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setCollapsed(c => !c)}
            aria-label={collapsed ? "Expand courses key" : "Collapse courses key"}
            style={paddedIconBtn}
          >
            <Icon name={collapsed ? "plus" : "x"} size={10} />
          </button>
        </div>
      </div>

      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {courseProgress.map(({ course, mastered, learning, struggling, unexplored, total, progress }) => {
            const pct = Math.round(progress * 100);
            const baseColor = course.color || "var(--accent)";
            const segs = [
              { count: mastered,   color: baseColor,         opacity: 1 },
              { count: learning,   color: baseColor,         opacity: 0.78 },
              { count: struggling, color: baseColor,         opacity: 0.55 },
              { count: unexplored, color: "var(--bg-soft)",  opacity: 1 },
            ];
            return (
              <div key={course.course_id}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3, gap: 6 }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: baseColor, flexShrink: 0, ...legibleDot }} />
                    <strong style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", ...legibleText }}>
                      {course.course_code || course.course_name}
                    </strong>
                  </span>
                  <span className="mono" style={{ color: "var(--text-dim)", fontSize: 10, ...legibleText }}>{pct}%</span>
                </div>
                {total > 0 ? (
                  <div
                    style={{
                      display: "flex",
                      height: 5,
                      background: "var(--bg-soft)",
                      borderRadius: "var(--r-full)",
                      overflow: "hidden",
                      ...legibleBar,
                    }}
                    title={`Mastered ${mastered} · Learning ${learning} · Struggling ${struggling} · Unexplored ${unexplored}`}
                  >
                    {segs.map((s, i) => s.count > 0 && (
                      <div
                        key={i}
                        style={{
                          width: `${(s.count / total) * 100}%`,
                          background: s.color,
                          opacity: s.opacity,
                          transition: "width var(--dur) var(--ease)",
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <div style={{ height: 5, background: "var(--bg-soft)", borderRadius: "var(--r-full)", ...legibleBar }} />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
