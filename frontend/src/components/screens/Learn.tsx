"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { CustomSelect } from "../CustomSelect";
import { ChatPanel, type ChatMsg } from "../ChatPanel";
import { FullHeightScreen } from "../FullHeightScreen";
import { SessionSummary } from "../SessionSummary";
import { SharedContextToggle, useSharedContext } from "../SharedContextToggle";
import { ModelToggle, useModelPref } from "../ModelToggle";
import { Toggle } from "@/components/ui";
import { DisclaimerModal } from "../DisclaimerModal";
import { AIDisclaimerChip } from "../AIDisclaimerChip";
import { KnowledgeGraph } from "../KnowledgeGraph";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester } from "@/lib/useActiveSemester";
import { useUser } from "@/context/UserContext";
import {
  startSession,
  startSessionStream,
  sendChat,
  streamChat,
  getSessions,
  resumeSession,
  deleteSession,
  renameSession,
  endSession,
  switchMode,
  learnAction,
  getCourses,
  getGraph,
  deleteGraphNode,
  describeConcept,
  type Session,
  type SessionSummaryData,
  type EnrolledCourse,
  type ChatResult,
  type GraphDelta,
} from "@/lib/api";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "@/lib/types";
import { apiToGraphNode, type GraphNode, type GraphEdge } from "@/lib/data";

function apiToGraphEdge(e: ApiEdge): GraphEdge {
  return { source: e.source as string, target: e.target as string, strength: e.strength };
}

type Mode = "socratic" | "expository" | "teachback";

const MODES: { id: Mode; name: string; tip: string }[] = [
  { id: "socratic", name: "Socratic", tip: "Asks guiding questions" },
  { id: "expository", name: "Expository", tip: "Explains directly" },
  { id: "teachback", name: "Teach-back", tip: "You teach, AI listens" },
];

const VALID_MODES: Mode[] = ["socratic", "expository", "teachback"];
const SESSION_END_COUNT_KEY = "sapling_session_end_count";
const LAST_SESSION_CTX_KEY = "sapling_last_session_context";
const RAIL_OPEN_KEY = "sapling_learn_rail_open";
const RAIL_WIDTH = 400;

// Mastery-tier vocabulary for the knowledge-map rail. Colors reuse the shared
// --state-* tokens (same palette as Tree/Dashboard); labels follow the map's
// student-facing wording. Note: the graph itself colors nodes by course, not
// tier — these swatches document the branch list + focus badge.
const TIER_META: Record<GraphNode["mastery_tier"], { label: string; color: string }> = {
  mastered: { label: "Mastered", color: "var(--state-mastery)" },
  learning: { label: "In progress", color: "var(--state-progress)" },
  struggling: { label: "Needs work", color: "var(--state-struggle)" },
  unexplored: { label: "Not started", color: "var(--state-neutral)" },
};
const TIER_ORDER: GraphNode["mastery_tier"][] = ["mastered", "learning", "struggling", "unexplored"];

function normalizeMode(input: string | null): Mode {
  if (!input) return "socratic";
  return (VALID_MODES as string[]).includes(input) ? (input as Mode) : "socratic";
}

// Mirrors backend/config.py::get_mastery_tier so a streamed delta classifies
// mastery the same way a full graph refetch would.
function tierForScore(score: number): GraphNode["mastery_tier"] {
  if (score >= 0.75) return "mastered";
  if (score >= 0.45) return "learning";
  if (score >= 0.1) return "struggling";
  return "unexplored";
}

const normalizeConceptName = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");

// Shared, defensive identity extraction for a single raw graph_update node
// entry: matched by `id`/`node_id` when present (future-proofing against a
// payload shape change), otherwise by normalized concept name. Used by both
// `mergeGraphDelta` and `deltaPlaceholderEdges` so their notions of "is this
// concept already known" can't drift apart.
function rawNodeIdentity(raw: Record<string, unknown>): { id?: string; name?: string } {
  const id = typeof raw.id === "string" ? raw.id : typeof raw.node_id === "string" ? raw.node_id : undefined;
  const name = typeof raw.concept_name === "string" ? raw.concept_name : typeof raw.name === "string" ? raw.name : undefined;
  return { id, name };
}

// Upsert a streamed `graph_update` event into `graphNodes` so the knowledge-map
// rail's "In this branch" / "Elsewhere in course" panels recompute through
// their existing useMemo — no refetch, no extra HTTP round-trip (#74).
//
// NOTE on the real payload shape: `delta.nodes` is NOT the flat
// {id, name, course_id, mastery_score, mastery_tier}[] the streaming-design
// spec sketches. It's a dict keyed by which graph tool wrote
// (backend/agents/tools/graph.py via services/chat_stream.py
// merge_graph_updates): `new_nodes` entries are {concept_name,
// initial_mastery}; `updated_nodes` entries are {concept_name,
// mastery_delta, reason, event_type}. Neither carries an `id` or an
// absolute post-update score. `delta.mastery_changes` ({concept, before,
// after}) IS authoritative for an existing node's new score, so it drives
// merges for updates; `nodes` entries are read defensively via
// `rawNodeIdentity` — and any fields we don't recognize are ignored rather
// than crashing.
//
// Pure function of its arguments only — no component state is read. It does
// NOT compute placeholder edges; see `deltaPlaceholderEdges` below, which
// `applyGraphDelta` runs as a second, independent, idempotent update instead
// of threading a value out of this one. Exported for Learn.graph.test.ts.
export function mergeGraphDelta(
  prev: GraphNode[],
  delta: GraphDelta,
  fallbackCourseId: string,
): GraphNode[] {
  const rawNodes = Object.values(delta.nodes ?? {}).flat() as Array<Record<string, unknown>>;
  const rawMasteryChanges = delta.mastery_changes ?? [];
  if (!rawNodes.length && !rawMasteryChanges.length) return prev;

  const byId = new Map(prev.map(n => [n.id, n] as const));
  const byName = new Map(prev.map(n => [normalizeConceptName(n.name), n] as const));

  const upsert = (existing: GraphNode | undefined, name: string, patch: Partial<GraphNode>) => {
    if (existing) {
      const merged: GraphNode = { ...existing, ...patch };
      byId.set(existing.id, merged);
      byName.set(normalizeConceptName(existing.name), merged);
      return;
    }
    // Unknown concept: insert a placeholder so it's visible immediately; a
    // later full graph refetch (session end / next visit) reconciles the
    // real id. The raw payload carries no course_id, so anchor it to the
    // session's active course when there is one. Mirrors `addConcept`
    // (~:892): resolve color + subject from the course's subject-root node
    // instead of a hardcoded `var(--…)` (the 3D rail can't resolve CSS
    // custom properties — lib/data.ts:78-79 — so that rendered black). The
    // root-anchoring edge is added separately by `deltaPlaceholderEdges`,
    // not here.
    const id = `stream-${normalizeConceptName(name)}`;
    const already = byId.get(id);
    const courseId = (typeof patch.course_id === "string" ? patch.course_id : undefined) ?? fallbackCourseId;
    const root = prev.find(n => n.is_subject_root && n.course_id === courseId);
    const placeholder: GraphNode = already
      ? { ...already, ...patch }
      : {
          id,
          name,
          subject: root?.subject ?? "",
          color: root?.color ?? "var(--c-sage)",
          mastery_tier: "unexplored",
          mastery_score: 0,
          course_id: courseId,
          ...patch,
        };
    byId.set(id, placeholder);
    byName.set(normalizeConceptName(name), placeholder);
  };

  for (const raw of rawNodes) {
    const { id, name } = rawNodeIdentity(raw);
    if (!id && !name) continue;
    const existing = id ? byId.get(id) : byName.get(normalizeConceptName(name as string));
    const patch: Partial<GraphNode> = {};
    const score = typeof raw.mastery_score === "number"
      ? raw.mastery_score
      : (!existing && typeof raw.initial_mastery === "number") ? raw.initial_mastery : undefined;
    if (score !== undefined) {
      patch.mastery_score = score;
      patch.mastery_tier = tierForScore(score);
    }
    if (typeof raw.mastery_tier === "string") patch.mastery_tier = raw.mastery_tier as GraphNode["mastery_tier"];
    if (typeof raw.course_id === "string") patch.course_id = raw.course_id;
    upsert(existing, name ?? (id as string), patch);
  }

  for (const mc of rawMasteryChanges) {
    const existing = byName.get(normalizeConceptName(mc.concept));
    if (!existing) continue; // bare mastery_changes entries carry no id/course to synthesize a new node from
    upsert(existing, mc.concept, { mastery_score: mc.after, mastery_tier: tierForScore(mc.after) });
  }

  return Array.from(byId.values());
}

function edgeKey(e: GraphEdge): string {
  return `${e.source}\u0000${e.target}`;
}

