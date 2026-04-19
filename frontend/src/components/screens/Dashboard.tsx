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

function Typewriter({ text, speed = 55 }: { text: string; speed?: number }) {
  const [shown, setShown] = React.useState("");
  const [cursor, setCursor] = React.useState(true);
  React.useEffect(() => {
    setShown("");
    let i = 0;
    const iv = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) clearInterval(iv);
    }, speed);
    return () => clearInterval(iv);
  }, [text, speed]);
  React.useEffect(() => {
    const iv = setInterval(() => setCursor((c) => !c), 530);
    return () => clearInterval(iv);
  }, []);
  return (
    <span>
      {shown}
      <span style={{ opacity: cursor ? 1 : 0, marginLeft: 2, color: "var(--accent)" }}>▍</span>
    </span>
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

  // Initial guess matches the container's CSS height (260). Actual
  // dimensions are measured via ResizeObserver below; this default just
  // avoids a one-frame flash at the old taller size.
  const [size, setSize] = React.useState({ w: 720, h: 260 });
  const gRef = React.useRef<HTMLDivElement>(null);

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

  React.useEffect(() => {
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setSize({ w: e.contentRect.width, h: e.contentRect.height });
    });
    if (gRef.current) ro.observe(gRef.current);
    return () => ro.disconnect();
  }, [fullscreen]);

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
  // Pre-revamp Dashboard rendered the daily quote right under the greeting
  // (italic, muted). Restoring that placement — the "Inspired learning"
  // label + card are gone; the quote now IS the subtitle.
  const subtitle = quote ? (
    <span style={{ fontStyle: "italic" }}>"{quote}"</span>
  ) : null;

  const courseProgress = React.useMemo(() => {
    return courses.map(c => {
      const courseNodes = nodes.filter(n => n.course_id === c.course_id && !n.is_subject_root);
      const mastered = courseNodes.filter(n => n.mastery_tier === "mastered").length;
      const total = courseNodes.length;
      return {
        course: c,
        mastered,
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
    <div className="card" style={{ padding: 0, overflow: "hidden", position: "relative", minHeight: 340 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 22px", borderBottom: "1px solid var(--border)" }}>
        <div>
          <div className="label-micro">Your knowledge graph</div>
          <div className="h-serif" style={{ fontSize: 20, marginTop: 2 }}>
            {stats.total || nodes.filter((n) => !n.is_subject_root).length} concepts across {courses.length} courses
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          {courses.slice(0, 5).map((c) => (
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
      <div ref={gRef} style={{ position: "relative", height: 260 }}>
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

  // Pre-revamp layout: 3 columns — courses + upcoming on the left,
  // graph in the middle (primary focus), stats on the right.
  const coursesPanel = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
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
        {courseProgress.map(({ course, mastered, total, progress }) => (
          <div key={course.course_id} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, marginBottom: 4 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: course.color || "var(--accent)", flexShrink: 0 }} />
                <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {course.course_code || course.course_name}
                </strong>
              </span>
              <span className="mono" style={{ color: "var(--text-dim)", fontSize: 11, flexShrink: 0, marginLeft: 8 }}>
                {mastered}/{total}
              </span>
            </div>
            <div style={{ height: 6, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden" }}>
              <div style={{
                width: "100%", height: "100%",
                background: course.color || "var(--accent)",
                transformOrigin: "left",
                transform: `scaleX(${progress})`,
                transition: "transform var(--dur) var(--ease)",
              }} />
            </div>
          </div>
        ))}
      </div>

      {/* Upcoming assignments live in the left column now, directly under
          the courses they belong to — feels more like a study planner. */}
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
          let label = `${days}d`;
          if (hours <= 0) { chipClass = "chip--err"; label = "overdue"; }
          else if (hours <= 24) { chipClass = "chip--err"; label = hours < 1 ? "now" : `${Math.max(1, Math.round(hours))}h`; }
          else if (days <= 2) chipClass = "chip--warn";
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

  const graphPanel = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
      {graphBlock}
    </div>
  );

  const rightPanel = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 8 }}>This week</div>
        {/* Prose-style streak line — typographic hierarchy replaces the
            hero-metric layout (big-number + small-label) called out as
            an anti-reference in .impeccable.md. */}
        <div className="body-serif" style={{ fontSize: 16, marginBottom: 14, color: "var(--text)" }}>
          {stats.streak > 0 ? (
            <>You're on a <span className="h-serif" style={{ color: "var(--warn)", fontWeight: 600 }}>{stats.streak}-day</span> streak.</>
          ) : (
            <>Ready when you are. Open any session to begin a streak.</>
          )}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6 }}>
          {weekDays.map(d => {
            const key = d.toISOString().slice(0, 10);
            const active = activeDays.has(key);
            const isToday = d.getTime() === today.getTime();
            return (
              <div key={key} style={{ textAlign: "center" }}>
                <div className="label-micro" style={{ fontSize: 9 }}>
                  {d.toLocaleDateString("en-US", { weekday: "short" }).slice(0, 2)}
                </div>
                <div
                  style={{
                    marginTop: 4, height: 28, borderRadius: "var(--r-sm)",
                    background: isToday ? "var(--warn)" : active ? "var(--accent-soft)" : "var(--bg-soft)",
                    color: isToday ? "#fff" : active ? "var(--accent)" : "var(--text-muted)",
                    display: "grid", placeItems: "center", fontSize: 13,
                    border: isToday ? "1px solid var(--warn)" : "1px solid var(--border)",
                  }}
                >
                  {active ? "🔥" : d.getDate()}
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
      <TopBar
        breadcrumb="Home / Dashboard"
        title={<Typewriter text={greetingText} />}
        subtitle={subtitle}
        actions={
          <>
            <button className="btn btn--sm" onClick={() => router.push("/library")}>
              <Icon name="search" size={13} /> Library
            </button>
            <button className="btn btn--sm btn--primary" onClick={() => router.push("/learn")}>
              <Icon name="sparkle" size={13} /> Start learning
            </button>
          </>
        }
      />

      {suggestNode && !suggestDismissed && (
        <div style={{ padding: "14px 32px 0" }}>
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
        </div>
      )}

      {isMobile && (
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

      <div
        style={{
          padding: isMobile ? "14px 20px" : "20px 32px",
          display: "grid", gap: 20,
          // Pre-revamp layout: narrow left (courses), wide middle (graph),
          // narrow right (stats/upcoming/learn-next). Matches the 300px /
          // flex 1 / 320px split from main@929658f.
          gridTemplateColumns: isMobile ? "1fr" : "minmax(240px, 280px) minmax(0, 1fr) minmax(240px, 300px)",
        }}
      >
        {isMobile ? (
          mobileTab === "courses" ? (
            <>
              {coursesPanel}
              {graphPanel}
            </>
          ) : (
            rightPanel
          )
        ) : (
          <>
            {coursesPanel}
            {graphPanel}
            {rightPanel}
          </>
        )}
      </div>

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
