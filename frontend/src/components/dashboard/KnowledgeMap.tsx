"use client";
import React from "react";

import { KnowledgeGraph } from "@/components/graph/KnowledgeGraph";
import { SaplingAction, StatusMessage } from "@/components/sapling";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { SOURCE_GRAPH_PALETTE, TIER_LABEL } from "@/lib/graph/nodeStyle";
import { TIERS, tierOf } from "./StateGlyph";
import type { ResourceStatus } from "./useResource";
import styles from "./Dashboard.module.css";

/** Measure a box for the graph (it takes explicit width/height). */
export function useBoxSize(initial: { w: number; h: number }) {
  const [size, setSize] = React.useState(initial);
  const roRef = React.useRef<ResizeObserver | null>(null);
  const ref = React.useCallback((el: HTMLDivElement | null) => {
    roRef.current?.disconnect();
    roRef.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = Math.round(e.contentRect.width);
        const h = Math.round(e.contentRect.height);
        if (w > 0 && h > 0) setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
      }
    });
    ro.observe(el);
    roRef.current = ro;
  }, []);
  return [size, ref] as const;
}

export interface KnowledgeMapProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  graphStatus: ResourceStatus;
  onRetryGraph: () => void;
  /** Courses in the semester scope, for the course select and progress. */
  scopedCourses: EnrolledCourse[];
  coursesReady: boolean;
  courseFilter: string;
  onCourseFilter: (courseId: string) => void;
  semesterLabel: string;
  /** Static overview (phone): page scrolls past it, exploration is deliberate. */
  preview: boolean;
  selectedId: string | null;
  highlightId?: string;
  onSelect: (n: GraphNode) => void;
  onOpenFullMap: () => void;
  onViewTopics: () => void;
  onManageCourses: () => void;
  openMapRef?: React.Ref<HTMLButtonElement>;
  topicsRef?: React.Ref<HTMLButtonElement>;
  /** The full map is open: this canvas stands down so only ONE graph (and
   *  one set of graph testids / a11y node list) exists at a time. */
  suspended?: boolean;
}

/**
 * The bounded map: one fine olive boundary, a sage header (title, scope,
 * counts), named controls, the canvas and the four-state legend. Counts are
 * computed from exactly the nodes the canvas renders, so map and numbers
 * never disagree; the scope line says "All courses" when it is.
 */
