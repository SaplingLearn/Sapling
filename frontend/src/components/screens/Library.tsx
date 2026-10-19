"use client";
import React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Icon } from "../Icon";
import { DocumentUploadModal } from "../DocumentUploadModal";
import { ManageCoursesModal } from "../ManageCoursesModal";
import { LibraryGridSkeleton, LibraryListSkeleton } from "../Skeleton";
import {
  BotanicalIcon,
  ContextPanel,
  PageHeading,
  SaplingAction,
  SectionHeading,
  SelectableRow,
  StatusMessage,
} from "@/components/sapling";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useIsMobile } from "@/lib/useIsMobile";
import { useUser } from "@/context/UserContext";
import {
  getDocuments,
  deleteDocument,
  getCourses,
  scanDocumentConcepts,
  scanCourseConcepts,
  type EnrolledCourse,
  type ScanConceptsResponse,
} from "@/lib/api";
import type { Document as Doc, ConceptNote } from "@/lib/types";
import styles from "./Library.module.css";

// Lazy-load to keep mermaid/katex/highlight.js out of the OpenNext
// server bundle. See ChatPanel.tsx for the rationale.
const MarkdownChat = dynamic(
  () => import("../chat/MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

/* Course Library (redesign prompt 03; Pen frames KTCuj desktop / AS0Yn
 * phone). Every row is a real `Document` from GET /api/documents/user/{id};
 * nothing here invents page counts, previews, byte sizes or download links,
 * because the Document contract has none of them. */

type Cat = Doc["category"] | "all";
type View = "grid" | "list";

export const CATEGORIES: readonly Doc["category"][] = [
  "lecture_notes", "syllabus", "reading", "slides", "study_guide", "assignment", "other",
];

const CATEGORY_LABEL: Record<Doc["category"], string> = {
  lecture_notes: "Lecture notes",
  syllabus: "Syllabus",
  reading: "Reading",
  slides: "Slides",
  study_guide: "Study guide",
  assignment: "Assignment",
  other: "Other",
};

export function categoryLabel(cat: string): string {
  return CATEGORY_LABEL[cat as Doc["category"]] ?? cat.replace(/_/g, " ");
}

/**
 * The file type a learner sees, read ONLY from the file name's extension.
 * It is not the document's category and not a server-verified MIME type;
 * the filter that uses it is labelled separately from Category.
 */
export function fileTypeOf(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  if (dot <= 0 || dot === fileName.length - 1) return "other";
  const ext = fileName.slice(dot + 1).toLowerCase();
  return /^[a-z0-9]{1,5}$/.test(ext) ? ext : "other";
}

export interface LibraryFilters {
  query: string;
  cat: Cat;
  /** "all" | "uncategorized" | a course_id */
  course: string;
  /** "all" | an extension from fileTypeOf */
  fileType: string;
}

export const NO_FILTERS: LibraryFilters = { query: "", cat: "all", course: "all", fileType: "all" };

/** Search (file name + summary, case-insensitive) AND category AND course AND file type. */
export function filterDocuments(docs: readonly Doc[], f: LibraryFilters): Doc[] {
  const q = f.query.trim().toLowerCase();
  return docs.filter((d) => {
    if (f.cat !== "all" && d.category !== f.cat) return false;
    if (f.course === "uncategorized" && d.course_id) return false;
    if (f.course !== "all" && f.course !== "uncategorized" && d.course_id !== f.course) return false;
    if (f.fileType !== "all" && fileTypeOf(d.file_name) !== f.fileType) return false;
    if (q && !d.file_name.toLowerCase().includes(q) && !(d.summary || "").toLowerCase().includes(q)) return false;
    return true;
  });
}

// #449 (upstream, out of scope here): GET /api/graph/{userId}/courses
// returns one row per ENROLLMENT, so a course with two offerings (e.g.
// CS101 in both fall and spring) surfaces as two rows sharing the same
// course_id — the API can't collapse that itself since enrollment_id-
// keyed consumers (the gradebook) depend on the per-enrollment rows.
// This is the Library render-side dedupe: one filter option / label per
// distinct abstract course, keeping the first enrollment's row (color,
// course_code, course_name) as the stable representative.
export function dedupeCourses(courses: readonly EnrolledCourse[]): EnrolledCourse[] {
  const byId = new Map<string, EnrolledCourse>();
  for (const c of courses) {
    if (!byId.has(c.course_id)) byId.set(c.course_id, c);
  }
  return [...byId.values()];
}

/** The scan copy, from the response's real counts. Adding concepts to the
 *  graph is not evidence the learner knows them, so the copy never says so. */
export function scanResultText(res: Pick<ScanConceptsResponse, "added" | "existing">, target: string): string {
  const plural = (n: number) => `${n} concept${n === 1 ? "" : "s"}`;
  if (res.added > 0) {
    return res.existing > 0
      ? `Added ${plural(res.added)} to ${target}'s knowledge graph; ${res.existing} ${res.existing === 1 ? "was" : "were"} already there.`
      : `Added ${plural(res.added)} to ${target}'s knowledge graph.`;
  }
  if (res.existing > 0) return `No new concepts: ${target}'s graph already covers the ${plural(res.existing)} found.`;
  return `Nothing to add yet: the scan found no concepts for ${target}.`;
}

const errText = (err: unknown) => {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  return msg || "Unknown error";
};

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatLongDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Browser connectivity. Only drives copy and disabled states — nothing is
 *  retried or re-sent automatically when it flips back to online. */
function useOnline(): boolean {
  const [online, setOnline] = React.useState(true);
  React.useEffect(() => {
    if (typeof navigator !== "undefined") setOnline(navigator.onLine !== false);
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

/** Phone and small-tablet widths get the detail as a full-height sheet. */
export const LIBRARY_SHEET_BREAKPOINT = 900;

type LoadState = "loading" | "ready" | "error";
type ScanStatus =
  | { state: "idle" }
  | { state: "scanning" }
  | { state: "done"; text: string }
  | { state: "error"; text: string };

export function Library() {
  const toast = useToast();
  const { userId, userReady } = useUser();
  const online = useOnline();
  const isSheet = useIsMobile(LIBRARY_SHEET_BREAKPOINT);

  const [documents, setDocuments] = React.useState<Doc[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [loadState, setLoadState] = React.useState<LoadState>("loading");
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [refreshError, setRefreshError] = React.useState<string | null>(null);
  const [coursesError, setCoursesError] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [loadedAt, setLoadedAt] = React.useState<Date | null>(null);

  const [filters, setFilters] = React.useState<LibraryFilters>(NO_FILTERS);
  const [view, setView] = React.useState<View>("list");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [coursesOpen, setCoursesOpen] = React.useState(false);
  const [courseScan, setCourseScan] = React.useState<ScanStatus>({ state: "idle" });
  /** Phones show Category / File type / Layout behind one disclosure. */
  const [moreFilters, setMoreFilters] = React.useState(false);

  const hasLoaded = React.useRef(false);
  const loadSeq = React.useRef(0);
  const resultsRef = React.useRef<HTMLParagraphElement>(null);

  const load = React.useCallback(async () => {
    if (!userId) return;
    const seq = ++loadSeq.current;
    setRefreshing(true);
    const [docsRes, coursesRes] = await Promise.allSettled([getDocuments(userId), getCourses(userId)]);
    if (seq !== loadSeq.current) return; // a newer load owns the state
    setRefreshing(false);

    if (coursesRes.status === "fulfilled") {
      setCourses(coursesRes.value.courses || []);
      setCoursesError(null);
    } else {
      setCoursesError(errText(coursesRes.reason));
    }

    if (docsRes.status === "fulfilled") {
      setDocuments((docsRes.value.documents || []) as Doc[]);
      hasLoaded.current = true;
      setLoadState("ready");
      setLoadError(null);
      setRefreshError(null);
      setLoadedAt(new Date());
    } else if (hasLoaded.current) {
      // Keep what was already on screen; say the refresh failed.
      setRefreshError(errText(docsRes.reason));
    } else {
      setLoadState("error");
      setLoadError(errText(docsRes.reason));
    }
  }, [userId]);

  React.useEffect(() => {
    if (userReady && userId) void load();
  }, [userReady, userId, load]);

  const dedupedCourses = React.useMemo(() => dedupeCourses(courses), [courses]);

  const courseLookup = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of dedupedCourses) map[c.course_id] = c.course_code || c.course_name;
    return map;
  }, [dedupedCourses]);

  const courseLabelOf = React.useCallback(
    (d: Doc) => (d.course_id ? courseLookup[d.course_id] ?? "Course" : "Uncategorized"),
    [courseLookup],
  );

  const courseCounts = React.useMemo(() => {
    const counts: Record<string, number> = { all: documents.length, uncategorized: 0 };
    for (const d of documents) {
      if (!d.course_id) { counts.uncategorized += 1; continue; }
      counts[d.course_id] = (counts[d.course_id] || 0) + 1;
    }
    return counts;
  }, [documents]);

  const fileTypes = React.useMemo(
    () => [...new Set(documents.map((d) => fileTypeOf(d.file_name)))].sort(),
    [documents],
  );

  const filtered = React.useMemo(() => filterDocuments(documents, filters), [documents, filters]);
  const filtersActive =
    filters.query.trim() !== "" || filters.cat !== "all" || filters.course !== "all" || filters.fileType !== "all";
  const extraActive = (filters.cat !== "all" ? 1 : 0) + (filters.fileType !== "all" ? 1 : 0);

  const detail = React.useMemo(
    () => (selectedId ? documents.find((d) => d.id === selectedId) ?? null : null),
    [documents, selectedId],
  );

  const courseScanCourseId =
    filters.course !== "all" && filters.course !== "uncategorized" ? filters.course : null;
  const courseScanLabel = courseScanCourseId ? courseLookup[courseScanCourseId] ?? "Course" : "";

  // A new course selection starts with no stale scan result.
  React.useEffect(() => { setCourseScan({ state: "idle" }); }, [courseScanCourseId]);

  const runCourseScan = React.useCallback(async () => {
    if (!userId || !courseScanCourseId) return;
    setCourseScan({ state: "scanning" });
    try {
      const res = await scanCourseConcepts(courseScanCourseId, userId);
      setCourseScan({ state: "done", text: scanResultText(res, courseScanLabel) });
    } catch (err) {
      setCourseScan({ state: "error", text: `Scanning ${courseScanLabel} failed: ${errText(err)}. Nothing was added.` });
    }
  }, [userId, courseScanCourseId, courseScanLabel]);

  const setFilter = <K extends keyof LibraryFilters>(key: K, value: LibraryFilters[K]) =>
    setFilters((prev) => ({ ...prev, [key]: value }));

  const noCourses = loadState === "ready" && !coursesError && dedupedCourses.length === 0;
  const uploadDisabled = loadState !== "ready" || courses.length === 0 || !online;
  const uploadHint = !online
    ? "You're offline. Upload needs a connection."
    : noCourses
      ? "Add a course first: every material belongs to a course."
      : coursesError && courses.length === 0
        ? "Upload is unavailable until your courses load."
        : null;

  const closeDetail = React.useCallback(() => setSelectedId(null), []);

  const handleDeleted = React.useCallback(async (doc: Doc) => {
    setSelectedId((cur) => (cur === doc.id ? null : cur));
    toast.success(`Deleted ${doc.file_name}`);
    await load();
    resultsRef.current?.focus();
  }, [load, toast]);

  return (
    <div className={styles.page} data-testid="library">
      <PageHeading
        eyebrow="Course library"
        title="Good ideas start somewhere."
        description="Bring your course materials together. Connect them to what you learn."
        testid="library-heading"
        actions={
          <div className={styles.headingActions}>
            <SaplingAction
              data-testid="library-upload"
              onClick={() => setUploadOpen(true)}
              disabled={uploadDisabled}
              aria-describedby={uploadHint ? "library-upload-hint" : undefined}
            >
              Upload material <Icon name="plus" size={14} />
            </SaplingAction>
            {noCourses && (
              <SaplingAction tone="secondary" data-testid="library-add-course" onClick={() => setCoursesOpen(true)}>
                Add a course
              </SaplingAction>
            )}
            {uploadHint && (
              <p id="library-upload-hint" className={styles.hint} data-testid="library-upload-hint">{uploadHint}</p>
            )}
          </div>
        }
      />

      {!online && (
        <StatusMessage tone="info" title="You're offline" testid="library-offline">
          {loadState === "ready"
            ? "Showing the materials that were already loaded. Uploads, scans and deletes need a connection, and nothing is sent automatically when you reconnect."
            : "Your library can't load until you're back online. Nothing is sent automatically when you reconnect."}
        </StatusMessage>
      )}

      <div className={styles.body}>
        <section className={styles.main} aria-labelledby="library-materials-heading">
          <h2 id="library-materials-heading" className="sapling-visually-hidden">Materials</h2>

          {loadState !== "error" && (
          <div className={styles.filters} role="search" aria-label="Filter materials">
            <div className={`${styles.field} ${styles.searchField}`}>
              <label htmlFor="library-search" className={styles.label}>Search</label>
              <span className={styles.searchWrap}>
                <span className={styles.searchIcon} aria-hidden="true"><Icon name="search" size={16} /></span>
                <input
                  id="library-search"
                  data-testid="library-search"
                  className={`${styles.control} ${styles.searchInput}`}
                  type="search"
                  value={filters.query}
                  onChange={(e) => setFilter("query", e.target.value)}
                  placeholder="Search names and summaries…"
                  autoComplete="off"
                />
              </span>
            </div>
            <div className={styles.field}>
              <label htmlFor="library-course-select" className={styles.label}>Course</label>
              <select
                id="library-course-select"
                data-testid="library-course-filter"
                className={styles.control}
                value={filters.course}
                onChange={(e) => setFilter("course", e.target.value)}
              >
                <option value="all">All courses ({courseCounts.all || 0})</option>
                <option value="uncategorized">Uncategorized ({courseCounts.uncategorized || 0})</option>
                {dedupedCourses.map((course) => (
                  <option key={course.course_id} value={course.course_id}>
                    {course.course_code || course.course_name} ({courseCounts[course.course_id] || 0})
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              className={styles.moreToggle}
              aria-expanded={moreFilters}
              aria-controls="library-more-filters"
              data-testid="library-more-filters"
              onClick={() => setMoreFilters((v) => !v)}
            >
              {moreFilters ? "Fewer filters" : `More filters${extraActive ? ` (${extraActive})` : ""}`}
            </button>
            <div id="library-more-filters" className={styles.extraFilters} data-open={moreFilters}>
            <div className={styles.field}>
              <label htmlFor="library-category-select" className={styles.label}>Category</label>
              <select
                id="library-category-select"
                data-testid="library-category-filter"
                className={styles.control}
                value={filters.cat}
                onChange={(e) => setFilter("cat", e.target.value as Cat)}
              >
                <option value="all">All categories</option>
                {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
              </select>
            </div>
            <div className={styles.field}>
              <label htmlFor="library-filetype-select" className={styles.label}>File type</label>
              <select
                id="library-filetype-select"
                data-testid="library-filetype-filter"
                className={styles.control}
                value={filters.fileType}
                aria-describedby="library-filetype-note"
                onChange={(e) => setFilter("fileType", e.target.value)}
              >
                <option value="all">All file types</option>
                {fileTypes.map((t) => <option key={t} value={t}>{t === "other" ? "Other" : t.toUpperCase()}</option>)}
              </select>
              <span id="library-filetype-note" className="sapling-visually-hidden">
                Read from each file name&apos;s extension. Separate from category.
              </span>
            </div>
            <div className={styles.viewToggle} role="group" aria-label="Layout">
              <button
                type="button"
                className={styles.viewButton}
                aria-pressed={view === "list"}
                data-testid="library-view-list"
                onClick={() => setView("list")}
              >
                <ListGlyph /> List
              </button>
              <button
                type="button"
                className={styles.viewButton}
                aria-pressed={view === "grid"}
                data-testid="library-view-grid"
                onClick={() => setView("grid")}
              >
                <GridGlyph /> Grid
              </button>
            </div>
            </div>
          </div>
          )}

          {coursesError && (
            <StatusMessage
              tone="error"
              title="Your courses didn't load"
              onRetry={() => void load()}
              retrying={refreshing}
              testid="library-courses-error"
            >
              Course names, the course filter and Upload may be incomplete until they do. Your materials are unaffected.
            </StatusMessage>
          )}

          {refreshError && (
            <StatusMessage
              tone="error"
              title="Couldn't refresh your library"
              onRetry={() => void load()}
              retrying={refreshing}
              testid="library-refresh-error"
            >
              {`Still showing the materials loaded${loadedAt ? ` at ${loadedAt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}` : ""}. Details: ${refreshError}`}
            </StatusMessage>
          )}

          {loadState === "loading" && (
            <div aria-busy="true" data-testid="library-loading">
              <p className="sapling-visually-hidden" role="status">Loading your library…</p>
              {view === "grid" ? <LibraryGridSkeleton count={6} /> : <LibraryListSkeleton count={6} />}
            </div>
          )}

          {loadState === "error" && (
            <StatusMessage
              tone="error"
              title="We couldn't load your library"
              onRetry={() => void load()}
              retrying={refreshing}
              testid="library-load-error"
            >
              {online
                ? `Your materials are still saved; this page just couldn't fetch them.${loadError ? ` Details: ${loadError}` : ""}`
                : "You're offline, so your materials couldn't be fetched. They are still saved."}
            </StatusMessage>
          )}

          {loadState === "ready" && (
            <>
              <div className={styles.resultsBar}>
                <p ref={resultsRef} tabIndex={-1} className={styles.resultsCount} data-testid="library-results-count" aria-live="polite">
                  {filtersActive
                    ? `Showing ${filtered.length} of ${documents.length} material${documents.length === 1 ? "" : "s"}`
                    : `${documents.length} material${documents.length === 1 ? "" : "s"}`}
                </p>
                <div className={styles.resultsActions}>
                  {courseScanCourseId && (
                    <SaplingAction
                      tone="secondary"
                      data-testid="library-course-scan"
                      onClick={runCourseScan}
                      disabled={courseScan.state === "scanning" || !online}
                    >
                      <Icon name="sparkle" size={14} />
                      {courseScan.state === "scanning" ? "Scanning…" : `Scan ${courseScanLabel}`}
                    </SaplingAction>
                  )}
                  <SaplingAction
                    tone="quiet"
                    data-testid="library-refresh"
                    onClick={() => void load()}
                    disabled={refreshing}
                  >
                    {refreshing ? "Refreshing…" : "Refresh"}
                  </SaplingAction>
                  <SaplingAction tone="quiet" data-testid="library-manage-courses" onClick={() => setCoursesOpen(true)}>
                    Manage courses
                  </SaplingAction>
                </div>
              </div>

              {courseScanCourseId && courseScan.state !== "idle" && (
                <StatusMessage
                  tone={courseScan.state === "scanning" ? "pending" : courseScan.state === "error" ? "error" : "success"}
                  onRetry={courseScan.state === "error" ? runCourseScan : undefined}
                  testid="library-course-scan-status"
                >
                  {courseScan.state === "scanning"
                    ? `Scanning ${courseScanLabel}'s materials for concepts…`
                    : courseScan.text}
                </StatusMessage>
              )}

              {documents.length === 0 ? (
                <div className={styles.empty} data-testid="library-empty">
                  <SectionHeading>Your library is quiet</SectionHeading>
                  <p>
                    {noCourses
                      ? "Add a course, then upload a syllabus, lecture notes or a reading. Sapling summarizes each file and pulls out its key concepts."
                      : "Upload a syllabus, lecture notes or a reading. Sapling summarizes each file and pulls out its key concepts."}
                  </p>
                  <div className={styles.emptyActions}>
                    {noCourses ? (
                      <SaplingAction onClick={() => setCoursesOpen(true)} data-testid="library-empty-add-course">Add a course</SaplingAction>
                    ) : (
                      <SaplingAction onClick={() => setUploadOpen(true)} disabled={uploadDisabled} data-testid="library-empty-upload">
                        Upload material
                      </SaplingAction>
                    )}
                  </div>
                </div>
              ) : filtered.length === 0 ? (
                <div className={styles.empty} data-testid="library-no-matches">
                  <SectionHeading>No materials match these filters</SectionHeading>
                  <p>Nothing in your library matches the current search and filters.</p>
                  <div className={styles.emptyActions}>
                    <SaplingAction tone="secondary" onClick={() => setFilters(NO_FILTERS)} data-testid="library-clear-filters">
                      Clear filters
                    </SaplingAction>
                  </div>
                </div>
              ) : view === "list" ? (
                <div className={styles.listWrap}>
                  <div className={styles.listHeader} aria-hidden="true">
                    <span>Material</span>
                    <span>Added</span>
                  </div>
                  <ul className={styles.list} data-testid="library-list">
                    {filtered.map((d) => (
                      <li key={d.id}>
                        <SelectableRow
                          selected={detail?.id === d.id}
                          testid={`library-doc-${d.id}`}
                          className={styles.row}
                          onClick={() => setSelectedId(d.id)}
                          aria-haspopup={isSheet ? "dialog" : undefined}
                        >
                          <BotanicalIcon name="paper" size={22} className={styles.paper} />
                          <span className={styles.rowText}>
                            <span className={styles.rowName}>{d.file_name}</span>
                            <span className={styles.rowMeta}>
                              <DocMeta doc={d} courseLabel={courseLabelOf(d)} />
                              <span className={styles.rowDateInline}> · {formatShortDate(d.created_at)}</span>
                            </span>
                            {d.summary && <span className={styles.rowSummary}>{d.summary}</span>}
                          </span>
                          <span className={styles.rowDate}>{formatShortDate(d.created_at)}</span>
                          <span className={styles.chevron} aria-hidden="true"><Icon name="chev" size={14} /></span>
                        </SelectableRow>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <ul className={styles.grid} data-testid="library-grid">
                  {filtered.map((d) => (
                    <li key={d.id}>
                      <SelectableRow
                        selected={detail?.id === d.id}
                        testid={`library-doc-${d.id}`}
                        className={styles.card}
                        onClick={() => setSelectedId(d.id)}
                        aria-haspopup={isSheet ? "dialog" : undefined}
                      >
                        <span className={styles.cardTop}>
                          <BotanicalIcon name="paper" size={26} className={styles.paper} />
                          <span className={styles.chip}>{categoryLabel(d.category)}</span>
                        </span>
                        <span className={styles.cardName}>{d.file_name}</span>
                        <span className={styles.rowMeta}>
                          {courseLabelOf(d)} · {fileTypeOf(d.file_name).toUpperCase()} · {formatShortDate(d.created_at)}
                        </span>
                        {d.summary && <span className={styles.cardSummary}>{d.summary}</span>}
                      </SelectableRow>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>

        {loadState === "ready" && documents.length > 0 && (
          <div className={styles.railWrap}>
            <ContextPanel
              label={isSheet && detail ? detail.file_name : "Selected material"}
              open={Boolean(detail)}
              onOpenChange={(open) => { if (!open) closeDetail(); }}
              hideTrigger
              breakpoint={LIBRARY_SHEET_BREAKPOINT}
              sheetClassName={styles.sheet}
              testid="library-detail"
            >
              <DetailPanel
                doc={detail}
                courseLabel={detail ? courseLabelOf(detail) : ""}
                showHeading={!isSheet}
                online={online}
                onClose={closeDetail}
                onDeleted={handleDeleted}
              />
            </ContextPanel>
          </div>
        )}
      </div>

      <DocumentUploadModal
        open={uploadOpen}
        userId={userId}
        courses={courses}
        onClose={() => setUploadOpen(false)}
        onComplete={async (items) => {
          const hasSyllabus = items.some((it) => it.status === "processed" && it.category === "syllabus");
          await load();
          if (hasSyllabus) {
            // Brief delay for server-side ingestion races, then reload again.
            setTimeout(() => void load(), 1500);
            toast.info("Syllabus processed — new assignments will appear on the calendar.");
          }
        }}
      />

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

function DocMeta({ doc, courseLabel }: { doc: Doc; courseLabel: string }) {
  const concepts = doc.concept_notes?.length ?? 0;
  return (
    <>
      {courseLabel} · {fileTypeOf(doc.file_name).toUpperCase()} · {categoryLabel(doc.category)}
      {concepts > 0 && ` · ${concepts} key concept${concepts === 1 ? "" : "s"}`}
    </>
  );
}

function ListGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function GridGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <rect x="9" y="2" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <rect x="2" y="9" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <rect x="9" y="9" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export function DetailPanel({
  doc, courseLabel, showHeading, online, onClose, onDeleted,
}: {
  doc: Doc | null;
  courseLabel: string;
  /** False inside the phone sheet, whose own title already names the file. */
  showHeading: boolean;
  online: boolean;
  onClose: () => void;
  onDeleted: (doc: Doc) => void | Promise<void>;
}) {
  const { userId } = useUser();
  const [scan, setScan] = React.useState<ScanStatus>({ state: "idle" });
  const [deleting, setDeleting] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const docId = doc?.id;

  React.useEffect(() => {
    setScan({ state: "idle" });
    setDeleting(false);
    setDeleteError(null);
  }, [docId]);

  const runScan = async () => {
    if (!doc) return;
    setScan({ state: "scanning" });
    try {
      const res = await scanDocumentConcepts(doc.id, userId);
      setScan({ state: "done", text: scanResultText(res, doc.course_id ? courseLabel : "this course") });
    } catch (err) {
      setScan({ state: "error", text: `Scan failed: ${errText(err)}. Nothing was added.` });
    }
  };

  const runDelete = React.useCallback(async () => {
    if (!doc) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteDocument(doc.id, userId);
    } catch (err) {
      setDeleting(false);
      setDeleteError(errText(err));
      return;
    }
    setDeleting(false);
    await onDeleted(doc);
  }, [doc, userId, onDeleted]);

  const del = useConfirm(() => { void runDelete(); });

  if (!doc) {
    return (
      <div className={styles.detailEmpty} data-testid="library-detail-empty">
        <p className="sapling-eyebrow">Selected material</p>
        <p>Choose a material to see its summary and key concepts.</p>
      </div>
    );
  }

  const fileType = fileTypeOf(doc.file_name).toUpperCase();

  return (
    <div className={styles.detail} data-testid="library-detail-panel">
      {showHeading && (
        <div className={styles.detailHead}>
          <div className={styles.detailHeadText}>
            <p className="sapling-eyebrow">Selected material</p>
            <h2 className={styles.detailTitle}>{doc.file_name}</h2>
          </div>
          <button
            type="button"
            data-testid="library-detail-close"
            className={styles.iconButton}
            onClick={onClose}
            aria-label="Close selected material"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      )}
      <p className={styles.detailMeta}>
        {courseLabel} · {fileType} · <span className={styles.chip}>{categoryLabel(doc.category)}</span>
      </p>
      <p className={styles.detailDates}>
        Uploaded {formatLongDate(doc.created_at)}
        {doc.processed_at ? ` · processed ${formatLongDate(doc.processed_at)}` : " · processing not recorded"}
      </p>

      <section className={styles.detailSection} aria-labelledby={`library-summary-${doc.id}`}>
        <SectionHeading level={3} id={`library-summary-${doc.id}`}>Summary</SectionHeading>
        {doc.summary ? (
          <>
            <p className={styles.detailNote}>Written by Sapling from this file. It is not the original material.</p>
            <p className={styles.detailText}>{doc.summary}</p>
          </>
        ) : (
          <p className={styles.detailNote}>No summary was saved for this file.</p>
        )}
      </section>

      {doc.concept_notes && doc.concept_notes.length > 0 && (
        <ConceptList notes={doc.concept_notes} />
      )}

      <section className={styles.detailSection} aria-labelledby={`library-scan-${doc.id}`}>
        <SectionHeading level={3} id={`library-scan-${doc.id}`}>Knowledge graph</SectionHeading>
        <p className={styles.detailNote}>
          {`Scanning adds this file's concepts to ${doc.course_id ? `${courseLabel}'s` : "the course's"} knowledge graph to explore. It doesn't mark anything as learned.`}
        </p>
        {scan.state !== "idle" && (
          <StatusMessage
            tone={scan.state === "scanning" ? "pending" : scan.state === "error" ? "error" : "success"}
            onRetry={scan.state === "error" ? runScan : undefined}
            testid="library-detail-scan-status"
          >
            {scan.state === "scanning" ? "Scanning this file for concepts…" : scan.text}
          </StatusMessage>
        )}
        <SaplingAction
          data-testid="library-detail-scan"
          onClick={runScan}
          disabled={scan.state === "scanning" || !online}
          className={styles.fullWidth}
        >
          {scan.state === "scanning" ? "Scanning…" : scan.state === "done" ? "Scan again" : "Scan to knowledge graph"}
        </SaplingAction>
        {doc.course_id && (
          <p className={styles.detailNote}>
            <Link href={`/learn?course=${encodeURIComponent(doc.course_id)}`} className={styles.link} data-testid="library-detail-ask-clov">
              Ask Clov about {courseLabel}
            </Link>
            {" "}opens Clov for this course. Clov draws on your course materials, but won&apos;t open this file by itself.
          </p>
        )}
      </section>

      <section className={styles.detailSection} aria-label="Delete material">
        {deleteError && (
          <StatusMessage
            tone="error"
            title="Couldn't delete this material"
            onRetry={() => void runDelete()}
            retrying={deleting}
            retryLabel="Try delete again"
            testid="library-detail-delete-error"
          >
            {`It is still in your library. ${deleteError}`}
          </StatusMessage>
        )}
        <SaplingAction
          tone="secondary"
          data-testid="library-detail-delete"
          onClick={del.trigger}
          disabled={deleting || !online}
          className={`${styles.fullWidth} ${del.armed ? styles.deleteArmed : ""}`}
        >
          {deleting ? "Deleting…" : del.armed ? "Click again to delete" : "Delete material"}
        </SaplingAction>
      </section>
    </div>
  );
}

function ConceptList({ notes }: { notes: ConceptNote[] }) {
  const [open, setOpen] = React.useState<Record<number, boolean>>({});
  const allOpen = notes.every((_, i) => open[i]);
  const toggleAll = () => {
    if (allOpen) setOpen({});
    else setOpen(Object.fromEntries(notes.map((_, i) => [i, true])));
  };
  const headingId = React.useId();

  return (
    <section className={styles.detailSection} aria-labelledby={headingId}>
      <div className={styles.conceptHead}>
        <SectionHeading level={3} id={headingId}>Key concepts ({notes.length})</SectionHeading>
        <button
          type="button"
          data-testid="library-concepts-toggle-all"
          onClick={toggleAll}
          className={styles.textButton}
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <ul className={styles.concepts}>
        {notes.map((n, i) => {
          const isOpen = !!open[i];
          const panelId = `${headingId}-c${i}`;
          return (
            <li key={`${n.name}-${i}`} className={styles.concept}>
              <button
                type="button"
                data-testid={`library-concept-toggle-${i}`}
                onClick={() => setOpen((prev) => ({ ...prev, [i]: !prev[i] }))}
                aria-expanded={isOpen}
                aria-controls={isOpen ? panelId : undefined}
                className={styles.conceptToggle}
              >
                <span className={styles.conceptChev} data-open={isOpen} aria-hidden="true">
                  <Icon name="chev" size={12} />
                </span>
                <span className={styles.conceptName}>{n.name}</span>
              </button>
              {isOpen && (
                <div id={panelId} className={styles.conceptBody}>
                  <MarkdownChat>{n.description}</MarkdownChat>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
