"use client";
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Pill } from "../Pill";
import { KnowledgeGraph } from "../KnowledgeGraph";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { getGraph, getCourses, getSessions, type EnrolledCourse, type Session } from "@/lib/api";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "@/lib/types";
import type { GraphNode, GraphEdge } from "@/lib/data";

type Tier = "all" | "mastered" | "learning" | "struggling" | "unexplored";

const TIER_META: Record<Exclude<Tier, "all">, { label: string; color: string }> = {
  mastered: { label: "Mastered", color: "#4a7d5c" },
  learning: { label: "Learning", color: "#c89b5e" },
  struggling: { label: "Struggling", color: "#b25855" },
  unexplored: { label: "Unexplored", color: "#9a9a9a" },
};

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

export function Tree() {
  const router = useRouter();
  const search = useSearchParams();
  const { userId, userReady } = useUser();
  const isMobile = useIsMobile();
  const suggest = search.get("suggest");

  const [courseFilter, setCourseFilter] = React.useState<string>("all");
  const [tier, setTier] = React.useState<Tier>("all");
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<GraphNode | null>(null);
  const [fullscreen, setFullscreen] = React.useState(false);

  const [size, setSize] = React.useState({ w: 900, h: 600 });
  const ref = React.useRef<HTMLDivElement>(null);

  const [nodes, setNodes] = React.useState<GraphNode[]>([]);
  const [edges, setEdges] = React.useState<GraphEdge[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [sessions, setSessions] = React.useState<Session[]>([]);

  React.useEffect(() => {
    const ro = new ResizeObserver((e) => setSize({ w: e[0].contentRect.width, h: e[0].contentRect.height }));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, [fullscreen]);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    (async () => {
      try {
        const [graphRes, coursesRes, sessionsRes] = await Promise.all([
          getGraph(userId),
          getCourses(userId),
          getSessions(userId, 50).catch(() => ({ sessions: [] })),
        ]);
        if (cancelled) return;
        const cs = coursesRes.courses || [];
        setCourses(cs);
        setNodes((graphRes.nodes || []).map((n: ApiNode) => apiToGraphNode(n, cs)));
        setEdges(
          (graphRes.edges || []).map((e: ApiEdge) => ({
            source: e.source as string,
            target: e.target as string,
            strength: e.strength,
          })),
        );
        setSessions(sessionsRes.sessions || []);
      } catch (err) {
        console.error("tree load failed", err);
      }
    })();
    return () => { cancelled = true; };
  }, [userReady, userId]);

  // Auto-select node matching ?suggest= once data loads.
  React.useEffect(() => {
    if (!suggest || !nodes.length) return;
    const target = nodes.find(n => n.name.toLowerCase() === suggest.toLowerCase());
    if (target) setSelected(target);
  }, [suggest, nodes]);

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

  const filteredNodes = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return nodes.filter(n => {
      if (courseFilter !== "all" && n.course_id !== courseFilter) return false;
      if (tier !== "all" && !n.is_subject_root && n.mastery_tier !== tier) return false;
      if (q && !n.name.toLowerCase().includes(q) && !n.subject.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [nodes, courseFilter, tier, query]);

  const filteredEdges = React.useMemo(() => {
    const ids = new Set(filteredNodes.map(n => n.id));
    return edges.filter(e => ids.has(typeof e.source === "string" ? e.source : "") && ids.has(typeof e.target === "string" ? e.target : ""));
  }, [edges, filteredNodes]);

  const conceptCount = filteredNodes.filter(n => !n.is_subject_root).length;

  const sessionsForSelected = React.useMemo(() => {
    if (!selected) return [];
    const name = selected.name.toLowerCase();
    return sessions.filter(s => (s.topic || "").toLowerCase() === name);
  }, [selected, sessions]);

  const suggestId = React.useMemo(() => {
    if (!suggest) return undefined;
    const n = nodes.find(x => x.name.toLowerCase() === suggest.toLowerCase());
    return n?.id;
  }, [suggest, nodes]);

  const onLearn = (n: GraphNode) => router.push(
    `/learn?topic=${encodeURIComponent(n.name)}&mode=socratic${n.course_id ? `&course_id=${encodeURIComponent(n.course_id)}` : ""}`,
  );
  const onQuiz = (n: GraphNode) => router.push(
    `/learn?topic=${encodeURIComponent(n.name)}&mode=quiz${n.course_id ? `&course_id=${encodeURIComponent(n.course_id)}` : ""}`,
  );

  const detailPanel = selected && (
    <>
      <button className="btn btn--ghost btn--sm" onClick={() => setSelected(null)} aria-label="Close detail panel">
        <Icon name="x" size={12} />
      </button>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
        <span style={{ width: 10, height: 10, borderRadius: "50%", background: selected.color }} />
        <span className="label-micro">{selected.subject}</span>
      </div>
      <h2 className="h-serif" style={{ fontSize: 24, margin: "6px 0 12px", fontWeight: 500 }}>
        {selected.name}
      </h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
        <div className="card" style={{ padding: 12 }}>
          <div className="label-micro">Mastery</div>
          <div className="mono" style={{ fontSize: 22, color: selected.color }}>
            {Math.round((selected.mastery_score || 0) * 100)}%
          </div>
        </div>
        <div className="card" style={{ padding: 12 }}>
          <div className="label-micro">Tier</div>
          <div style={{ fontSize: 14, fontWeight: 500, marginTop: 4, textTransform: "capitalize" }}>
            {selected.mastery_tier}
          </div>
        </div>
      </div>
      <div style={{ marginBottom: 12 }}>
        <div className="label-micro" style={{ marginBottom: 6 }}>Last studied</div>
        <div style={{ fontSize: 13 }}>
          {selected.last_studied_at ? new Date(selected.last_studied_at).toLocaleString() : "never"}
        </div>
      </div>
      <button className="btn btn--primary" style={{ width: "100%" }} onClick={() => onLearn(selected)}>
        <Icon name="brain" size={14} /> Learn this
      </button>
      <button className="btn" style={{ width: "100%", marginTop: 8 }} onClick={() => onQuiz(selected)}>
        <Icon name="bolt" size={14} /> Quick quiz
      </button>
      {sessionsForSelected.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="label-micro" style={{ marginBottom: 8 }}>Sessions for this concept</div>
          {sessionsForSelected.slice(0, 4).map(s => (
            <button
              key={s.id}
              onClick={() => router.push(`/learn?session=${s.id}`)}
              style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                width: "100%", padding: "8px 10px",
                background: "var(--bg-panel)", border: "1px solid var(--border)",
                borderRadius: "var(--r-sm)", marginBottom: 6, textAlign: "left",
              }}
            >
              <div style={{ fontSize: 12, minWidth: 0, overflow: "hidden" }}>
                <div style={{ fontWeight: 500, textTransform: "capitalize" }}>{s.mode}</div>
                <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                  {s.message_count} msgs · {new Date(s.started_at).toLocaleDateString()}
                </div>
              </div>
              <Icon name="chev" size={12} />
            </button>
          ))}
        </div>
      )}
    </>
  );

  return (
    <div>
      <TopBar
        breadcrumb="Home / Tree"
        title="Your Knowledge Tree"
        subtitle="The living map of what you've learned, organized by course."
        actions={
          <button className="btn btn--sm" onClick={() => setFullscreen(true)}>
            <Icon name="max" size={13} /> Fullscreen
          </button>
        }
      />

      <div
        style={{
          padding: "14px 32px",
          display: "flex",
          gap: 10,
          borderBottom: "1px solid var(--border)",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <div style={{ position: "relative", flex: "0 1 260px" }}>
          <Icon name="search" size={13} />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search concepts…"
            style={{
              width: "100%", padding: "5px 10px 5px 28px", fontSize: 12,
              border: "1px solid var(--border)", borderRadius: "var(--r-full)",
              background: "var(--bg-panel)",
            }}
          />
          <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)", pointerEvents: "none" }}>
            <Icon name="search" size={12} />
          </span>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Pill active={tier === "all"} onClick={() => setTier("all")}>All</Pill>
          {(Object.keys(TIER_META) as Array<Exclude<Tier, "all">>).map(t => (
            <Pill key={t} active={tier === t} onClick={() => setTier(t)} color={TIER_META[t].color}>
              {TIER_META[t].label}
            </Pill>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {conceptCount} node{conceptCount === 1 ? "" : "s"}
        </div>
      </div>

      <div
        style={{
          padding: "12px 32px 0",
          display: "flex",
          gap: 8,
          borderBottom: "1px solid var(--border)",
          flexWrap: "wrap",
          paddingBottom: 12,
        }}
      >
        <Pill active={courseFilter === "all"} onClick={() => setCourseFilter("all")}>All courses</Pill>
        {courses.map((c) => (
          <Pill
            key={c.course_id}
            active={courseFilter === c.course_id}
            onClick={() => setCourseFilter(c.course_id)}
            color={c.color || undefined}
          >
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: courseFilter === c.course_id ? "#fff" : c.color || "var(--accent)",
              display: "inline-block",
            }} />
            {c.course_code || c.course_name}
          </Pill>
        ))}
      </div>

      <div style={{ display: "flex", height: "calc(100vh - 240px)" }}>
        <div ref={ref} style={{ flex: 1, minWidth: 0, position: "relative" }}>
          <KnowledgeGraph
            nodes={filteredNodes}
            edges={filteredEdges}
            width={size.w}
            height={size.h}
            highlightId={suggestId || selected?.id}
            masteryTierFill
            onNodeClick={(n) => setSelected(n)}
          />
        </div>
        {selected && !isMobile && (
          <aside
            style={{
              width: 320,
              borderLeft: "1px solid var(--border)",
              padding: 20,
              background: "var(--bg-subtle)",
              overflowY: "auto",
            }}
          >
            {detailPanel}
          </aside>
        )}
      </div>

      {selected && isMobile && (
        <div
          onClick={() => setSelected(null)}
          style={{
            position: "fixed", inset: 0, zIndex: 90, background: "rgba(19,38,16,0.35)",
            display: "flex", flexDirection: "column", justifyContent: "flex-end",
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            className="slide-up"
            style={{
              background: "var(--bg-panel)", borderTopLeftRadius: "var(--r-lg)", borderTopRightRadius: "var(--r-lg)",
              padding: 20, maxHeight: "80vh", overflowY: "auto",
            }}
          >
            {detailPanel}
          </div>
        </div>
      )}

      {fullscreen && (
        <div style={{ position: "fixed", inset: 0, zIndex: 150, background: "var(--bg)", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
            <div>
              <div className="label-micro">Knowledge tree — fullscreen</div>
              <div className="h-serif" style={{ fontSize: 18 }}>Press Esc to exit</div>
            </div>
            <button className="btn btn--ghost btn--sm" onClick={() => setFullscreen(false)}>
              <Icon name="x" size={14} />
            </button>
          </div>
          <FullscreenGraph
            nodes={filteredNodes}
            edges={filteredEdges}
            highlightId={suggestId || selected?.id}
            onNodeClick={(n) => { setSelected(n); setFullscreen(false); }}
          />
        </div>
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
        masteryTierFill
        highlightId={highlightId}
        onNodeClick={onNodeClick}
      />
    </div>
  );
}