export function KnowledgeMap(props: KnowledgeMapProps) {
  const {
    nodes, edges, graphStatus, onRetryGraph, scopedCourses, coursesReady, courseFilter, onCourseFilter,
    semesterLabel, preview, selectedId, highlightId, onSelect, onOpenFullMap, onViewTopics, onManageCourses,
    openMapRef, topicsRef, suspended = false,
  } = props;
  const [size, boxRef] = useBoxSize({ w: preview ? 320 : 720, h: preview ? 260 : 520 });
  const [coursesOpen, setCoursesOpen] = React.useState(false);
  const coursesId = React.useId();
  const selectId = React.useId();

  const concepts = nodes.filter((n) => !n.is_subject_root);
  const hubs = nodes.filter((n) => n.is_subject_root);
  const loaded = graphStatus === "ready" || graphStatus === "refreshing" || graphStatus === "stale";
  const filterName =
    courseFilter === "all"
      ? "All courses"
      : scopedCourses.find((c) => c.course_id === courseFilter)?.course_code ||
        scopedCourses.find((c) => c.course_id === courseFilter)?.course_name ||
        "One course";

  const progress = React.useMemo(
    () =>
      scopedCourses.map((c) => {
        const own = nodes.filter((n) => !n.is_subject_root && n.course_id === c.course_id);
        const by = Object.fromEntries(TIERS.map((t) => [t, own.filter((n) => tierOf(n.mastery_tier) === t).length])) as Record<
          (typeof TIERS)[number],
          number
        >;
        return { course: c, total: own.length, by };
      }),
    [scopedCourses, nodes],
  );

  return (
    <section className={styles.mapCard} aria-labelledby="dashboard-map-title" data-testid="dashboard-map">
      <div className={styles.mapHeader}>
        <h2 id="dashboard-map-title" className={styles.mapTitle}>Your knowledge</h2>
        <p className={styles.counts} data-testid="dashboard-map-counts" aria-live="polite">
          {loaded
            ? `${concepts.length} ${concepts.length === 1 ? "concept" : "concepts"} · ${hubs.length} ${hubs.length === 1 ? "course" : "courses"}`
            : graphStatus === "error"
              ? "Map unavailable"
              : "Loading…"}
        </p>
      </div>

      <div className={styles.toolbar}>
        <label className={styles.field} htmlFor={selectId}>
          <span className="sapling-visually-hidden">Show courses</span>
          <select
            id={selectId}
            className={styles.select}
            value={courseFilter}
            onChange={(e) => onCourseFilter(e.target.value)}
            data-testid="dashboard-course-filter"
          >
            <option value="all">All courses</option>
            {scopedCourses.map((c) => (
              <option key={c.course_id} value={c.course_id}>
                {c.course_code ? `${c.course_code} — ${c.course_name}` : c.course_name}
              </option>
            ))}
          </select>
        </label>
        <span className={styles.semester} data-testid="dashboard-semester-scope">{semesterLabel}</span>
        <span className={styles.toolbarSpacer} />
        {coursesReady && (
          <button
            type="button"
            className={styles.toolButton}
            aria-expanded={coursesOpen}
            aria-controls={coursesId}
            onClick={() => setCoursesOpen((o) => !o)}
            data-testid="dashboard-courses-key-toggle"
          >
            {coursesOpen ? "Hide course progress" : "Course progress"}
          </button>
        )}
        <button type="button" ref={topicsRef} className={styles.toolButton} onClick={onViewTopics} data-testid="dashboard-view-topics">
          View topics
        </button>
        {!preview && (
          <button type="button" ref={openMapRef} className={styles.toolButton} onClick={onOpenFullMap} data-testid="dashboard-open-map">
            Open full map <span aria-hidden="true">↗</span>
          </button>
        )}
      </div>

      {coursesOpen && coursesReady && (
        <div id={coursesId} className={styles.courses} data-testid="dashboard-courses">
          {progress.length === 0 && <p className={styles.muted} style={{ margin: 0 }}>Nothing enrolled this semester.</p>}
          {progress.map(({ course, total, by }) => (
            <div key={course.course_id} className={styles.courseRow}>
              <div className={styles.courseRowHead}>
                <strong className={styles.courseCode} data-testid="dashboard-course-code">
                  {course.course_code || course.course_name}
                </strong>
                <span className={styles.legendNote}>
                  {total === 0 ? "No concepts yet" : TIERS.map((t) => `${by[t]} ${TIER_LABEL[t].toLowerCase()}`).join(" · ")}
                </span>
              </div>
              {total > 0 && (
                <div className={styles.bar} aria-hidden="true">
                  {TIERS.map((t) =>
                    by[t] > 0 ? <div key={t} style={{ width: `${(by[t] / total) * 100}%`, background: SOURCE_GRAPH_PALETTE[t] }} /> : null,
                  )}
                </div>
              )}
            </div>
          ))}
          <div>
            <SaplingAction tone="secondary" onClick={onManageCourses} data-testid="dashboard-courses-manage">
              Courses &amp; semesters
            </SaplingAction>
          </div>
        </div>
      )}

      {graphStatus === "stale" && (
        <div className={styles.mapStatus}>
          <StatusMessage tone="info" onRetry={onRetryGraph} testid="dashboard-map-stale">
            Couldn&apos;t refresh your map; showing the last one we loaded.
          </StatusMessage>
        </div>
      )}

      <div
        ref={boxRef}
        className={preview ? styles.canvasPreview : styles.canvas}
        data-testid={preview ? "dashboard-map-preview" : "dashboard-map-canvas"}
      >
        {loaded && !suspended && (
          <KnowledgeGraph
            appearance="sapling"
            nodes={nodes}
            edges={edges}
            width={size.w}
            height={size.h}
            selectedId={selectedId}
            highlightId={highlightId}
            onNodeClick={preview ? undefined : onSelect}
            interactive={!preview}
          />
        )}
        {(graphStatus === "loading" || graphStatus === "idle") && (
          <div className={styles.canvasOverlay}>
            <StatusMessage tone="pending" testid="dashboard-map-loading">Loading your map…</StatusMessage>
          </div>
        )}
        {graphStatus === "error" && (
          <div className={styles.canvasOverlay}>
            <StatusMessage tone="error" title="Couldn't load your map" onRetry={onRetryGraph} testid="dashboard-map-error">
              Your progress is safe; this is only a loading problem.
            </StatusMessage>
          </div>
        )}
        {loaded && concepts.length === 0 && (
          <div className={styles.canvasOverlay}>
            <p className={styles.muted} data-testid="dashboard-map-empty" style={{ textAlign: "center" }}>
              {courseFilter === "all"
                ? "No concepts on your map yet. Upload course material in Library and they appear here."
                : `No concepts on your map for ${filterName} yet.`}
            </p>
          </div>
        )}
      </div>

      {preview && (
        <div className={styles.previewActions}>
          <SaplingAction onClick={onOpenFullMap} ref={openMapRef} data-testid="dashboard-open-map">
            Open full map <span aria-hidden="true">↗</span>
          </SaplingAction>
        </div>
      )}

      <ul className={styles.legend} aria-label="Map key">
        {TIERS.map((t) => (
          <li key={t}>
            {/* A disc, exactly as the canvas draws the node (the map encodes
                state by fill only; the text names it). */}
            <svg className={styles.glyph} viewBox="0 0 12 12" aria-hidden="true" focusable="false">
              <circle cx="6" cy="6" r="5.5" fill={SOURCE_GRAPH_PALETTE[t]} />
            </svg>
            {TIER_LABEL[t]}
          </li>
        ))}
        <li className={styles.legendNote}>Brown circles are courses; bigger circles have a higher mastery estimate.</li>
      </ul>
    </section>
  );
}
