"use client";
/**
 * Home (Sapling Home v2): greeting, deadline pills, Up Next + Quick Reviews,
 * an editable quote, the knowledge graph / family tree, and a right column
 * with level + streak, Last Session, Roadmap, Recent Notes and Coming Up.
 *
 * Every value is derived from data loaded here (see `home/homeModel.ts`):
 * graph, courses, upcoming assignments, sessions, recommendations, plus the
 * best-effort extras (gamification, activity, flashcards, notes).
 */
import React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Icon } from "../Icon";
import { ManageCoursesModal } from "../ManageCoursesModal";
import { Skeleton } from "../Skeleton";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { useVisibleNavSections } from "@/lib/useNavSections";
import {
  getGraph,
  getCourses,
  getUpcomingAssignments,
  getSessions,
  getRecommendations,
  fetchActivity,
  fetchGamificationMe,
  getFlashcards,
  listNotes,
  type EnrolledCourse,
  type Session,
  type Assignment,
} from "@/lib/api";
import type { GamificationMe, GraphNode as ApiNode, GraphEdge as ApiEdge, Note } from "@/lib/types";
import { apiToGraphNode, learnHrefForNode, type GraphNode, type GraphEdge } from "@/lib/data";
import { now } from "@/lib/testMode";
import { buildQuizHref } from "@/lib/quiz/source";
import { KnowledgeGraph } from "../graph/KnowledgeGraph";
import { CoursesKey, courseProgressFor } from "../graph/CoursesKey";
import { useScrollLock } from "@/lib/useScrollLock";
import { Chevron, ComingUp, LastSession, LevelStreak, RecentNotes, Roadmap, type LevelInfo } from "../home/HomeAside";
import {
  DEFAULT_QUOTE,
  buildPrereqs,
  courseFocus,
  dueAtMs,
  dueDateParts,
  dueReviewConcepts,
  editedLabel,
  examRow,
  goalRow,
  greetingPrefix,
  hexToRgb,
  isExam,
  localDayKey,
  notificationPills,
  quoteStorageKey,
  sessionDayLabel,
  splitQuote,
  weekDaysOf,
  type CardLike,
  type CourseFocus,
  type DatedAssignment,
  type RoadmapRow,
} from "../home/homeModel";
import styles from "../home/Home.module.css";

const hasDueDate = (a: Assignment): a is DatedAssignment => !!a.due_date;

function apiToGraphEdge(e: ApiEdge): GraphEdge {
  return { source: e.source as string, target: e.target as string, strength: e.strength, relationship_type: e.relationship_type };
}

const DIVIDER = "1px solid rgba(42,39,31,0.10)";

