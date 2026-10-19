"use client";
/**
 * Dashboard / Home — the learning workspace (redesign prompt 07; frames
 * Xnuwg / bj5Ap / cCYac). One bounded map at left and an open learning
 * context at right: the saved goal, the ONE next activity with its reason
 * and a single state-appropriate action, then at most two real notes and
 * one or two dated items.
 *
 * Arrival, scope changes, selection and Back are READ-ONLY. The page reads
 * the graph, courses, sessions, assignments, notes, the loop status and —
 * for the resumable session — GET /learn/loop/sessions and GET /status.
 * It never starts or closes a session, writes a goal, approves a plan,
 * poses a probe/check or grades: every such step happens in the Learn
 * controller after the student clicks an explicit action here.
 *
 * Every resource carries its own loading / stale / error state
 * (useResource), so a failing region never blanks the others.
 */
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ContextSheet, SaplingAction, StatusMessage } from "@/components/sapling";
import { ManageCoursesModal } from "@/components/ManageCoursesModal";
import { useLoopStatus } from "@/components/learn/useLoopStatus";
import { useUser } from "@/context/UserContext";
import { useFlag } from "@/context/FlagsContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { courseInTerm, useActiveSemester } from "@/lib/useActiveSemester";
import {
  getCourses,
  getGraph,
  getSessions,
  getUpcomingAssignments,
  listNotes,
  type EnrolledCourse,
} from "@/lib/api";
import type { GraphEdge as ApiEdge, GraphNode as ApiNode } from "@/lib/types";
import { apiToGraphNode, type GraphEdge, type GraphNode } from "@/lib/data";
import { now } from "@/lib/testMode";
import { buildQuizHref } from "@/lib/quiz/source";
import { dueSet } from "@/lib/quiz/proposals";
import type { NextStepContext } from "@/lib/dashboard/nextStep";
import { ConceptDetail, type OpenSessionRef } from "./ConceptDetail";
import { FullMap } from "./FullMap";
import { KnowledgeMap } from "./KnowledgeMap";
import { NextStepPanel } from "./NextStepPanel";
import { ComingUp, RecentNotes, RecentSessions, type ListedNote } from "./Sections";
import { TopicList } from "./TopicList";
import { HomeGreeting } from "./Greeting";
import { longDate } from "./format";
import { hasData, useResource } from "./useResource";
import { useLearningDiscovery } from "./useLearningDiscovery";
import styles from "./Dashboard.module.css";

type GraphPayload = { nodes: ApiNode[]; edges: ApiEdge[]; stats: { streak?: number } | null };

const toEdge = (e: ApiEdge): GraphEdge => ({ source: e.source as string, target: e.target as string, strength: e.strength });