// The root→placeholder edges a streamed `graph_update` implies, computed
// against `nodes` — the caller's current `graphNodes` snapshot — rather than
// against `mergeGraphDelta`'s `prev`: the two run as independent updates
// (see `applyGraphDelta`), so this can't reach into the other's in-flight
// result, and doesn't need to. A concept only gets a synthetic edge when it
// has no existing id/name match in `nodes`, mirroring `mergeGraphDelta`'s
// "unknown concept" branch; an already-known concept is updated in place by
// `mergeGraphDelta` and never gets a new edge here. Pure and side-effect
// free. Exported for Learn.graph.test.ts.
export function deltaPlaceholderEdges(
  nodes: GraphNode[],
  delta: GraphDelta,
  fallbackCourseId: string,
): GraphEdge[] {
  const rawNodes = Object.values(delta.nodes ?? {}).flat() as Array<Record<string, unknown>>;
  if (!rawNodes.length) return [];

  const byId = new Map(nodes.map(n => [n.id, n] as const));
  const byName = new Map(nodes.map(n => [normalizeConceptName(n.name), n] as const));
  const edges: GraphEdge[] = [];

  for (const raw of rawNodes) {
    const { id, name } = rawNodeIdentity(raw);
    if (!id && !name) continue;
    const existing = id ? byId.get(id) : byName.get(normalizeConceptName(name as string));
    if (existing) continue;

    const courseId = (typeof raw.course_id === "string" ? raw.course_id : undefined) ?? fallbackCourseId;
    const root = nodes.find(n => n.is_subject_root && n.course_id === courseId);
    if (!root) continue;

    const label = (name ?? id) as string;
    edges.push({ source: root.id, target: `stream-${normalizeConceptName(label)}`, strength: 0.4 });
  }
  return edges;
}

// Idempotent edge append: dedupes `additions` against `prev` AND against
// each other by source+target, so calling this twice with identical inputs —
// React 18 Strict Mode's dev double-invocation of a setState updater, or the
// same `graph_update` replayed — leaves `prev` unchanged the second time.
// Never mutates `prev`. Exported for Learn.graph.test.ts.
export function mergeGraphEdges(prev: GraphEdge[], additions: GraphEdge[]): GraphEdge[] {
  if (!additions.length) return prev;
  const seen = new Set(prev.map(edgeKey));
  const next: GraphEdge[] = [];
  for (const e of additions) {
    const key = edgeKey(e);
    if (seen.has(key)) continue;
    seen.add(key);
    next.push(e);
  }
  return next.length ? [...prev, ...next] : prev;
}

// Course resolution for a rail-focused node: prefer the node's own course,
// fall back to the course picker's selection, else null. Used both for the
// rail's focus card (`cardCourseId` in LearnInner) and, via that same value,
// for the streamed-placeholder course fallback in `applyGraphDelta` — so a
// streamed node lands in the same course bucket a manually-added one would
// (Finding B). Exported for Learn.graph.test.ts.
export function resolveCardCourseId(
  topicNode: GraphNode | undefined,
  selectedCourseId: string,
): string | null {
  return topicNode?.course_id || selectedCourseId || null;
}

// The actual call-site assembly `applyGraphDelta` (LearnInner, below) runs on
// every streamed `graph_update`. Extracted to a standalone, exported function
// — rather than left inline in the `useCallback` body — specifically so
// Learn.applyGraphDelta.test.ts can invoke the REAL assembly with fake
// `setGraphNodes`/`setGraphEdges` and prove the shape below is what actually
// runs, instead of testing a hand-written mirror of it (fix pass 2's gap).
//
// `edges` MUST be computed before either setter is called: it is a plain,
// eager read of `graphNodesSnapshot` (the caller's current `graphNodes`), not
// a value threaded out of the `setGraphNodes` updater. That distinction is
// the entire fix — see the big comment on `applyGraphDelta` for why reading
// a value out of a functional updater immediately after calling it is
// unsound (React never runs it synchronously at the call site).
// `setGraphNodes`/`setGraphEdges` are typed to only the functional-updater
// overload because that's the only form this call site ever uses.
export function applyGraphDeltaAssembly(
  delta: GraphDelta,
  courseId: string,
  graphNodesSnapshot: GraphNode[],
  setGraphNodes: (updater: (prev: GraphNode[]) => GraphNode[]) => void,
  setGraphEdges: (updater: (prev: GraphEdge[]) => GraphEdge[]) => void,
): void {
  const edges = deltaPlaceholderEdges(graphNodesSnapshot, delta, courseId);
  setGraphNodes(prev => mergeGraphDelta(prev, delta, courseId));
  setGraphEdges(prev => mergeGraphEdges(prev, edges));
}

// #164: Dashboard's "Where you left off" cards push /learn?resume=<id>; Tree's
// session rows used ?session=<id> before both callers unified on ?resume=.
// Accept both so any bookmarked/legacy link keeps working.
export function readResumeParam(params: { get(name: string): string | null }): string | null {
  return params.get("resume") ?? params.get("session");
}

// ADR 0020 Retry: drop the interrupted assistant bubble and — when it sits
// directly before it — the user bubble of the same turn, so the re-send
// (which appends a fresh user bubble) doesn't duplicate either. Pure and
// exported for Learn.resume.test.ts.
export function removeInterruptedTurn(
  messages: ChatMsg[],
  interruptedId: string,
  retryText: string,
): ChatMsg[] {
  const i = messages.findIndex(m => m.id === interruptedId);
  if (i === -1) return messages;
  const next = [...messages.slice(0, i), ...messages.slice(i + 1)];
  if (i > 0 && next[i - 1]?.role === "user" && next[i - 1].content === retryText) {
    next.splice(i - 1, 1);
  }
  return next;
}

export function Learn() {
  return (
    <Suspense fallback={<div style={{ padding: 40, color: "var(--text-dim)" }}>Loading…</div>}>
      <LearnInner />
    </Suspense>
  );
}

function LearnInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { userId, userReady } = useUser();
  const [activeSemester, , semesterHydrated] = useActiveSemester();
  const toast = useToast();
  const isMobile = useIsMobile();

  const [sharedCtx, setSharedCtx] = useSharedContext();
  const [modelPref, setModelPref] = useModelPref();

  const initialTopic = searchParams.get("topic") ?? "";
  const initialMode = normalizeMode(searchParams.get("mode"));
  const initialCourseId = searchParams.get("course") ?? "";

  const [mode, setMode] = useState<Mode>(initialMode);
  const [topic, setTopic] = useState<string>(initialTopic);
  const [topicDraft, setTopicDraft] = useState<string>(initialTopic);
  const [selectedCourseId, setSelectedCourseId] = useState<string | "">(initialCourseId);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);
  // Deep-link resume (#164) in flight — renders a loading state instead of
  // flashing the session picker the deep link is about to leave.
  const [resuming, setResuming] = useState(false);
  // Mirror of `sessionId` readable from async closures: `send`'s error paths
  // must know whether the user has switched sessions while the turn was in
  // flight (appending an interrupted bubble then would inject it into the
  // OTHER session's transcript — the #356 item-7 "stale bubble").
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);
  // Assistant text arriving token-by-token for the in-flight turn; null =
  // not streaming, '' = stream open but no token yet, non-empty = live text.
  // Passed straight through to ChatPanel's `streamingText` prop.
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const streamAbort = useRef<AbortController | null>(null);

  const [recentSessions, setRecentSessions] = useState<Session[]>([]);
  const [courses, setCourses] = useState<EnrolledCourse[]>([]);
  const [concepts, setConcepts] = useState<{ id: string; name: string; course_id: string | null; course_code: string | null; term: string | null }[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);

  // The rail's focused node — independent of the active session's topic, so
  // clicking around the map explores without touching the chat. Null means
  // the focus follows the current session topic. `lastNodeClickRef` powers
  // the double-click-to-switch shortcut. Declared here — ahead of the rest
  // of the rail state below — because `applyGraphDelta`'s course resolution
  // needs `cardCourseId`, which is derived from it.
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const lastNodeClickRef = useRef<{ id: string; t: number } | null>(null);

  const suggestParam = searchParams.get("suggest");
  const highlightId = useMemo(() => {
    // Pre-revamp Learn honored ?suggest=<concept> from the Dashboard
    // "Learn next" suggestion; restore that here, falling back to the
    // current topic if no suggestion is active.
    const suggestMatch = suggestParam
      ? graphNodes.find(n => n.name.toLowerCase() === suggestParam.trim().toLowerCase())
      : null;
    if (suggestMatch) return suggestMatch.id;
    return graphNodes.find(n => n.name.toLowerCase() === topic.trim().toLowerCase())?.id;
  }, [suggestParam, graphNodes, topic]);

  // The rail focus: an explicitly-clicked node when present, otherwise the
  // node for the active session topic. Drives the graph highlight, focus
  // card, "In this branch", and "Elsewhere".
  const activeFocusId = focusedNodeId ?? highlightId;
  const topicNode = useMemo(
    () => graphNodes.find(n => n.id === activeFocusId),
    [graphNodes, activeFocusId],
  );

  // Course resolution shared by the rail's focus card, `addConcept` (~:892
  // below), and the streamed-placeholder fallback right below: prefer the
  // focused concept's own course, fall back to the course picker. Extracted
  // to a top-level function (rather than an inline expression) so it's
  // directly testable — see Learn.graph.test.ts.
  const cardCourseId = resolveCardCourseId(topicNode, selectedCourseId);

  // Streamed graph_update handler (#74) — see mergeGraphDelta above for why
  // the match key falls back to concept name. The course fallback is
  // `cardCourseId`, the same resolution `addConcept` uses for a manually-
  // added node, so a streamed placeholder lands in the same course bucket;
  // when nothing resolves at all it falls back to `selectedCourseId`, same
  // as before.
  //
  // The actual assembly lives in `applyGraphDeltaAssembly` (top-level,
  // exported, above) — nodes and edges are two independent, idempotent
  // functional updates there, NOT one updater's result threaded into the
  // other. `setGraphNodes`'s updater runs against the true, always-current
  // `prev`. `setGraphEdges`'s updater applies edges computed eagerly against
  // the render-scope `graphNodes` snapshot passed in here — safe because
  // subject-root nodes never change mid-stream, and any staleness in the "is
  // this concept already known" check only produces a redundant candidate,
  // which `mergeGraphEdges` dedupes by source+target rather than an
  // incorrect edge. Both updaters are pure functions of their arguments, so
  // calling either twice with the same input — React 18 Strict Mode's dev
  // double-invocation, or the same delta arriving twice — produces the same
  // result. No timing assumption, nothing smuggled out.
  const applyGraphDelta = useCallback(
    (delta: GraphDelta) => {
      const courseId = cardCourseId ?? selectedCourseId;
      applyGraphDeltaAssembly(delta, courseId, graphNodes, setGraphNodes, setGraphEdges);
    },
    [cardCourseId, selectedCourseId, graphNodes],
  );

  // Inline "add concept" composer state for the knowledge-map rail.
  const [addingConcept, setAddingConcept] = useState(false);
  const [newConceptName, setNewConceptName] = useState("");
  // AI-generated concept descriptions, fetched lazily for the focused concept
  // when it has no stored description (keyed by node id). `descInflightRef`
  // dedupes concurrent fetches for the same node.
  const [descCache, setDescCache] = useState<Record<string, string>>({});
  const descInflightRef = useRef<Set<string>>(new Set());

  const [summary, setSummary] = useState<SessionSummaryData | null>(null);
  const [mobileTab, setMobileTab] = useState<"chat" | "graph">("chat");
  const idCounter = useRef(0);
  const msgId = () => `m-${++idCounter.current}`;
  // Tracks each session's last server-confirmed topic so back-to-back rename failures revert to the right value.
  const confirmedTopicsRef = useRef<Map<string, string>>(new Map());

  // Collapsible knowledge-map rail (desktop only). `dragWidth` is non-null
  // only mid-drag, when it drives the live width and the CSS transition is off.
  const [railOpen, setRailOpen] = useState(true);
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const railDragRef = useRef<{ startX: number; startWidth: number; width: number; moved: boolean; pointerId: number } | null>(null);
  const [railHydrated, setRailHydrated] = useState(false);

  // Initial data load. Waits for the active-semester read from localStorage
  // before fetching, so returning users fetch scoped once instead of
  // unscoped-then-scoped; re-runs when the active semester changes.
  useEffect(() => {
    if (!userReady || !userId || !semesterHydrated) return;
    let cancelled = false;
    (async () => {
      try {
        const [sRes, cRes, gRes] = await Promise.all([
          getSessions(userId, 10).catch(() => ({ sessions: [] })),
          getCourses(userId).catch(() => ({ courses: [] })),
          getGraph(userId, activeSemester || undefined).catch(() => ({ nodes: [] as any[], edges: [] as any[], stats: {} })),
        ]);
        if (cancelled) return;
        const filteredSessions = (sRes.sessions ?? []).filter(s => s.message_count > 0);
        setRecentSessions(filteredSessions);
        confirmedTopicsRef.current = new Map(
          filteredSessions.map(s => [s.id, s.topic] as const),
        );
        setCourses(cRes.courses ?? []);
        const nodes = (gRes.nodes ?? []) as Array<{ id: string; concept_name?: string; name?: string; course_id?: string | null; is_subject_root?: boolean }>;
        const courseById = new Map((cRes.courses ?? []).map(c => [c.course_id, c]));
        setConcepts(
          nodes
            .filter(n => !n.is_subject_root)
            .map(n => ({
              id: n.id,
              name: n.concept_name || n.name || "Concept",
              course_id: n.course_id ?? null,
              course_code: n.course_id ? (courseById.get(n.course_id)?.course_code ?? null) : null,
              term: n.course_id ? (courseById.get(n.course_id)?.term ?? null) : null,
            })),
        );
        const apiNodes = (gRes.nodes ?? []) as ApiNode[];
        const apiEdges = (gRes.edges ?? []) as ApiEdge[];
        setGraphNodes(apiNodes.map(n => apiToGraphNode(n, cRes.courses ?? [])));
        setGraphEdges(apiEdges.map(apiToGraphEdge));
      } catch (err) {
        console.error("learn bootstrap failed", err);
      }
    })();
    return () => { cancelled = true; };
  }, [userReady, userId, semesterHydrated, activeSemester]);

  // Sync URL params when mode changes (preserve other params)
  useEffect(() => {
    const current = searchParams.get("mode");
    if (current === mode) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("mode", mode);
    router.replace(`/learn?${params.toString()}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // Restore the rail's open/closed state on mount, then persist changes. The
  // `railHydrated` state flips true only after the stored value is applied, and
  // the persist effect is gated on it (and re-runs when it flips), so the
  // initial value can't be written back before hydration completes.
  useEffect(() => {
    try {
      const v = localStorage.getItem(RAIL_OPEN_KEY);
      if (v != null) setRailOpen(v === "1");
    } catch {}
    setRailHydrated(true);
  }, []);
  useEffect(() => {
    if (!railHydrated) return;
    try {
      localStorage.setItem(RAIL_OPEN_KEY, railOpen ? "1" : "0");
    } catch {}
  }, [railOpen, railHydrated]);

  // Begins a fresh tutor session on `t`. Shared by the entry-screen Start
  // button and the knowledge-map switch flow. Clears any map focus so the rail
  // snaps back to following the (new) active topic.
  //
  // Streams the greeting over startSessionStream, mirroring `send`'s
  // three-rung fallback ladder verbatim (see the big comment on `send`,
  // above `send`'s definition, for the full rationale):
  //   Rung 3 (stream never produced text) -> retry transparently via the
  //     non-streaming JSON startSession; the user never sees an error.
  //   Rung 2 (rejected AFTER tokens appeared) -> surface the error via the
  //     same toast path this handler already used for JSON failures. Never
  //     silently re-run.
  //   Stop pressed -> distinguished via the AbortController's signal.aborted;
  //     intentional, not an error, no fallback. No session exists yet on
  //     this path (session_id is only set on success below), so aborting
  //     just drops back to the entry screen once `starting` clears.
  //
  // Like `send`, no loading placeholder goes into `messages` up front — the
  // greeting renders through ChatPanel's `streamingText` bubble instead, so
  // it appears progressively rather than after a spinner (#70's premise,
  // extended to session start).
  //
  // Field-name note: the JSON route returns `initial_message`; the stream's
  // `done` event returns `reply` (ChatResult). Both are normalized into
  // `replyText` below so the rest of this function doesn't care which path
  // served the turn.
  const beginSession = async (t: string) => {
    const topicName = t.trim();
    if (!topicName || !userId) return;
    setFocusedNodeId(null);
    setTopic(topicName);
    setTopicDraft(topicName);
    setMessages([]);
    setStarting(true);
    setStreamingText("");
    // A stream may already be in flight (e.g. a graph-node click starting a
    // new session while a reply streams) — abort it first so two streams
    // never interleave writes into the same streamingText/messages state.
    streamAbort.current?.abort();
    const controller = new AbortController();
    streamAbort.current = controller;
    let sawToken = false;
    try {
      let newSessionId: string;
      let replyText: string;
      try {
        const res = await startSessionStream(userId, topicName, mode, sharedCtx, selectedCourseId || undefined, modelPref, {
          onToken: (delta) => {
            sawToken = true;
            setStreamingText(prev => (prev ?? "") + delta);
          },
          onGraphUpdate: applyGraphDelta,
          signal: controller.signal,
        });
        if (!res.session_id) throw new Error("Session stream completed without a session_id.");
        newSessionId = res.session_id;
        replyText = res.reply || "Let's begin.";
      } catch (err) {
        if (controller.signal.aborted) { setMessages([]); return; } // Stop pressed — intentional, not an error.
        if (sawToken) throw err; // Rung 2: interrupted after producing text — surface it, don't retry.
        // Rung 3: the stream never produced text — retry transparently via
        // the non-streaming JSON route. Clear streamingText first so
        // ChatPanel drops the Stop affordance for this leg (mirrors `send`).
        setStreamingText(null);
        const res = await startSession(userId, topicName, mode, selectedCourseId || undefined, sharedCtx, modelPref);
        newSessionId = res.session_id;
        replyText = res.initial_message || "Let's begin.";
      }
      setSessionId(newSessionId);
      setMessages([{ id: msgId(), role: "assistant", content: replyText }]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't start session.");
      setMessages([]);
    } finally {
      setStarting(false);
      setStreamingText(null);
      if (streamAbort.current === controller) streamAbort.current = null;
    }
  };

  const handleStart = () => beginSession(topicDraft);

  // Loads a session by id and enters it. Server-authoritative: topic/mode/
  // course come off the resume payload itself, so a deep link works even for
  // a session outside the 10-row recent list (#164).
  const resumeSessionById = async (id: string, opts?: { deepLink?: boolean }) => {
    if (opts?.deepLink) setResuming(true);
    try {
      const res = await resumeSession(id);
      setSessionId(res.session.id);
      setTopic(res.session.topic);
      setMode(normalizeMode(res.session.mode));
      setSelectedCourseId(res.session.course_id || "");
      setMessages(
        (res.messages ?? []).map(m => ({
          id: msgId(),
          role: m.role === "user" ? "user" : "assistant",
          content: m.content,
        })),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Resume failed.");
    } finally {
      if (opts?.deepLink) setResuming(false);
    }
  };

  const handleResume = (s: Session) => resumeSessionById(s.id);

  // #164: consume /learn?resume=<id> (legacy ?session= accepted too) —
  // Dashboard's "Where you left off" cards and Tree's session rows deep-link
  // here. Consumed once per id via the guard ref, so the mode-sync URL
  // rewrite above (which preserves all params) can't re-trigger it and a
  // session the user opened manually afterwards isn't yanked away.
  const resumeParam = readResumeParam(searchParams);
  const consumedResumeRef = useRef<string | null>(null);
  useEffect(() => {
    if (!resumeParam || !userReady || !userId) return;
    if (consumedResumeRef.current === resumeParam) return;
    consumedResumeRef.current = resumeParam;
    void resumeSessionById(resumeParam, { deepLink: true });
    // resumeSessionById is a plain function (same pattern as handleResume);
    // the guard ref makes re-runs from its identity changing harmless.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeParam, userReady, userId]);

  const handleDeleteSession = async (s: Session) => {
    if (!userId) return;
    try {
      await deleteSession(s.id, userId);
      setRecentSessions(prev => prev.filter(p => p.id !== s.id));
      toast.success("Session deleted.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed.");
    }
  };

  const handleRenameSession = useCallback(async (s: Session, newTopic: string) => {
    if (!userId) return;
    const trimmed = newTopic.trim();
    if (!trimmed || trimmed.length > 120 || trimmed === s.topic) return;
    setRecentSessions(prev => prev.map(p => (p.id === s.id ? { ...p, topic: trimmed } : p)));
    try {
      await renameSession(s.id, userId, trimmed);
      confirmedTopicsRef.current.set(s.id, trimmed);
    } catch (err) {
      // Server is authoritative — resync from it instead of guessing a revert
      // target, which is otherwise racy when multiple renames overlap.
      const res = await getSessions(userId, 10).catch(() => null);
      if (res) {
        const filtered = (res.sessions ?? []).filter(x => x.message_count > 0);
        setRecentSessions(filtered);
        confirmedTopicsRef.current = new Map(filtered.map(x => [x.id, x.topic] as const));
      }
      toast.error(err instanceof Error ? err.message : "Rename failed.");
    }
  }, [userId, toast]);

  // Sends one turn over the SSE stream, with a three-rung fallback ladder:
  //   Rung 3 (stream never produced text) -> retry transparently via the
  //     non-streaming sendChat; the user never sees an error.
  //   Rung 2 (rejected AFTER tokens appeared) -> surface the error through
  //     the same error-message path the old non-streaming send() used. Never
  //     silently re-run: the user already saw partial text, and nothing was
  //     persisted server-side, so re-running would restart the reply.
  //   Stop pressed -> distinguished via the AbortController's signal.aborted;
  //     intentional, not an error, no fallback, no message appended (nothing
  //     was persisted, so the partial bubble just disappears).
  //
  // Unlike the old handler, no loading placeholder is pushed into `messages`
  // up front — ChatPanel renders the in-flight turn itself via streamingText
  // (a placeholder there would double up with that live bubble). The real
  // assistant message is appended once, after the turn resolves one way or
  // another.
  const send = useCallback(async (userText: string) => {
    if (!userText.trim() || !sessionId || !userId) return;
    const turnSessionId = sessionId;
    setMessages(m => [...m, { id: msgId(), role: "user", content: userText }]);
    setSending(true);
    setStreamingText("");
    // A stream may already be in flight (e.g. a graph-node click starting a
    // new session while a reply streams) — abort it first so two streams
    // never interleave writes into the same streamingText/messages state.
    streamAbort.current?.abort();
    const controller = new AbortController();
    streamAbort.current = controller;
    let sawToken = false;
    // The partial reply so far — what an interrupted bubble keeps (ADR 0020).
    // streamingText can't serve here: it's cleared before the Rung-3 leg.
    let acc = "";
    // ADR 0020: keep the partial, mark the bubble interrupted, offer Retry.
    // Skipped when the user has switched sessions (or left the chat) while
    // this turn was in flight — appending then would inject a stale bubble
    // into the OTHER session's transcript (#356 item 7). Nothing was
    // persisted server-side for the turn (routes persist only on
    // completion), so Retry is a plain re-send.
    const appendInterrupted = () => {
      if (sessionIdRef.current !== turnSessionId) return;
      setMessages(m => [
        ...m,
        { id: msgId(), role: "assistant", content: acc, interrupted: true, retryText: userText },
      ]);
    };
    try {
      let res: ChatResult;
      try {
        res = await streamChat(sessionId, userId, userText, mode, sharedCtx, modelPref, {
          onToken: (delta) => {
            sawToken = true;
            acc += delta;
            setStreamingText(t => (t ?? "") + delta);
          },
          onGraphUpdate: applyGraphDelta,
          signal: controller.signal,
        });
      } catch (err) {
        if (controller.signal.aborted) {
          // Stop pressed (or the session switched, aborting via the
          // sessionId-keyed effect below) — intentional, not an error.
          appendInterrupted();
          return;
        }
        if (sawToken) {
          // Rung 2: interrupted after producing text — surface it, never
          // silently re-run (the user already saw partial text). The error
          // detail goes to a toast; the transcript keeps the partial.
          toast.error(err instanceof Error ? err.message : "The tutor was interrupted.");
          appendInterrupted();
          return;
        }
        // Rung 3: the stream never produced text — retry transparently via the
        // non-streaming JSON route. `sendChat`/`fetchJSON` (lib/api.ts) take
        // no AbortSignal, and plumbing one through is out of scope for this
        // fix — so the fallback request itself cannot actually be cancelled.
        // Clear streamingText to null *before* issuing it so ChatPanel drops
        // both the Stop button and the "Thinking…" bubble for this leg,
        // rather than offering a Stop affordance that would abort an
        // already-detached controller while the JSON call keeps running
        // server-side regardless. `sending` stays true, so the input is
        // still disabled — the turn just no longer looks interruptible,
        // which is now the truth.
        setStreamingText(null);
        res = await sendChat(sessionId, userId, userText, mode, sharedCtx, modelPref);
      }
      setMessages(m => [...m, { id: msgId(), role: "assistant", content: res.reply || "" }]);
    } catch (err) {
      // The Rung-3 JSON fallback itself failed — the ladder is exhausted.
      // ADR 0020 treats this like any mid-stream failure: interrupted bubble
      // + Retry, error detail in a toast rather than a fake assistant reply.
      toast.error(err instanceof Error ? err.message : "The tutor is unavailable.");
      appendInterrupted();
    } finally {
      setSending(false);
      setStreamingText(null);
      if (streamAbort.current === controller) streamAbort.current = null;
    }
  }, [sessionId, userId, mode, sharedCtx, modelPref, applyGraphDelta, toast]);

  // ADR 0020 Retry: re-dispatch the interrupted turn's original text. Drop
  // the failed pair first (removeInterruptedTurn) so `send`'s own user-bubble
  // append doesn't duplicate it. Guarded while a turn is in flight.
  const handleRetry = useCallback((m: ChatMsg) => {
    const text = m.retryText;
    if (!text || sending || starting) return;
    setMessages(prev => removeInterruptedTurn(prev, m.id, text));
    void send(text);
  }, [send, sending, starting]);

  // Abort any in-flight stream when the active session changes (including to
  // none) and on unmount — guards the #131/#133 leaked-stream bug class. A
  // plain unmount-only effect would miss the "switched sessions mid-stream"
  // case, so this keys on sessionId: its cleanup fires both when sessionId
  // changes and when the component unmounts.
  useEffect(() => {
    return () => streamAbort.current?.abort();
  }, [sessionId]);

  const handleAction = async (action: "hint" | "confused" | "skip") => {
    if (!sessionId || !userId) return;
    const labelMap = { hint: "(Requested a hint)", confused: "(Said I'm confused)", skip: "(Asked to skip)" };
    setMessages(m => [
      ...m,
      { id: msgId(), role: "user", content: labelMap[action] },
      { id: msgId(), role: "assistant", content: "", loading: true },
    ]);
    setSending(true);
    try {
      const res = await learnAction(sessionId, userId, action, mode, sharedCtx, modelPref);
      setMessages(m => {
        const next = [...m];
        next[next.length - 1] = { id: next[next.length - 1].id, role: "assistant", content: res.reply || "" };
        return next;
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed.");
      setMessages(m => m.slice(0, -2));
    } finally {
      setSending(false);
    }
  };

  const handleModeSwitch = async (newMode: Mode) => {
    if (newMode === mode) return;
    if (!sessionId || !userId) {
      setMode(newMode);
      return;
    }
    const prev = mode;
    setMode(newMode);
    try {
      const res = await switchMode(sessionId, userId, newMode);
      if (res.reply) {
        setMessages(m => [...m, { id: msgId(), role: "assistant", content: res.reply }]);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Mode switch failed.");
      setMode(prev);
    }
  };

  const handleEndSession = useCallback(async () => {
    if (!sessionId || !userId) return;
    try {
      const res = await endSession(sessionId, userId);
      setSummary(res.summary ?? null);
      // Write session context for navigate-away feedback
      try {
        sessionStorage.setItem(LAST_SESSION_CTX_KEY, JSON.stringify({ sessionId, topic }));
      } catch {}
      // Bump end-count for every-3 session-feedback trigger
      try {
        const n = Number(localStorage.getItem(SESSION_END_COUNT_KEY) ?? "0") + 1;
        localStorage.setItem(SESSION_END_COUNT_KEY, String(n));
      } catch {}
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "End session failed.");
    }
  }, [sessionId, userId, topic, toast]);

  const endConfirm = useConfirm(() => { handleEndSession(); }, 3000);

  const closeSummary = () => {
    setSummary(null);
    setSessionId(null);
    setMessages([]);
    setTopic("");
    setTopicDraft("");
  };

  const handleBackToLearn = () => {
    setSessionId(null);
    setMessages([]);
    setTopic("");
    setTopicDraft("");
    router.replace(`/learn?mode=${mode}`, { scroll: false });
  };

  const startNextFromSummary = (concept: string) => {
    setSummary(null);
    setSessionId(null);
    setMessages([]);
    setTopicDraft(concept);
    setTopic(concept);
    router.replace(`/learn?topic=${encodeURIComponent(concept)}&mode=${mode}`, { scroll: false });
  };

  const modeOptions = useMemo(() => MODES.map(m => ({ value: m.id, label: m.name, description: m.tip })), []);

  // Scope the course picker to the active semester (falls back to all
  // courses when no semester is selected). The suggest/highlight logic that
  // sat next to this pre-revamp now lives up top with the rail-focus state.
  const scopedCourses = useMemo(
    () => (activeSemester ? courses.filter(c => c.term === activeSemester) : courses),
    [courses, activeSemester],
  );

  // Jump the chat to `name`: resume an existing session on that concept if one
  // exists, otherwise start a fresh one. Both paths clear the map focus so the
  // rail follows the now-active session.
  const switchToConcept = (name: string) => {
    const existing = recentSessions.find(
      s => s.topic.trim().toLowerCase() === name.trim().toLowerCase(),
    );
    if (existing) {
      setFocusedNodeId(null);
      handleResume(existing);
    } else {
      beginSession(name);
    }
  };

  // Single click focuses a concept in the rail (chat untouched); a second click
  // on the same node within 350ms switches the session to it.
  const handleNodeClick = (n: GraphNode) => {
    if (n.is_subject_root) return;
    const now = Date.now();
    const last = lastNodeClickRef.current;
    lastNodeClickRef.current = { id: n.id, t: now };
    if (last && last.id === n.id && now - last.t < 350) {
      switchToConcept(n.name);
    } else {
      setFocusedNodeId(n.id);
    }
  };

  // Edge-tab pointer handling: grab-drag moves the rail width live; a sub-4px
  // press is treated as a click (toggle). On release we snap open/closed at the
  // halfway point. The tab lives on the rail's left edge, so dragging right
  // (toward the screen edge) collapses it.
  const onRailTabPointerDown = (e: React.PointerEvent) => {
    if (isMobile) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const startWidth = railOpen ? RAIL_WIDTH : 0;
    railDragRef.current = { startX: e.clientX, startWidth, width: startWidth, moved: false, pointerId: e.pointerId };
    setDragWidth(startWidth);
  };
  const onRailTabPointerMove = (e: React.PointerEvent) => {
    const d = railDragRef.current;
    if (!d || e.pointerId !== d.pointerId) return;
    const dx = e.clientX - d.startX;
    if (Math.abs(dx) > 4) d.moved = true;
    const next = Math.max(0, Math.min(RAIL_WIDTH, d.startWidth - dx));
    d.width = next;
    setDragWidth(next);
  };
  // Shared drag terminator. A cancellation (or an event from a stray pointer
  // that isn't the one that started the drag) clears state without toggling or
  // snapping the rail.
  const endRailDrag = (e: React.PointerEvent, cancelled: boolean) => {
    const d = railDragRef.current;
    if (!d || e.pointerId !== d.pointerId) return;
    railDragRef.current = null;
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch {}
    setDragWidth(null);
    if (cancelled) return;
    if (!d.moved) { setRailOpen(o => !o); return; }
    setRailOpen(d.width >= RAIL_WIDTH / 2);
  };
  const onRailTabPointerUp = (e: React.PointerEvent) => endRailDrag(e, false);
  const onRailTabPointerCancel = (e: React.PointerEvent) => endRailDrag(e, true);
  const onRailTabKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setRailOpen(o => !o);
    }
  };

  const neighborIds = useMemo(() => {
    if (!topicNode) return new Set<string>();
    const ids = new Set<string>();
    for (const e of graphEdges) {
      if (e.source === topicNode.id) ids.add(e.target as string);
      else if (e.target === topicNode.id) ids.add(e.source as string);
    }
    return ids;
  }, [topicNode, graphEdges]);

  const cardCourse = useMemo(
    () => courses.find(c => c.course_id === cardCourseId) ?? null,
    [courses, cardCourseId],
  );

  const progressItems = useMemo(() => {
    if (topicNode && neighborIds.size > 0) {
      return graphNodes
        .filter(n => neighborIds.has(n.id) && !n.is_subject_root)
        .slice(0, 6)
        .map(n => ({ id: n.id, name: n.name, tier: n.mastery_tier }));
    }
    if (cardCourseId) {
      return graphNodes
        .filter(n => n.course_id === cardCourseId && !n.is_subject_root)
        .sort((a, b) => (b.mastery_score ?? 0) - (a.mastery_score ?? 0))
        .slice(0, 6)
        .map(n => ({ id: n.id, name: n.name, tier: n.mastery_tier }));
    }
    return [];
  }, [graphNodes, neighborIds, topicNode, cardCourseId]);

  const relatedItems = useMemo(() => {
    if (topicNode) {
      return graphNodes
        .filter(n =>
          n.id !== topicNode.id &&
          !n.is_subject_root &&
          !neighborIds.has(n.id) &&
          n.course_id === topicNode.course_id,
        )
        .sort((a, b) => (b.mastery_score ?? 0) - (a.mastery_score ?? 0))
        .slice(0, 4)
        .map(n => ({ id: n.id, name: n.name }));
    }
    if (cardCourseId) {
      const topicLower = topic.trim().toLowerCase();
      return graphNodes
        .filter(n =>
          !n.is_subject_root &&
          n.course_id === cardCourseId &&
          n.name.toLowerCase() !== topicLower,
        )
        .sort((a, b) => (b.mastery_score ?? 0) - (a.mastery_score ?? 0))
        .slice(0, 4)
        .map(n => ({ id: n.id, name: n.name }));
    }
    return [];
  }, [graphNodes, neighborIds, topicNode, cardCourseId, topic]);

  // The rail graph shows only the focused course's tree (its subject root +
  // its concepts), not the full multi-course graph. Falls back to the whole
  // graph when no course is resolved (free-text topic with no enrollment).
  const railGraph = useMemo(() => {
    if (!cardCourseId) return { nodes: graphNodes, edges: graphEdges };
    const nodes = graphNodes.filter(n => n.course_id === cardCourseId);
    if (nodes.length === 0) return { nodes: graphNodes, edges: graphEdges };
    const ids = new Set(nodes.map(n => n.id));
    const edges = graphEdges.filter(e => ids.has(e.source as string) && ids.has(e.target as string));
    return { nodes, edges };
  }, [graphNodes, graphEdges, cardCourseId]);

  // The focus card anchors on the specific concept when the session topic is
  // one; otherwise (course-level session) it anchors on the course itself.
  const focusConcept = topicNode && !topicNode.is_subject_root ? topicNode : null;
  const courseConceptCount = railGraph.nodes.filter(n => !n.is_subject_root).length;

  // Whether the focused concept is the one already being chatted about (no
  // switch needed), and whether a prior session exists to resume vs. start.
  const focusIsCurrent = !!focusConcept && focusConcept.name.trim().toLowerCase() === topic.trim().toLowerCase();
  const focusHasSession = !!focusConcept && recentSessions.some(
    s => s.topic.trim().toLowerCase() === focusConcept.name.trim().toLowerCase(),
  );

  // Lazily fetch an AI description for the focused concept when it lacks a
  // stored one (e.g. a manually-added concept). Concepts without a fetched
  // description fall back to the connected-concepts sentence.
  const focusId = focusConcept?.id;
  const focusName = focusConcept?.name;
  const focusDesc = focusConcept?.description;
  const focusCourseName = cardCourse?.course_name;
  useEffect(() => {
    if (!userId || !focusId || !focusName) return;
    if (focusDesc || descCache[focusId] || descInflightRef.current.has(focusId)) return;
    descInflightRef.current.add(focusId);
    let cancelled = false;
    describeConcept(userId, focusName, focusCourseName)
      .then(r => {
        if (!cancelled && r?.description) {
          setDescCache(prev => ({ ...prev, [focusId]: r.description }));
        }
      })
      .catch(() => {})
      .finally(() => { descInflightRef.current.delete(focusId); });
    return () => { cancelled = true; };
  }, [userId, focusId, focusName, focusDesc, focusCourseName, descCache]);

  // Manually add a concept to the current course. The new node links to the
  // focused concept (or the course root) so it joins the tree, starts as
  // "unexplored", and becomes the focus. State-first; real-backend
  // persistence for add would need a dedicated endpoint.
  const addConcept = (name: string) => {
    const label = name.trim();
    if (!label || !cardCourseId) return;
    const root = graphNodes.find(n => n.is_subject_root && n.course_id === cardCourseId);
    const anchorId = focusConcept?.id ?? root?.id;
    const id = `node-new-${Date.now()}`;
    const newNode: GraphNode = {
      id,
      name: label,
      subject: cardCourse?.course_name ?? root?.subject ?? "",
      color: root?.color ?? "var(--c-sage)",
      mastery_tier: "unexplored",
      mastery_score: 0,
      course_id: cardCourseId,
    };
    setGraphNodes(prev => [...prev, newNode]);
    if (anchorId) setGraphEdges(prev => [...prev, { source: anchorId, target: id, strength: 0.4 }]);
    setFocusedNodeId(id);
    setNewConceptName("");
    setAddingConcept(false);
  };

  // Remove a concept: drop the node + its edges and clear focus if it was
  // focused. Best-effort persistence via the delete endpoint on real backends.
  const removeConcept = (nodeId: string) => {
    setGraphNodes(prev => prev.filter(n => n.id !== nodeId));
    setGraphEdges(prev => prev.filter(e => e.source !== nodeId && e.target !== nodeId));
    setFocusedNodeId(cur => (cur === nodeId ? null : cur));
    if (userId) deleteGraphNode(userId, nodeId).catch(() => {});
  };

  // ────────── Entry screen (no active session) ──────────
  // Deep-link resume in flight (#164): a quiet loading state instead of
  // flashing the "Start a session" picker the deep link is about to leave.
  if (resuming && !sessionId) {
    return (
      <FullHeightScreen>
        <DisclaimerModal />
        <div data-testid="tutor-resume-loading" style={{ padding: 40, color: "var(--text-dim)" }}>
          Loading…
        </div>
      </FullHeightScreen>
    );
  }

  if (!sessionId && !starting) {
    return (
      <FullHeightScreen className="fade-in">
        <DisclaimerModal />
        <TopBar
          title="Start a session"
          subtitle="Pick a topic. Sapling will adapt to your chosen mode."
          actions={<AIDisclaimerChip />}
        />
        <div
          style={{
            padding: 32,
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "minmax(0, 1fr) 320px",
            gap: 24,
            flex: 1,
            overflowY: "auto",
          }}
        >
          <div className="card" style={{ padding: "var(--pad-xl)" }}>
            <div className="label-micro" style={{ marginBottom: 8 }}>Course (optional)</div>
            <CustomSelect<string>
              value={selectedCourseId}
              options={[
                { value: "", label: "No course" },
                ...scopedCourses.map(c => ({ value: c.course_id, label: `${c.course_code} — ${c.course_name}` })),
              ]}
              onChange={setSelectedCourseId}
              style={{ width: "100%", marginBottom: 16 }}
            />
            <div className="label-micro" style={{ marginBottom: 8 }}>Topic</div>
            <TopicPicker
              value={topicDraft}
              onChange={setTopicDraft}
              onSubmit={handleStart}
              concepts={concepts}
              courses={courses}
              selectedCourseId={selectedCourseId}
              activeSemester={activeSemester}
            />
            <div className="label-micro" style={{ marginBottom: 8 }}>Mode</div>
            <div style={{ marginBottom: 20 }}>
              <Toggle
                options={MODES.map(m => ({ value: m.id, label: m.name, title: m.tip }))}
                value={mode}
                onChange={setMode}
              />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <SharedContextToggle enabled={sharedCtx} onChange={setSharedCtx} />
              <button className="btn btn--primary" onClick={handleStart} disabled={!topicDraft.trim() || !userId}>
                <Icon name="sparkle" size={13} /> Start learning
              </button>
            </div>
          </div>

          <div className="card" style={{ padding: "var(--pad-lg)" }}>
            <div className="label-micro" style={{ marginBottom: 10 }}>Recent sessions</div>
            {recentSessions.length === 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No recent sessions yet.</div>
            )}
            {recentSessions.map(s => (
              <SessionRow key={s.id} s={s} onResume={handleResume} onDelete={handleDeleteSession} onRename={handleRenameSession} />
            ))}
          </div>
        </div>
      </FullHeightScreen>
    );
  }

  // ────────── Active session ──────────
  const railDragging = dragWidth != null;
  const railW = railDragging ? (dragWidth as number) : railOpen ? RAIL_WIDTH : 0;
  return (
    <FullHeightScreen>
      <DisclaimerModal />

      {isMobile && (
        <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
          {(["chat", "graph"] as const).map(t => (
            <button
              key={t}
              onClick={() => setMobileTab(t)}
              style={{
                flex: 1,
                padding: "10px 0",
                fontSize: 12,
                fontWeight: 500,
                textTransform: "capitalize",
                color: mobileTab === t ? "var(--accent)" : "var(--text-dim)",
                borderBottom: mobileTab === t ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flex: 1, minHeight: 0, position: "relative" }}>
        {(!isMobile || mobileTab === "chat") && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
            <TopBar
              breadcrumb={<BackToLearnLink onClick={handleBackToLearn} />}
              title={topic}
              subtitle={`${cardCourse?.course_code ? `${cardCourse.course_code} · ` : ""}${MODES.find(m => m.id === mode)?.name ?? mode} Tutor · ${messages.length} Messages`}
              actions={
                <>
                  <SharedContextToggle enabled={sharedCtx} onChange={setSharedCtx} />
                  <button
                    className={endConfirm.armed ? "btn btn--danger btn--sm" : "btn btn--sm"}
                    onClick={endConfirm.trigger}
                    title={endConfirm.armed ? "Click again to confirm" : "End session"}
                  >
                    {endConfirm.armed ? "Confirm end" : "End session"}
                  </button>
                </>
              }
            />
            <div style={{ display: "flex", gap: 6, padding: "10px 32px", borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
              {MODES.map(m => (
                <button
                  key={m.id}
                  onClick={() => handleModeSwitch(m.id)}
                  style={{
                    padding: "6px 14px",
                    borderRadius: "var(--r-full)",
                    fontSize: 12,
                    fontWeight: 500,
                    background: mode === m.id ? "var(--accent)" : "var(--bg-subtle)",
                    color: mode === m.id ? "var(--accent-fg)" : "var(--text-dim)",
                    border: mode === m.id ? "1px solid var(--accent)" : "1px solid var(--border)",
                  }}
                >
                  {m.name}
                </button>
              ))}
              <div style={{ flex: 1 }} />
              <AIDisclaimerChip />
              <ModelToggle pref={modelPref} onChange={setModelPref} />
            </div>
            <ChatPanel
              messages={messages}
              onSend={send}
              onAction={handleAction}
              disabled={sending || starting}
              streamingText={streamingText}
              onStop={() => streamAbort.current?.abort()}
              onRetry={handleRetry}
            />
          </div>
        )}

        {(!isMobile || mobileTab === "graph") && (
          <aside
            style={{
              width: isMobile ? "100%" : railW,
              minWidth: isMobile ? undefined : railW,
              flexShrink: 0,
              overflow: "hidden",
              transition: isMobile || railDragging
                ? "none"
                : "width var(--dur) var(--ease), min-width var(--dur) var(--ease)",
            }}
          >
            {/* Inner content keeps a fixed 400px width so it stays laid out
                (and the graph's measured bounds stay stable) while the outer
                <aside> clips it during the slide. */}
            <div
              className="learn-map-rail"
              style={{
                width: isMobile ? "100%" : RAIL_WIDTH,
                height: "100%",
                boxSizing: "border-box",
                borderLeft: isMobile ? "none" : "1px solid var(--border)",
                background: "var(--bg-subtle)",
                overflowY: "auto",
                overflowX: "hidden",
                display: "flex",
                flexDirection: "column",
              }}
            >
              {/* Header */}
              <div style={{ padding: "20px 22px 16px", borderBottom: "1px solid var(--border)" }}>
                <div className="label-micro">Knowledge map</div>
                {cardCourse && (
                  <div style={{ marginTop: 8, fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 500, color: "var(--brand-forest)" }}>
                    {cardCourse.course_code}
                  </div>
                )}
                <div style={{ fontFamily: "var(--font-serif)", fontSize: 15, color: "var(--text-dim)", marginTop: 2, lineHeight: 1.35 }}>
                  {cardCourse?.course_name ?? topic}
                </div>
              </div>

              {/* Graph + legend */}
              {railGraph.nodes.length > 0 && (
                <div
                  style={{
                    padding: "14px 14px 8px",
                    background: "radial-gradient(ellipse 80% 70% at 55% 42%, color-mix(in srgb, var(--brand-forest-bright) 6%, transparent), transparent 70%)",
                  }}
                >
                  <SidebarKnowledgeGraph
                    nodes={railGraph.nodes}
                    edges={railGraph.edges}
                    highlightId={activeFocusId}
                    onNodeClick={handleNodeClick}
                  />
                  <div style={{ display: "flex", gap: 14, justifyContent: "center", padding: "6px 0 4px", flexWrap: "wrap" }}>
                    {TIER_ORDER.map(tier => (
                      <span key={tier} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, color: "var(--text-muted)" }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: TIER_META[tier].color }} />
                        {TIER_META[tier].label}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Focused concept (or course anchor when no concept is focused) */}
              {(focusConcept || cardCourse) && (
                <div
                  style={{
                    margin: "6px 18px 0",
                    padding: "15px 16px",
                    background: "var(--bg-panel)",
                    border: "1px solid var(--border)",
                    borderRadius: 14,
                    boxShadow: "var(--shadow-sm)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <div className="label-micro">{focusConcept ? "Focused concept" : "Focused course"}</div>
                    {focusConcept && (
                      <span
                        style={{
                          fontSize: 10.5,
                          fontWeight: 600,
                          padding: "2px 9px",
                          borderRadius: "var(--r-full)",
                          color: "#fff",
                          background: TIER_META[focusConcept.mastery_tier].color,
                        }}
                      >
                        {TIER_META[focusConcept.mastery_tier].label}
                      </span>
                    )}
                  </div>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 19, fontWeight: 500, color: "var(--text)", marginTop: 7, lineHeight: 1.2 }}>
                    {focusConcept ? focusConcept.name : (cardCourse?.course_name ?? topic)}
                  </div>
                  <div
                    data-testid="tutor-focus-concept-description"
                    style={{ fontSize: 12.5, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.5 }}
                  >
                    {focusConcept
                      ? (focusConcept.description
                          ?? descCache[focusConcept.id]
                          ?? `${neighborIds.size} connected concepts · this is where your session is anchored on the course map.`)
                      : `${courseConceptCount} concepts in this course · pick one to anchor your session.`}
                  </div>
                  {focusConcept && (
                    <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                      {!focusIsCurrent && (
                        <button
                          onClick={() => switchToConcept(focusConcept.name)}
                          style={{
                            flex: 1,
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: 6,
                            padding: "8px 12px",
                            borderRadius: "var(--r-sm)",
                            fontSize: 12.5,
                            fontWeight: 600,
                            border: "none",
                            background: "var(--brand-forest)",
                            color: "var(--accent-fg)",
                            cursor: "pointer",
                          }}
                        >
                          <Icon name="sparkle" size={12} />
                          {focusHasSession ? "Resume session" : "Start session"}
                        </button>
                      )}
                      <button
                        onClick={() => removeConcept(focusConcept.id)}
                        title="Remove concept"
                        style={{
                          flex: focusIsCurrent ? 1 : undefined,
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: 6,
                          padding: "8px 12px",
                          borderRadius: "var(--r-sm)",
                          fontSize: 12.5,
                          fontWeight: 500,
                          border: "1px solid var(--border)",
                          background: "var(--bg-panel)",
                          color: "var(--state-struggle)",
                          cursor: "pointer",
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* In this branch */}
              {progressItems.length > 0 && (
                <div style={{ padding: "18px 22px 6px" }}>
                  <div className="label-micro" style={{ marginBottom: 10 }}>In this branch</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                    {progressItems.map(p => (
                      <button
                        key={p.id}
                        onClick={() => setFocusedNodeId(p.id)}
                        title={`Focus ${p.name}`}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          textAlign: "left",
                          width: "100%",
                          margin: "0 -7px",
                          padding: "5px 7px",
                          borderRadius: 8,
                          background: p.id === activeFocusId ? "var(--bg-soft)" : "transparent",
                          border: "none",
                          cursor: "pointer",
                        }}
                      >
                        <span style={{ width: 11, height: 11, borderRadius: "50%", flexShrink: 0, background: TIER_META[p.tier].color }} />
                        <span style={{ flex: 1, fontSize: 13, color: "var(--text)", fontWeight: p.id === activeFocusId ? 600 : 400, lineHeight: 1.3 }}>{p.name}</span>
                        <span style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{TIER_META[p.tier].label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Elsewhere in course */}
              {relatedItems.length > 0 && (
                <div style={{ padding: "16px 22px 24px" }}>
                  <div className="label-micro" style={{ marginBottom: 10 }}>Elsewhere in course</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
                    {relatedItems.map(r => {
                      const active = r.id === activeFocusId;
                      return (
                        <button
                          key={r.id}
                          onClick={() => setFocusedNodeId(r.id)}
                          title={`Focus ${r.name}`}
                          style={{
                            padding: "6px 12px",
                            borderRadius: "var(--r-full)",
                            fontSize: 12.5,
                            fontWeight: 500,
                            border: `1px solid ${active ? "var(--brand-forest)" : "var(--border)"}`,
                            background: active ? "var(--accent-soft)" : "var(--bg-panel)",
                            color: active ? "var(--text)" : "var(--text-dim)",
                            cursor: "pointer",
                          }}
                        >
                          {r.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Add concept */}
              {cardCourseId && (
                <div style={{ padding: "4px 22px 24px" }}>
                  {addingConcept ? (
                    <div style={{ display: "flex", gap: 6 }}>
                      <input
                        autoFocus
                        value={newConceptName}
                        onChange={e => setNewConceptName(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === "Enter") addConcept(newConceptName);
                          if (e.key === "Escape") { setAddingConcept(false); setNewConceptName(""); }
                        }}
                        placeholder="New concept name…"
                        style={{
                          flex: 1,
                          minWidth: 0,
                          padding: "7px 10px",
                          fontSize: 12.5,
                          border: "1px solid var(--border-strong)",
                          borderRadius: "var(--r-sm)",
                          background: "var(--bg-panel)",
                          color: "var(--text)",
                          outline: "none",
                        }}
                      />
                      <button
                        onClick={() => addConcept(newConceptName)}
                        disabled={!newConceptName.trim()}
                        style={{
                          padding: "7px 12px",
                          fontSize: 12.5,
                          fontWeight: 600,
                          borderRadius: "var(--r-sm)",
                          border: "none",
                          background: newConceptName.trim() ? "var(--brand-forest)" : "var(--bg-soft)",
                          color: newConceptName.trim() ? "var(--accent-fg)" : "var(--text-muted)",
                          cursor: newConceptName.trim() ? "pointer" : "not-allowed",
                        }}
                      >
                        Add
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setAddingConcept(true)}
                      style={{
                        width: "100%",
                        padding: "8px 12px",
                        fontSize: 12.5,
                        fontWeight: 500,
                        borderRadius: "var(--r-sm)",
                        border: "1px dashed var(--border-strong)",
                        background: "transparent",
                        color: "var(--text-muted)",
                        cursor: "pointer",
                      }}
                    >
                      ＋ Add concept
                    </button>
                  )}
                </div>
              )}
            </div>
          </aside>
        )}

        {!isMobile && (
          <button
            type="button"
            aria-label="Toggle knowledge map"
            aria-expanded={railOpen}
            title={railOpen ? "Collapse knowledge map" : "Show knowledge map"}
            onPointerDown={onRailTabPointerDown}
            onPointerMove={onRailTabPointerMove}
            onPointerUp={onRailTabPointerUp}
            onPointerCancel={onRailTabPointerCancel}
            onKeyDown={onRailTabKeyDown}
            style={{
              position: "absolute",
              top: "50%",
              right: railW,
              transform: "translateY(-50%)",
              width: 24,
              height: 68,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
              cursor: railDragging ? "grabbing" : "pointer",
              touchAction: "none",
              background: "var(--bg-panel)",
              border: "1px solid var(--border)",
              borderRight: "none",
              borderRadius: "10px 0 0 10px",
              boxShadow: "-3px 0 8px rgba(19, 38, 16, 0.06)",
              color: railOpen ? "var(--brand-forest)" : "var(--text-muted)",
              zIndex: 20,
              transition: railDragging
                ? "none"
                : "right var(--dur) var(--ease), color var(--dur) var(--ease)",
            }}
          >
            {/* Knowledge-graph glyph: three nodes joined in a triangle. */}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="6" cy="7" r="2" />
              <circle cx="17.5" cy="6" r="2" />
              <circle cx="13" cy="17.5" r="2.3" />
              <path d="M7.7 8.6 12 15.4M15.7 7.8 13.7 15.2M8 7.2 15.6 6.2" />
            </svg>
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              style={{
                transform: railOpen ? "rotate(0deg)" : "rotate(180deg)",
                transition: railDragging ? "none" : "transform var(--dur) var(--ease)",
              }}
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        )}
      </div>

      {summary && (
        <SessionSummary
          summary={summary}
          onClose={closeSummary}
          onStartNext={startNextFromSummary}
        />
      )}
    </FullHeightScreen>
  );
}

function SidebarKnowledgeGraph({
  nodes,
  edges,
  highlightId,
  onNodeClick,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlightId?: string;
  onNodeClick?: (n: GraphNode) => void;
}) {
  const [width, setWidth] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} style={{ width: "100%" }}>
      {width > 0 && (
        <KnowledgeGraph
          nodes={nodes}
          edges={edges}
          width={width}
          height={280}
          highlightId={highlightId}
          onNodeClick={onNodeClick}
        />
      )}
    </div>
  );
}

function BackToLearnLink({ onClick }: { onClick: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      data-testid="tutor-back-to-learn"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "0 0 4px",
        background: "transparent",
        border: "none",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        fontSize: 13,
        fontWeight: 400,
        letterSpacing: "normal",
        textTransform: "none",
        color: hover ? "var(--accent)" : "var(--text-muted)",
        transition: "color var(--dur-fast) var(--ease)",
      }}
    >
      <ChevronLeft
        size={14}
        style={{
          transform: hover ? "translateX(-2px)" : "translateX(0)",
          transition: "transform var(--dur-fast) var(--ease)",
        }}
      />
      Back to Learn
    </button>
  );
}

function SessionRow({ s, onResume, onDelete, onRename }: {
  s: Session;
  onResume: (s: Session) => void;
  onDelete: (s: Session) => void;
  onRename: (s: Session, newTopic: string) => void;
}) {
  const del = useConfirm(() => onDelete(s), 3000);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(s.topic);
  // Esc unmounts the input, which fires blur → commitEdit. The blur closure
  // still holds the typed `draft`, so without this guard Esc would commit.
  const cancellingRef = useRef(false);

  const startEdit = () => {
    setDraft(s.topic);
    setEditing(true);
  };

  const commitEdit = () => {
    if (cancellingRef.current) {
      cancellingRef.current = false;
      setEditing(false);
      return;
    }
    const trimmed = draft.trim();
    if (trimmed && trimmed !== s.topic) onRename(s, trimmed);
    setEditing(false);
  };

  const cancelEdit = () => {
    cancellingRef.current = true;
    setDraft(s.topic);
    setEditing(false);
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "8px 10px",
        borderRadius: "var(--r-md)",
        background: "var(--bg-subtle)",
        marginBottom: 6,
      }}
    >
      {editing ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
          <input
            autoFocus
            aria-label="Session name"
            value={draft}
            maxLength={120}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter") {
                e.preventDefault();
                commitEdit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancelEdit();
              }
            }}
            onBlur={commitEdit}
            style={{
              fontSize: 13,
              fontWeight: 600,
              padding: "2px 4px",
              border: "1px solid var(--border)",
              borderRadius: "var(--r-sm)",
              background: "var(--bg)",
              color: "var(--text)",
            }}
          />
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {s.mode} · {s.message_count} msg{s.message_count === 1 ? "" : "s"}
          </span>
        </div>
      ) : (
        <button
          // Keyed on the session id (a stable domain id per
          // docs/frontend-testids.md) — the E2E tutor journey (#392) resumes a
          // seeded `rich-sess-*` session to reach an active chat without the
          // Gemini-backed start-session call.
          data-testid={`tutor-session-resume-${s.id}`}
          onClick={() => onResume(s)}
          style={{
            flex: 1,
            textAlign: "left",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600 }}>{s.topic}</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {s.mode} · {s.message_count} msg{s.message_count === 1 ? "" : "s"}
          </span>
        </button>
      )}
      {!editing && (
        <button
          className="btn btn--ghost btn--sm"
          onClick={startEdit}
          aria-label="Rename session"
          title="Rename"
        >
          <Icon name="pencil" size={12} />
        </button>
      )}
      <button
        className={del.armed ? "btn btn--danger btn--sm" : "btn btn--ghost btn--sm"}
        onClick={del.trigger}
        disabled={editing}
        aria-label={del.armed ? "Confirm delete" : "Delete session"}
        title={del.armed ? "Click again to confirm" : "Delete"}
      >
        {del.armed ? "Confirm" : <Icon name="x" size={12} />}
      </button>
    </div>
  );
}

const GENERAL_TOPIC = "Course overview — pick the next concept I should learn next.";

function TopicPicker({
  value, onChange, onSubmit, concepts, courses, selectedCourseId, activeSemester,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  concepts: { id: string; name: string; course_id: string | null; course_code: string | null; term: string | null }[];
  courses: EnrolledCourse[];
  selectedCourseId: string;
  activeSemester: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const selectedCourse = useMemo(
    () => courses.find(c => c.course_id === selectedCourseId) || null,
    [courses, selectedCourseId],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return concepts
      .filter(c => !selectedCourseId || c.course_id === selectedCourseId)
      .filter(c => (activeSemester ? c.term === activeSemester : true))
      .filter(c => !q || c.name.toLowerCase().includes(q))
      .slice(0, 80);
  }, [concepts, query, selectedCourseId, activeSemester]);

  const isGeneral = value === GENERAL_TOPIC;
  const courseLabel = selectedCourse
    ? (selectedCourse.course_code || selectedCourse.course_name)
    : "this course";
  const generalLabel = selectedCourse
    ? `General — pick what's next in ${courseLabel}`
    : "General — pick what to study next";

  const pickGeneral = () => {
    onChange(GENERAL_TOPIC);
    setOpen(false);
  };
  const pickConcept = (name: string) => {
    onChange(name);
    setOpen(false);
  };
  const pickCustom = () => {
    const q = query.trim();
    if (!q) return;
    onChange(q);
    setOpen(false);
  };

  const displayLabel = isGeneral ? generalLabel : (value || "Pick or type a topic…");

  return (
    <div ref={wrapRef} style={{ position: "relative", marginBottom: 16 }}>
      <button
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => { if (e.key === "Enter" && !open && value.trim()) onSubmit(); }}
        style={{
          width: "100%",
          padding: "12px 14px",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-sm)",
          fontSize: 15,
          background: "var(--bg-input)",
          textAlign: "left",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          color: value ? "var(--text)" : "var(--text-muted)",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {displayLabel}
        </span>
        <Icon name="chev" size={12} />
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0, right: 0,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--r-sm)",
            boxShadow: "var(--shadow-md)",
            zIndex: 30,
            maxHeight: 360,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <input
            autoFocus
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Escape") setOpen(false);
              if (e.key === "Enter") {
                if (filtered.length > 0) pickConcept(filtered[0].name);
                else if (query.trim()) pickCustom();
              }
            }}
            placeholder="Search concepts or type a custom topic…"
            style={{
              width: "100%",
              padding: "10px 12px",
              fontSize: 13,
              border: "none",
              borderBottom: "1px solid var(--border)",
              background: "transparent",
            }}
          />
          <div style={{ overflowY: "auto", flex: 1 }}>
            <button
              onClick={pickGeneral}
              style={{
                width: "100%", padding: "10px 12px", textAlign: "left",
                background: isGeneral ? "var(--accent-soft)" : "transparent",
                border: "none", cursor: "pointer", fontSize: 13,
                display: "flex", flexDirection: "column", gap: 2,
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span style={{ fontWeight: 600, color: "var(--text)" }}>{generalLabel}</span>
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Tutor scans your graph and chooses the next concept.
              </span>
            </button>
            {filtered.length === 0 && query.trim() && (
              <button
                onClick={pickCustom}
                style={{
                  width: "100%", padding: "10px 12px", textAlign: "left",
                  background: "transparent", border: "none", cursor: "pointer", fontSize: 13,
                  color: "var(--text)",
                }}
              >
                Use custom topic: <strong>“{query.trim()}”</strong>
              </button>
            )}
            {filtered.length === 0 && !query.trim() && (
              <div style={{ padding: "16px 12px", fontSize: 12, color: "var(--text-muted)" }}>
                {selectedCourseId
                  ? "No concepts in this course yet — upload a syllabus or scan to populate the graph."
                  : "No concepts in your graph yet."}
              </div>
            )}
            {filtered.map(c => {
              const isSel = value === c.name;
              return (
                <button
                  key={c.id}
                  onClick={() => pickConcept(c.name)}
                  style={{
                    width: "100%", padding: "8px 12px", textAlign: "left",
                    background: isSel ? "var(--accent-soft)" : "transparent",
                    border: "none", cursor: "pointer", fontSize: 13,
                    display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8,
                  }}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text)" }}>
                    {c.name}
                  </span>
                  {c.course_code && (
                    <span className="mono" style={{ fontSize: 10, color: "var(--text-muted)", flexShrink: 0 }}>
                      {c.course_code}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