/** One of the two action cards (Up Next, Quick Reviews). */
function ActionCard(props: {
  testId: string; label: string; title: string; href: string; icon: React.ReactNode;
  bg: string; border: string; accent: string; linkClass: string;
}) {
  return (
    <div
      data-testid={props.testId}
      style={{
        flex: "0 1 320px", minWidth: 0, boxSizing: "border-box", display: "flex", alignItems: "center", gap: 14, height: 68,
        padding: "0 16px 0 18px", border: `1px solid ${props.border}`, borderRadius: 14, background: props.bg, color: "#1A1814",
      }}
    >
      <span style={{ color: props.accent, display: "flex", flexShrink: 0, transform: "translateY(-3px)" }}>{props.icon}</span>
      <span style={{ flex: "1 1 0%", minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ height: 14, fontSize: 12, lineHeight: "14px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: props.accent }}>
          {props.label}
        </span>
        <span style={{ height: 22, fontSize: 17, lineHeight: "22px", fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {props.title}
        </span>
      </span>
      <Link href={props.href} className={props.linkClass} style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
        <span style={{ fontSize: 14, lineHeight: "14px", fontWeight: 700, whiteSpace: "nowrap" }}>Study</span>
        <Chevron />
      </Link>
    </div>
  );
}

const TargetIcon = (
  <svg width="32" height="32" viewBox="0 0 14 14" aria-hidden="true">
    <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
    <circle cx="7" cy="7" r="2.2" fill="currentColor" />
  </svg>
);
const CardsIcon = (
  <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M7 3h11a2 2 0 0 1 2 2v11h-2V5H7z" />
    <path d="M4 7h11a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
  </svg>
);

function HomeSkeleton({ isMobile }: { isMobile: boolean }) {
  return (
    <div
      data-testid="home-skeleton"
      style={{
        display: "grid", gap: isMobile ? 24 : 56, gridTemplateColumns: isMobile ? "1fr" : "minmax(0, 1fr) 380px",
        padding: isMobile ? "20px 16px" : "36px 56px 0 64px", minHeight: "100%", boxSizing: "border-box", background: "#FAF8F3",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Skeleton width="40%" height={38} />
        <Skeleton width={360} height={44} radius={22} />
        <Skeleton width={660} height={68} radius={14} />
        <Skeleton height={isMobile ? 360 : 640} radius={14} style={{ marginTop: 22 }} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        <Skeleton width={160} height={24} />
        <Skeleton height={68} radius={14} />
        <Skeleton height={140} radius={14} />
        <Skeleton height={120} radius={14} />
      </div>
    </div>
  );
}

export function Dashboard() {
  const router = useRouter();
  const search = useSearchParams();
  const { userId, userName, userReady } = useUser();
  const [activeSemester, , semesterHydrated] = useActiveSemester();
  const isMobile = useIsMobile();
  const navSections = useVisibleNavSections();
  const visibleHrefs = React.useMemo(() => new Set(navSections.flatMap((s) => s.items.map((i) => i.href))), [navSections]);
  const canStudy = visibleHrefs.has("/study");
  const canNotes = visibleHrefs.has("/notetaker");
  const canCalendar = visibleHrefs.has("/calendar");

  const [nodes, setNodes] = React.useState<GraphNode[]>([]);
  const [edges, setEdges] = React.useState<GraphEdge[]>([]);
  const [streak, setStreak] = React.useState(0);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [sessions, setSessions] = React.useState<Session[]>([]);
  const [assignments, setAssignments] = React.useState<DatedAssignment[]>([]);
  const [recommendations, setRecommendations] = React.useState<{ concept_name: string; reason?: string }[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  // Best-effort extras: the screen renders without any of them.
  const [me, setMe] = React.useState<GamificationMe | null>(null);
  const [xpDays, setXpDays] = React.useState<Set<string>>(new Set());
  const [cards, setCards] = React.useState<CardLike[] | null>(null);
  const [notes, setNotes] = React.useState<Note[]>([]);
  const [extrasKey, setExtrasKey] = React.useState(0);

  const [coursesOpen, setCoursesOpen] = React.useState(false);
  const [fullscreen, setFullscreen] = React.useState(false);
  // The "My courses" key and the graph, wired together (the original Home
  // graph): hovering a course row fades the other courses; hovering a concept
  // lights its course's row; clicking a row zooms the graph to that course,
  // clicking it again zooms back out.
  const [keyHoverCourse, setKeyHoverCourse] = React.useState<string | null>(null);
  const [graphHoverCourse, setGraphHoverCourse] = React.useState<string | null>(null);
  const [zoomRequest, setZoomRequest] = React.useState<{ courseId: string | null; seq: number } | null>(null);
  const zoomedCourse = zoomRequest?.courseId ?? null;
  const zoomToCourse = (courseId: string) =>
    setZoomRequest((r) => ({ courseId: r?.courseId === courseId ? null : courseId, seq: (r?.seq ?? 0) + 1 }));

  // Client-only clock (no SSR/CSR drift); test mode pins it via now().
  const [nowMs, setNowMs] = React.useState<number>(0);
  React.useEffect(() => { setNowMs(now()); }, []);
  const [greeting, setGreeting] = React.useState("Welcome back");
  React.useEffect(() => { setGreeting(greetingPrefix(new Date(now()))); }, []);

  // ── Quote: per-user, in this browser ──
  const [quote, setQuote] = React.useState<string | null>(null);
  const [quoteEditing, setQuoteEditing] = React.useState(false);
  const [quoteDraft, setQuoteDraft] = React.useState("");
  React.useEffect(() => {
    if (!userId) return;
    try { setQuote(window.localStorage.getItem(quoteStorageKey(userId))); } catch { setQuote(null); }
  }, [userId]);
  const saveQuote = (q: string) => {
    setQuote(q);
    setQuoteEditing(false);
    if (!userId) return;
    try { window.localStorage.setItem(quoteStorageKey(userId), q); } catch { /* private mode: keeps for this view */ }
  };
  const shownQuote = quote ?? DEFAULT_QUOTE;

  // ── Graph size ──
  const [size, setSize] = React.useState({ w: 720, h: 420 });
  const roRef = React.useRef<ResizeObserver | null>(null);
  const graphRef = React.useCallback((el: HTMLDivElement | null) => {
    roRef.current?.disconnect();
    roRef.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        if (e.contentRect.width > 0 && e.contentRect.height > 0) setSize({ w: e.contentRect.width, h: e.contentRect.height });
      }
    });
    ro.observe(el);
    roRef.current = ro;
  }, []);

  const suggest = search.get("suggest");
  const [suggestDismissed, setSuggestDismissed] = React.useState(false);
  React.useEffect(() => { setSuggestDismissed(false); }, [suggest]);

  // Latest load wins (#769): a semester switch mid-flight must not let the
  // OLDER reply repaint the screen.
  const loadReq = useLatestRequest();
  const load = React.useCallback(async () => {
    if (!userId) return;
    const run = loadReq.begin();
    setExtrasKey((k) => k + 1);
    setLoading(true);
    setLoadError(null);
    try {
      // Empty `activeSemester` = "All semesters" (the default): unscoped (#360).
      const [graphRes, coursesRes, assignsRes, sessionsRes, recsRes] = await Promise.all([
        getGraph(userId, activeSemester || undefined),
        getCourses(userId),
        getUpcomingAssignments(userId),
        getSessions(userId, 10),
        getRecommendations(userId, activeSemester || undefined).catch(() => ({ recommendations: [] })),
      ]);
      if (!run.isCurrent()) return;
      const cs = coursesRes.courses || [];
      setCourses(cs);
      setNodes((graphRes.nodes || []).map((n: ApiNode) => apiToGraphNode(n, cs)));
      setEdges((graphRes.edges || []).map(apiToGraphEdge));
      setStreak(graphRes.stats?.streak ?? 0);
      // Undated rows can't be placed on a calendar (or dated 1970): drop them.
      setAssignments((assignsRes.assignments || []).filter(hasDueDate));
      setSessions(sessionsRes.sessions || []);
      setRecommendations(recsRes.recommendations || []);
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("dashboard load failed", err);
      setLoadError(String(err));
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
  }, [userId, activeSemester, loadReq]);

  React.useEffect(() => {
    if (userReady && userId && semesterHydrated) load();
  }, [userReady, userId, semesterHydrated, load]);

  useScrollLock(fullscreen);
  React.useEffect(() => {
    if (!fullscreen) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [fullscreen]);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    (async () => {
      const [activity, meRes, cardsRes, notesRes] = await Promise.all([
        fetchActivity(userId).catch(() => null),
        fetchGamificationMe(userId).catch(() => null),
        getFlashcards(userId, undefined, activeSemester || undefined).catch(() => null),
        listNotes(userId).catch(() => null),
      ]);
      if (cancelled) return;
      setXpDays(new Set((activity?.week ?? []).filter((d) => d.xp > 0).map((d) => d.date)));
      setMe(meRes);
      setCards(cardsRes ? (cardsRes.flashcards as CardLike[]) : null);
      setNotes(notesRes?.notes ?? []);
    })();
    return () => { cancelled = true; };
  }, [userReady, userId, extrasKey, activeSemester]);

  // ── Derived ──
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter((c) => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );
  const concepts = React.useMemo(() => nodes.filter((n) => !n.is_subject_root), [nodes]);
  const byId = React.useMemo(() => new Map(concepts.map((n) => [n.id, n])), [concepts]);
  const prereqs = React.useMemo(() => buildPrereqs(concepts, edges), [concepts, edges]);
  const courseLabel = React.useCallback((id: string | null | undefined) => {
    const c = id ? courses.find((co) => co.course_id === id) : undefined;
    return c ? c.course_code || c.course_name : null;
  }, [courses]);

  const courseProgress = React.useMemo(() => courseProgressFor(scopedCourses, nodes), [scopedCourses, nodes]);

  const homeCourses = React.useMemo<HomeCourse[]>(() => {
    const list: HomeCourse[] = scopedCourses.map((c) => ({
      id: c.course_id, code: c.course_code || c.course_name, name: c.course_name === c.course_code ? "" : c.course_name,
      rgb: hexToRgb(c.color || concepts.find((n) => n.course_id === c.course_id)?.color),
    }));
    // Concepts whose course isn't in the enrolled list still get a hub.
    for (const n of concepts) {
      if (n.course_id && !list.some((c) => c.id === n.course_id)) {
        list.push({ id: n.course_id, code: n.subject || "Course", name: "", rgb: hexToRgb(n.color) });
      }
    }
    return list;
  }, [scopedCourses, concepts]);

  const focusByCourse = React.useMemo(() => {
    const m = new Map<string, CourseFocus>();
    for (const c of homeCourses) m.set(c.id, courseFocus(concepts.filter((n) => n.course_id === c.id), prereqs));
    return m;
  }, [homeCourses, concepts, prereqs]);

  const sortedDue = React.useMemo(
    () => [...assignments].filter((a) => !nowMs || dueAtMs(a.due_date) >= nowMs).sort((a, b) => dueAtMs(a.due_date) - dueAtMs(b.due_date)),
    [assignments, nowMs],
  );

  // The course the screen is "about": nearest exam, else most recent study, else the biggest.
  const primaryCourse = React.useMemo(() => {
    const withConcepts = homeCourses.filter((c) => concepts.some((n) => n.course_id === c.id));
    if (!withConcepts.length) return homeCourses[0]?.id ?? null;
    const exam = sortedDue.find((a) => isExam(a) && withConcepts.some((c) => c.id === a.course_id));
    if (exam?.course_id) return exam.course_id;
    const recent = [...concepts].filter((n) => n.last_studied_at).sort((a, b) => (b.last_studied_at as string).localeCompare(a.last_studied_at as string))[0];
    if (recent && withConcepts.some((c) => c.id === recent.course_id)) return recent.course_id;
    return [...withConcepts].sort((a, b) => concepts.filter((n) => n.course_id === b.id).length - concepts.filter((n) => n.course_id === a.id).length)[0].id;
  }, [homeCourses, concepts, sortedDue]);

  const primaryFocus = primaryCourse ? focusByCourse.get(primaryCourse) : undefined;

  const studyHref = (courseId?: string | null) =>
    canStudy ? (courseId ? `/study?course=${encodeURIComponent(courseId)}` : "/study") : "/learn";

  // Up Next: the primary course's next step, else the shakiest concept, else a recommendation.
  const upNext = React.useMemo(() => {
    const here = primaryFocus?.hereId ? byId.get(primaryFocus.hereId) : undefined;
    if (here) return { name: here.name, courseId: here.course_id };
    const weak = [...concepts]
      .filter((n) => n.mastery_tier === "struggling" || n.mastery_tier === "learning")
      .sort((a, b) => a.mastery_score - b.mastery_score)[0];
    if (weak) return { name: weak.name, courseId: weak.course_id };
    if (recommendations[0]) return { name: recommendations[0].concept_name, courseId: null };
    return null;
  }, [primaryFocus, byId, concepts, recommendations]);

  const reviewCount = cards && nowMs ? dueReviewConcepts(cards, nowMs) : null;
  const pills = nowMs ? notificationPills(assignments, nowMs) : [];

  const roadmap = React.useMemo<RoadmapRow[]>(() => {
    const rows: RoadmapRow[] = [];
    if (primaryFocus) {
      const g = goalRow(primaryFocus, byId, prereqs);
      if (g) rows.push(g);
    }
    const exams = sortedDue.filter((a) => isExam(a) && a.course_id).slice(0, 3);
    for (const ex of exams) {
      if (rows.length >= 2) break;
      const r = examRow(ex, concepts.filter((n) => n.course_id === ex.course_id), courseLabel(ex.course_id));
      if (r) rows.push(r);
    }
    return rows;
  }, [primaryFocus, byId, prereqs, sortedDue, concepts, courseLabel]);

  const level: LevelInfo | null = me
    ? { level: me.level, have: me.xp_into_level, need: me.xp_for_level, pct: Math.max(0, Math.min(100, Math.round(me.level_pct))) }
    : null;

  const week = React.useMemo(() => {
    const days = new Set<string>(xpDays);
    for (const n of concepts) { const k = localDayKey(n.last_studied_at); if (k) days.add(k); }
    for (const s of sessions) for (const iso of [s.started_at, s.ended_at]) { const k = localDayKey(iso); if (k) days.add(k); }
    const letters = ["M", "T", "W", "T", "F", "S", "S"];
    return weekDaysOf(new Date(nowMs || 0)).map((d, i) => {
      const key = localDayKey(d) as string;
      return { d: letters[i], key, done: days.has(key) };
    });
  }, [xpDays, concepts, sessions, nowMs]);

  const lastSession = React.useMemo(() => {
    const s = sessions[0];
    if (!s) return null;
    const match = concepts.find((n) => n.name.toLowerCase() === s.topic.toLowerCase() && (!s.course_id || n.course_id === s.course_id))
      ?? concepts.find((n) => n.name.toLowerCase() === s.topic.toLowerCase());
    return {
      id: s.id,
      topic: s.topic,
      day: nowMs ? sessionDayLabel(s.ended_at ?? s.started_at, nowMs) : "",
      tier: match?.mastery_tier ?? null,
      href: `/learn?resume=${encodeURIComponent(s.id)}`,
    };
  }, [sessions, concepts, nowMs]);

  const noteRows = React.useMemo(
    () => [...notes]
      .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""))
      .slice(0, 2)
      .map((n) => ({
        id: n.id,
        title: n.title?.trim() || "Untitled note",
        meta: [courseLabel(n.course_id), nowMs ? editedLabel(n.updated_at, nowMs) : ""].filter(Boolean).join(" · "),
      })),
    [notes, courseLabel, nowMs],
  );

  const comingUp = sortedDue.slice(0, 4).map((a) => {
    const p = dueDateParts(a.due_date);
    const hub = homeCourses.find((h) => h.id === a.course_id);
    const c = courses.find((co) => co.course_id === a.course_id);
    return {
      id: a.id, dow: p.dow, day: p.day, title: a.title,
      course: a.course_code || a.course_name || courseLabel(a.course_id) || "",
      color: `rgb(${hub?.rgb ?? hexToRgb(c?.color)})`,
      exam: isExam(a),
    };
  });

  const suggestNode = suggest ? concepts.find((n) => n.name.toLowerCase() === suggest.toLowerCase()) ?? null : null;
  const dismissSuggest = () => {
    setSuggestDismissed(true);
    const next = new URLSearchParams(search.toString());
    next.delete("suggest");
    const qs = next.toString();
    router.replace(qs ? `/dashboard?${qs}` : "/dashboard");
  };

  if (loading && !courses.length) return <HomeSkeleton isMobile={isMobile} />;

  if (loadError && !courses.length) {
    return (
      <div style={{ padding: 32, background: "#FAF8F3", minHeight: "100%" }}>
        <h1 style={{ margin: 0, fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 600 }}>Couldn&apos;t load your home</h1>
        <div style={{ color: "#8E2F29", margin: "10px 0", fontSize: 14 }}>{loadError}</div>
        <button type="button" data-testid="home-retry" className="btn btn--primary" onClick={load}>Retry</button>
      </div>
    );
  }

  const firstName = userName ? userName.split(" ")[0] : "";
  const { text: quoteText, by: quoteBy } = splitQuote(shownQuote);

  const header = (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: isMobile ? 18 : 40, maxWidth: 1164, flexWrap: isMobile ? "wrap" : "nowrap" }}>
      <div style={{ flex: "1 1 612px", minWidth: 0 }}>
        <h1 style={{ margin: 0, fontFamily: "var(--font-serif)", fontSize: 34, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.15 }}>
          {firstName ? `${greeting}, ${firstName}` : "Welcome back"}
        </h1>
        {pills.length > 0 && (
          <div data-testid="home-pills" style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
            {pills.map((p) => (
              <Link
                key={p.id}
                href={studyHref(p.courseId)}
                data-testid={`home-pill-${p.kind}`}
                className={p.kind === "exam" ? styles.pillExam : styles.pillDeadline}
                style={{
                  display: "flex", alignItems: "center", gap: 10, height: 44, padding: "0 16px 0 6px", borderRadius: 22,
                  fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", textDecoration: "none", boxSizing: "border-box",
                }}
              >
                <span style={{ width: 32, height: 32, borderRadius: "50%", background: "#FFFFFF", color: p.kind === "exam" ? "#B23A33" : "#8A6420", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <Icon name={p.kind === "exam" ? "nofitication" : "calendar"} size={15} />
                </span>
                <span>{p.text}</span>
              </Link>
            ))}
          </div>
        )}
        <section aria-label="Study plan" style={{ marginTop: 18, display: "flex", flexWrap: isMobile ? "wrap" : "nowrap", gap: 12 }}>
          <ActionCard
            testId="home-up-next" label="Up Next" title={upNext?.name ?? "Start your first session"}
            href={upNext ? studyHref(upNext.courseId) : "/learn"} icon={TargetIcon}
            bg="#EBF0E1" border="#D3DEC2" accent="#445D22" linkClass={styles.link}
          />
          <ActionCard
            testId="home-quick-reviews" label="Quick Reviews"
            title={reviewCount === null ? "Flashcards" : reviewCount === 0 ? "All Caught Up" : `${reviewCount} ${reviewCount === 1 ? "Concept" : "Concepts"}`}
            href={canStudy ? "/study?mode=cards" : "/learn"} icon={CardsIcon}
            bg="#E8F0F8" border="#C9D9EC" accent="#2E5F96" linkClass={styles.linkBlue}
          />
        </section>
      </div>
      <figure style={{ margin: 0, flex: "0 1 400px", minWidth: 0, paddingLeft: 16, borderLeft: DIVIDER }}>
        {!quoteEditing ? (
          <>
            <blockquote
              data-testid="home-quote"
              role="button"
              tabIndex={0}
              onClick={() => { setQuoteDraft(shownQuote); setQuoteEditing(true); }}
              onKeyDown={(e) => { if (e.key === "Enter") { setQuoteDraft(shownQuote); setQuoteEditing(true); } }}
              title="Click to change your quote"
              style={{
                margin: 0, fontFamily: "var(--font-serif)", fontSize: 15, fontStyle: "italic",
                color: shownQuote ? "#3F3B31" : "#8A8372", lineHeight: 1.5, cursor: "text", textWrap: "pretty",
              } as React.CSSProperties}
            >
              {shownQuote ? quoteText : "Add a quote that keeps you going"}
            </blockquote>
            {quoteBy && (
              <figcaption style={{ marginTop: 6, paddingLeft: 7, textAlign: "left", fontSize: 13, fontWeight: 600, letterSpacing: "0.02em", color: "#7A9A4E" }}>
                {quoteBy}
              </figcaption>
            )}
          </>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <input
              data-testid="home-quote-input"
              autoFocus
              value={quoteDraft}
              onChange={(e) => setQuoteDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveQuote(quoteDraft.trim());
                if (e.key === "Escape") setQuoteEditing(false);
              }}
              placeholder="Type a quote that keeps you going"
              aria-label="Your quote"
              style={{
                height: 34, padding: "0 10px", border: "1px solid rgba(42,39,31,0.22)", borderRadius: 8, background: "#FDFCF9",
                fontFamily: "var(--font-serif)", fontSize: 15, fontStyle: "italic", color: "#1A1814", outlineColor: "#597536",
              }}
            />
            <div style={{ display: "flex", gap: 6 }}>
              <button type="button" data-testid="home-quote-save" onClick={() => saveQuote(quoteDraft.trim())} className={styles.primary}
                style={{ height: 30, padding: "0 12px", border: 0, background: "#445D22", color: "#FFFFFF", borderRadius: 8, fontFamily: "inherit", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
                Save
              </button>
              <button type="button" data-testid="home-quote-cancel" onClick={() => setQuoteEditing(false)}
                style={{ height: 30, padding: "0 8px", border: 0, background: "transparent", color: "#3F3B31", fontFamily: "inherit", fontSize: 13, cursor: "pointer" }}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </figure>
    </div>
  );

  const graphSection = (
    <section aria-label="Knowledge graph" style={{ flex: 1, minHeight: isMobile ? 520 : 0, marginTop: 22, marginBottom: 24, display: "flex", flexDirection: "column", gap: 12, maxWidth: 1164 }}>
      {suggestNode && !suggestDismissed && (
        <div
          data-testid="home-suggest"
          style={{ padding: "10px 14px", display: "flex", gap: 12, alignItems: "center", borderRadius: 14, background: "#EBF0E1", border: "1px solid #D3DEC2", fontSize: 14 }}
        >
          <div style={{ flex: 1 }}><strong>Try this next:</strong> {suggestNode.name}</div>
          <button
            type="button"
            data-testid="home-suggest-quiz"
            className={styles.primary}
            onClick={() => router.push(buildQuizHref({ concept: suggestNode.id }, { kind: "dashboard", returnTo: "/dashboard" }))}
            style={{ height: 30, padding: "0 12px", border: 0, background: "#445D22", color: "#FFFFFF", borderRadius: 8, fontFamily: "inherit", fontSize: 13, fontWeight: 700, cursor: "pointer" }}
          >
            Start quiz
          </button>
          <button type="button" data-testid="home-suggest-dismiss" onClick={dismissSuggest} style={{ height: 30, padding: "0 8px", border: 0, background: "transparent", color: "#3F3B31", fontFamily: "inherit", fontSize: 13, cursor: "pointer" }}>
            Dismiss
          </button>
        </div>
      )}
      {/* The original Home knowledge graph (KnowledgeGraph + the CoursesKey
          overlay and its own controls) on the original white panel, boxed by
          the v3 divider hairline with the heading row over a divider. */}
      <div
        data-testid="home-graph-panel"
        style={{ position: "relative", minHeight: 420, display: "flex", flexDirection: "column", flex: 1, background: "var(--bg-panel)", boxShadow: "var(--shadow-sm)", border: DIVIDER, borderRadius: 14, overflow: "hidden" }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "12px 18px", borderBottom: DIVIDER }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, minWidth: 0 }}>
            <span style={{ fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 600, whiteSpace: "nowrap" }}>Knowledge Graph</span>
            <span style={{ fontSize: 14, color: "#6F6857", whiteSpace: "nowrap" }}>
              {concepts.length} concepts across {scopedCourses.length} courses
            </span>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <button
              type="button"
              data-testid="dashboard-courses-manage"
              className="btn btn--ghost btn--sm"
              onClick={() => setCoursesOpen(true)}
            >
              Courses &amp; Semesters
            </button>
            <button
              type="button"
              data-testid="home-graph-fullscreen"
              className="btn btn--ghost btn--sm"
              onClick={() => setFullscreen(true)}
              aria-label="Fullscreen graph"
            >
              <Icon name="max" size={12} />
            </button>
          </div>
        </div>
        <div ref={graphRef} style={{ position: "relative", flex: 1, minHeight: 260 }}>
          <KnowledgeGraph
            legible
            nodes={nodes}
            edges={edges}
            width={size.w}
            height={size.h}
            highlightId={suggestNode?.id}
            onNodeClick={(n) => router.push(learnHrefForNode(n))}
            focusCourseId={keyHoverCourse ?? zoomedCourse}
            onHoverCourse={setGraphHoverCourse}
            zoomRequest={zoomRequest}
          />
          <CoursesKey
            courseProgress={courseProgress}
            activeCourseId={keyHoverCourse ?? graphHoverCourse}
            onHoverCourse={setKeyHoverCourse}
            selectedCourseId={zoomedCourse}
            onSelectCourse={zoomToCourse}
            selectHint="Click to zoom to this course, again to zoom out"
          />
        </div>
      </div>
    </section>
  );

  const aside = (
    <aside style={{ display: "flex", flexDirection: "column", gap: 22, minHeight: 0, paddingTop: 6, paddingBottom: 24 }}>
      <LevelStreak level={level} streak={me?.streak ?? streak} best={me ? me.longest_streak : null} week={week} />
      <LastSession session={lastSession} />
      <Roadmap rows={roadmap} />
      {canNotes && <RecentNotes notes={noteRows} />}
      <ComingUp rows={comingUp} showCalendar={canCalendar} />
    </aside>
  );

  return (
    <div
      data-testid="home"
      style={{
        minHeight: "100%", height: isMobile ? undefined : "100%", boxSizing: "border-box", background: "#FAF8F3", color: "#1A1814",
        fontFamily: "var(--font-sans)", fontSize: 15, lineHeight: 1.45,
        display: "grid", gridTemplateColumns: isMobile ? "minmax(0, 1fr)" : "minmax(0, 1fr) 380px", gap: isMobile ? 28 : 56,
        padding: isMobile ? "20px 16px 24px" : "36px 56px 0 64px",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: isMobile ? undefined : 760 }}>
        {header}
        {graphSection}
      </div>
      {aside}
      {fullscreen && (
        <div style={{ position: "fixed", inset: 0, zIndex: 150, background: "var(--bg)", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
            <div>
              <div className="label-micro">Knowledge graph · fullscreen</div>
              <div className="h-serif" style={{ fontSize: 18 }}>Press Esc to exit</div>
            </div>
            <button type="button" data-testid="home-graph-fullscreen-close" className="btn btn--ghost btn--sm" onClick={() => setFullscreen(false)} aria-label="Exit fullscreen">
              <Icon name="x" size={14} />
            </button>
          </div>
          <FullscreenGraph
            nodes={nodes}
            edges={edges}
            highlightId={suggestNode?.id}
            onNodeClick={(n) => { setFullscreen(false); router.push(learnHrefForNode(n)); }}
          />
        </div>
      )}
      <ManageCoursesModal open={coursesOpen} userId={userId} courses={courses} onClose={() => setCoursesOpen(false)} onChanged={load} />
    </div>
  );
}

type HomeCourse = { id: string; code: string; name: string; rgb: string };

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
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => setSize({ w: e[0].contentRect.width, h: e[0].contentRect.height }));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} style={{ flex: 1, position: "relative" }}>
      <KnowledgeGraph legible nodes={nodes} edges={edges} width={size.w} height={size.h} highlightId={highlightId} onNodeClick={onNodeClick} />
    </div>
  );
}