export function DashboardWorkspace() {
  const router = useRouter();
  const search = useSearchParams();
  const { userId, userReady, userName } = useUser();
  const [activeSemester, , semesterHydrated] = useActiveSemester();
  const isPhone = useIsMobile();
  const { status: loopStatus, retry: retryLoop } = useLoopStatus(userId, userReady);
  const notetakerHidden = useFlag("hide_notetaker") === "on";
  const uid = userReady && userId ? userId : null;

  // ── Resources (each with its own truthful state) ─────────────────────
  const courses = useResource<EnrolledCourse[]>(
    uid ? `courses|${uid}` : null,
    React.useCallback(() => getCourses(uid!).then((r) => r.courses ?? []), [uid]),
  );
  // Semester scope is read from storage first, so a returning student's
  // first graph read is already scoped (no unscoped-then-scoped double).
  const graph = useResource<GraphPayload>(
    uid && semesterHydrated ? `graph|${uid}|${activeSemester}` : null,
    React.useCallback(
      () => getGraph(uid!, activeSemester || undefined).then((r) => ({ nodes: r.nodes ?? [], edges: r.edges ?? [], stats: r.stats ?? null })),
      [uid, activeSemester],
    ),
  );
  const sessions = useResource(
    uid ? `sessions|${uid}` : null,
    React.useCallback(() => getSessions(uid!, 10).then((r) => r.sessions ?? []), [uid]),
  );
  const assignments = useResource(
    uid ? `assignments|${uid}` : null,
    React.useCallback(() => getUpcomingAssignments(uid!).then((r) => r.assignments ?? []), [uid]),
  );
  const notes = useResource<ListedNote[]>(
    uid && !notetakerHidden ? `notes|${uid}` : null,
    React.useCallback(() => listNotes(uid!).then((r) => (r.notes ?? []) as ListedNote[]), [uid]),
  );

  // ── Derived data ──────────────────────────────────────────────────────
  const courseList = React.useMemo(() => courses.data ?? [], [courses.data]);
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courseList.filter((c) => courseInTerm(c, activeSemester)) : courseList),
    [courseList, activeSemester],
  );
  const allNodes = React.useMemo<GraphNode[]>(
    () => (graph.data ? graph.data.nodes.map((n) => apiToGraphNode(n, courseList)) : []),
    [graph.data, courseList],
  );
  const rawById = React.useMemo(() => new Map((graph.data?.nodes ?? []).map((n) => [n.id, n])), [graph.data]);
  const allEdges = React.useMemo(() => (graph.data?.edges ?? []).map(toEdge), [graph.data]);
  const due = React.useMemo(() => (graph.data ? dueSet(graph.data.nodes) : null), [graph.data]);

  const courseLabel = React.useCallback(
    (id: string | null | undefined) => {
      if (!id) return null;
      const c = courseList.find((co) => co.course_id === id);
      return c ? c.course_code || c.course_name : null;
    },
    [courseList],
  );

  // Map scope: a course filter over the semester-scoped graph. A filter for
  // a course that left the semester scope reads as "all" (never a stale view).
  const [courseFilterState, setCourseFilter] = React.useState("all");
  const courseFilter = scopedCourses.some((c) => c.course_id === courseFilterState) ? courseFilterState : "all";
  const nodes = React.useMemo(
    () => (courseFilter === "all" ? allNodes : allNodes.filter((n) => n.course_id === courseFilter)),
    [allNodes, courseFilter],
  );
  const edges = React.useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    return allEdges.filter((e) => ids.has(e.source) && ids.has(e.target));
  }, [nodes, allEdges]);
  const filterLabel = courseFilter === "all" ? "All courses" : courseLabel(courseFilter) ?? "One course";
  const semesterLabel = activeSemester || "All semesters";

  // ── Learner state (read-only discovery) ───────────────────────────────
  const targetCourseId = React.useMemo(() => {
    if (courseFilter !== "all") return courseFilter;
    const enrolled = new Set(courseList.map((c) => c.course_id));
    const recent = (sessions.data ?? []).find((s) => s.course_id && enrolled.has(s.course_id))?.course_id;
    return recent ?? scopedCourses[0]?.course_id ?? courseList[0]?.course_id ?? null;
  }, [courseFilter, courseList, scopedCourses, sessions.data]);
  const graphLoaded = hasData(graph.status);
  const conceptCount = React.useCallback(
    (courseId: string) => {
      // Only a course inside the loaded (semester-scoped) graph can be said
      // to have zero concepts; anything else is unknown.
      if (!graphLoaded || !scopedCourses.some((c) => c.course_id === courseId)) return null;
      return allNodes.filter((n) => !n.is_subject_root && n.course_id === courseId).length;
    },
    [graphLoaded, scopedCourses, allNodes],
  );
  const discovery = useLearningDiscovery({
    userId: userId ?? "",
    loop: loopStatus,
    sessions: hasData(sessions.status) ? sessions.data : null,
    sessionsFailed: sessions.status === "error",
    courseIds: hasData(courses.status) ? courseList.map((c) => c.course_id) : null,
    coursesFailed: courses.status === "error",
    targetCourseId,
    conceptCount,
  });
  const ctx: NextStepContext = React.useMemo(
    () => ({ conceptName: (id: string) => rawById.get(id)?.concept_name ?? null, courseLabel }),
    [rawById, courseLabel],
  );
  const retryDiscovery = () => {
    if (loopStatus === "error") retryLoop();
    if (sessions.status === "error") sessions.retry();
    if (courses.status === "error") courses.retry();
    discovery.retry();
  };
  const openSession: OpenSessionRef | null =
    discovery.state.kind === "loop-open"
      ? { sessionId: discovery.state.session.sessionId, courseId: discovery.state.session.courseId, courseLabel: courseLabel(discovery.state.session.courseId), loop: discovery.state.session }
      : discovery.state.kind === "legacy-open"
        ? { sessionId: discovery.state.sessionId, courseId: discovery.state.courseId, courseLabel: courseLabel(discovery.state.courseId), loop: null }
        : null;

  // ── Selection (UI context only — never a server write) ────────────────
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const selectedNode = selectedId ? nodes.find((n) => n.id === selectedId) ?? null : null;
  // A selection that left the view (scope change, removed node) is cleared
  // rather than shown stale; the page says so once.
  const lostSelection = !!selectedId && graphLoaded && !selectedNode;
  const [focusToken, setFocusToken] = React.useState(0);
  const [announce, setAnnounce] = React.useState("");
  const [topicsOpen, setTopicsOpen] = React.useState(false);
  const [mapOpen, setMapOpen] = React.useState(false);
  const [conceptSheetOpen, setConceptSheetOpen] = React.useState(false);
  const [manageOpen, setManageOpen] = React.useState(false);

  const select = (n: GraphNode, from: "map" | "list" | "full") => {
    setSelectedId(n.id);
    setAnnounce(`Selected ${n.name}${courseLabel(n.course_id) ? `, ${courseLabel(n.course_id)}` : ""}.`);
    if (from === "list") setTopicsOpen(false);
    if (isPhone && from !== "full") setConceptSheetOpen(true);
    if (!isPhone && from !== "full") setFocusToken((t) => t + 1);
  };
  const backToNext = () => {
    setSelectedId(null);
    setConceptSheetOpen(false);
    setAnnounce("Showing your next step.");
    if (!isPhone && !mapOpen) setTimeout(() => document.getElementById("dashboard-next-title")?.focus(), 60);
  };
  const changeFilter = (id: string) => {
    setCourseFilter(id);
    // A scope change never touches the goal/session; it only clears a
    // selection that the new scope no longer shows.
    if (selectedId && id !== "all" && !allNodes.some((n) => n.id === selectedId && n.course_id === id)) setSelectedId(null);
  };
  const navigate = (href: string) => router.push(href);

  // ── ?suggest= (recommendation deep link): resolved by name, shown by id ─
  const suggest = (search.get("suggest") ?? "").trim();
  const [dismissedSuggest, setDismissedSuggest] = React.useState<string | null>(null);
  const suggestMatches = React.useMemo(
    () => (suggest ? allNodes.filter((n) => !n.is_subject_root && n.name.toLowerCase() === suggest.toLowerCase()) : []),
    [suggest, allNodes],
  );
  const showSuggest = !!suggest && dismissedSuggest !== suggest && graphLoaded;
  const dismissSuggest = () => {
    setDismissedSuggest(suggest);
    const next = new URLSearchParams(search.toString());
    next.delete("suggest");
    const qs = next.toString();
    router.replace(qs ? `/dashboard?${qs}` : "/dashboard");
  };
  const highlightId = showSuggest && suggestMatches.length === 1 ? suggestMatches[0].id : undefined;

  // ── Date line (client clock: no SSR/CSR drift) ────────────────────────
  const [today, setToday] = React.useState<string | null>(null);
  React.useEffect(() => setToday(longDate(now())), []);
  const streak = graph.data?.stats?.streak ?? 0;

  const reviewHref = buildQuizHref({ scope: "due" }, { kind: "dashboard", returnTo: "/dashboard" });

  const detailFor = (n: GraphNode, headingLevel: 2 | 3, testid: string, token?: number) => (
    <ConceptDetail
      key={n.id}
      node={n}
      raw={rawById.get(n.id)}
      nodes={allNodes}
      courseLabel={courseLabel}
      openSession={openSession}
      onBack={backToNext}
      onNavigate={navigate}
      focusToken={token}
      headingLevel={headingLevel}
      testid={testid}
    />
  );

  const nextPanel = (
    <NextStepPanel
      state={discovery.state}
      stale={discovery.stale}
      ctx={ctx}
      onRetry={retryDiscovery}
      onNavigate={navigate}
      onAddCourse={() => setManageOpen(true)}
    />
  );

  return (
    <div className={styles.page} data-testid="dashboard-workspace">
      <header className={styles.header}>
        <div className={styles.headingText}>
          <HomeGreeting userName={userName} titleClassName={styles.title} quoteClassName={styles.quote} />
          <p className={styles.scopeLine} data-testid="dashboard-scope-line">
            {filterLabel} · {semesterLabel}
          </p>
        </div>
        <p className={styles.meta} data-testid="dashboard-meta">
          {today}
          {graphLoaded && streak > 0 && <> · {streak}-day streak</>}
        </p>
      </header>

      {showSuggest && (
        <div className={styles.suggest} role="status" data-testid="dashboard-suggest">
          {suggestMatches.length === 1 ? (
            <>
              <span className={styles.suggestText}>
                <strong>Suggested next:</strong> {suggestMatches[0].name}
                {courseLabel(suggestMatches[0].course_id) && <> · {courseLabel(suggestMatches[0].course_id)}</>}
              </span>
              <SaplingAction tone="quiet" onClick={() => select(suggestMatches[0], "map")} data-testid="dashboard-suggest-show">
                Show on map
              </SaplingAction>
              <SaplingAction
                tone="secondary"
                onClick={() => navigate(buildQuizHref({ concept: suggestMatches[0].id }, { kind: "dashboard", returnTo: "/dashboard" }))}
                data-testid="dashboard-suggest-quiz"
              >
                Start quiz
              </SaplingAction>
            </>
          ) : suggestMatches.length > 1 ? (
            <>
              <span className={styles.suggestText}>
                <strong>Suggested next:</strong> “{suggest}” is in {suggestMatches.length} courses. Pick one:
              </span>
              {suggestMatches.map((n) => (
                <SaplingAction key={n.id} tone="secondary" onClick={() => select(n, "map")} data-testid={`dashboard-suggest-pick-${n.id}`}>
                  {courseLabel(n.course_id) ?? n.subject}
                </SaplingAction>
              ))}
            </>
          ) : (
            <span className={styles.suggestText} data-testid="dashboard-suggest-missing">
              We couldn&apos;t find “{suggest}” on your map. It may have been renamed or removed.
            </span>
          )}
          <SaplingAction tone="quiet" onClick={dismissSuggest} data-testid="dashboard-suggest-dismiss">
            Dismiss
          </SaplingAction>
        </div>
      )}

      <div className={styles.workspace}>
        <div className={styles.contextArea}>
          {!isPhone && selectedNode ? (
            detailFor(selectedNode, 2, "dashboard-concept", focusToken)
          ) : (
            <>
              {lostSelection && (
                <div style={{ marginBottom: 16 }}>
                  <StatusMessage tone="info" testid="dashboard-selection-cleared">
                    The topic you selected isn&apos;t in this view any more, so we cleared it.
                  </StatusMessage>
                </div>
              )}
              {nextPanel}
            </>
          )}
        </div>

        <div className={styles.mapArea}>
          <KnowledgeMap
            nodes={nodes}
            edges={edges}
            graphStatus={graph.status}
            onRetryGraph={graph.retry}
            scopedCourses={scopedCourses}
            coursesReady={hasData(courses.status)}
            courseFilter={courseFilter}
            onCourseFilter={changeFilter}
            semesterLabel={semesterLabel}
            preview={isPhone}
            selectedId={selectedNode?.id ?? null}
            highlightId={highlightId}
            onSelect={(n) => select(n, "map")}
            onOpenFullMap={() => setMapOpen(true)}
            onViewTopics={() => setTopicsOpen(true)}
            onManageCourses={() => setManageOpen(true)}
            suspended={mapOpen}
          />
        </div>

        <div className={styles.notesArea}>
          <RecentNotes notes={notes} notetakerHidden={notetakerHidden} courseLabel={courseLabel} />
        </div>

        <div className={styles.comingArea}>
          <ComingUp
            assignments={assignments}
            due={due}
            reviewHref={reviewHref}
            semesterScoped={!!activeSemester}
            onNavigate={navigate}
          />
          <RecentSessions sessions={sessions} semesterScoped={!!activeSemester} courseLabel={courseLabel} onNavigate={navigate} />
        </div>
      </div>

      <p className="sapling-visually-hidden" aria-live="polite" data-testid="dashboard-announce">{announce}</p>

      <FullMap
        open={mapOpen}
        onClose={() => setMapOpen(false)}
        scopeLabel={`${filterLabel} · ${semesterLabel}`}
        nodes={nodes}
        edges={edges}
        selectedId={selectedNode?.id ?? null}
        highlightId={highlightId}
        onSelect={(n) => select(n, "full")}
        side={
          selectedNode ? (
            detailFor(selectedNode, 3, "dashboard-full-map-concept")
          ) : (
            <p className={styles.muted} data-testid="dashboard-full-map-hint">
              Select a topic on the map to see its state and evidence. Selecting changes nothing about your goal or plan.
            </p>
          )
        }
      />

      <ContextSheet
        open={topicsOpen}
        onClose={() => setTopicsOpen(false)}
        title="Topics on your map"
        side={isPhone ? "bottom" : "right"}
        testid="dashboard-topics"
      >
        <p className={styles.muted} style={{ marginTop: 0 }}>{filterLabel} · {semesterLabel}</p>
        <TopicList nodes={nodes} raw={rawById} selectedId={selectedNode?.id ?? null} courseLabel={courseLabel} onPick={(n) => select(n, "list")} />
      </ContextSheet>

      <ContextSheet
        open={isPhone && conceptSheetOpen && !!selectedNode && !mapOpen}
        onClose={backToNext}
        title={selectedNode?.is_subject_root ? "Selected course" : "Selected topic"}
        testid="dashboard-concept-sheet"
      >
        {selectedNode && detailFor(selectedNode, 3, "dashboard-sheet-concept")}
      </ContextSheet>

      <ManageCoursesModal
        open={manageOpen}
        userId={userId}
        courses={courseList}
        onClose={() => setManageOpen(false)}
        onChanged={() => {
          courses.retry();
          graph.retry();
        }}
      />
    </div>
  );
}
