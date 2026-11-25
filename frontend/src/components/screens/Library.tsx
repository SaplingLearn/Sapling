"use client";
import React from "react";
import dynamic from "next/dynamic";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, type MotionProps } from "framer-motion";
// Importing lib/motion also sets framer's test-mode skip (#383).
import { useMotionPresets, type MotionPreset } from "@/lib/motion";
import { AnimatedNumber } from "./AnimatedNumber";
import styles from "./Library.module.css";
import { TopBar } from "../TopBar";
import { FullHeightScreen } from "../FullHeightScreen";
import { Icon } from "../Icon";
import { FilterPills, Toggle } from "@/components/ui";
import { DocumentUploadModal } from "../DocumentUploadModal";
import { LibraryGridSkeleton, LibraryListSkeleton } from "../Skeleton";

// Lazy-load to keep mermaid/katex/highlight.js out of the OpenNext
// server bundle. See ChatPanel.tsx for the rationale.
const MarkdownChat = dynamic(
  () => import("../chat/MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useIsMobile } from "@/lib/useIsMobile";
import { useScrollLock } from "@/lib/useScrollLock";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { useUser } from "@/context/UserContext";
import { useFlagMap } from "@/context/FlagsContext";
import {
  getDocuments,
  deleteDocument,
  getCourses,
  scanDocumentConcepts,
  scanCourseConcepts,
  type EnrolledCourse,
} from "@/lib/api";
import type { Document as Doc, ConceptNote } from "@/lib/types";
import { LibraryGuides } from "../studyGuide/home/LibraryGuides";
import { libraryGuides } from "../studyGuide/home/guidesModel";
import { useLibraryGuides } from "../studyGuide/home/useLibraryGuides";
import { LibraryNextCtas } from "../library/LibraryNextCtas";
import { conceptIdsFromNotes, libraryNext } from "@/lib/libraryNext";
import { LEARNING_LOOP_FLAG } from "@/lib/learningLoopFlag";
import { useIsNavHidden } from "@/lib/useNavHidden";
import { humanizeError } from "@/lib/errorMessage";

const catColor: Record<Doc["category"], string> = {
  lecture_notes: "var(--c-sage)",
  syllabus:      "var(--c-ink)",
  reading:       "var(--c-plum)",
  slides:        "var(--c-amber)",
  study_guide:   "var(--c-teal)",
  assignment:    "var(--c-rust)",
  other:         "var(--text-muted)",
};

/** A syllabus's assignments land after the upload returns; reload once more after this. */
const SYLLABUS_RELOAD_DELAY_MS = 1500;

// lib/motion types a preset's `initial` as TargetAndTransition, which
// motion.div's `initial` prop does not accept as written; the values are the
// same shape, so view one as the other.
const asProps = (p: MotionPreset): MotionProps => p as MotionProps;

/** `--cat` for a document's category colour (the tile's fill). */
const catVar = (d: Doc) => ({ "--cat": catColor[d.category] }) as React.CSSProperties;

type Cat = Doc["category"] | "all";
type View = "grid" | "list";

export function Library() {
  const toast = useToast();
  const isMobile = useIsMobile();
  const { userId, userReady } = useUser();
  const [documents, setDocuments] = React.useState<Doc[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  // Every guide the student has; the ones saved to the Library show here.
  const saved = useLibraryGuides(userId);
  const [cat, setCat] = React.useState<Cat>("all");
  const [courseFilter, setCourseFilter] = React.useState<string>("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [detail, setDetail] = React.useState<Doc | null>(null);
  const [query, setQuery] = React.useState("");
  const [view, setView] = React.useState<View>("grid");
  const [loading, setLoading] = React.useState(true);
  // A failed load is NOT an empty library (#769): with nothing loaded yet it
  // renders its own error state + retry instead of "Your library is quiet".
  const [loadError, setLoadError] = React.useState(false);
  const loadReq = useLatestRequest();
  const m = useMotionPresets();

  useScrollLock(Boolean(detail));
  const [modalMounted, setModalMounted] = React.useState(false);
  React.useEffect(() => setModalMounted(true), []);

  const [courseScanning, setCourseScanning] = React.useState(false);
  const courseScanCourseId =
    courseFilter !== "all" && courseFilter !== "uncategorized" ? courseFilter : null;
  const courseScanLabel = React.useMemo(() => {
    if (!courseScanCourseId) return "";
    const c = courses.find(x => x.course_id === courseScanCourseId);
    return c ? (c.course_code || c.course_name) : "Course";
  }, [courses, courseScanCourseId]);

  const runCourseScan = React.useCallback(async () => {
    if (!userId || !courseScanCourseId) return;
    setCourseScanning(true);
    try {
      const res = await scanCourseConcepts(courseScanCourseId, userId);
      if (res.added > 0) {
        toast.success(`${courseScanLabel}: added ${res.added} new concept${res.added === 1 ? "" : "s"}.`);
      } else if (res.existing > 0) {
        toast.info(`${courseScanLabel}: graph already covers it (${res.existing} concept${res.existing === 1 ? "" : "s"}).`);
      } else {
        toast.info(`${courseScanLabel}: nothing to add yet.`);
      }
    } catch (err: any) {
      toast.error(`Scan failed: ${String(err?.message || err)}`);
    } finally {
      setCourseScanning(false);
    }
  }, [userId, courseScanCourseId, courseScanLabel, toast]);

  const cats: Cat[] = ["all", "lecture_notes", "syllabus", "reading", "slides", "study_guide", "assignment"];

  const load = React.useCallback(async () => {
    if (!userId) return;
    // Reloads overlap (upload complete + the syllabus re-poll, delete):
    // the latest one owns the list (#769).
    const run = loadReq.begin();
    try {
      const [docs, crs] = await Promise.all([getDocuments(userId), getCourses(userId)]);
      if (!run.isCurrent()) return;
      setDocuments(docs.documents || []);
      setCourses(crs.courses || []);
      setLoadError(false);
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("library load failed", err);
      setLoadError(true);
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
  }, [userId, loadReq]);

  const retryLoad = () => {
    setLoading(true);
    load();
  };

  React.useEffect(() => {
    if (userReady && userId) load();
  }, [userReady, userId, load]);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return documents.filter(d => {
      if (cat !== "all" && d.category !== cat) return false;
      if (courseFilter === "uncategorized" && d.course_id) return false;
      if (courseFilter !== "all" && courseFilter !== "uncategorized" && d.course_id !== courseFilter) return false;
      if (q && !d.file_name.toLowerCase().includes(q) && !(d.summary || "").toLowerCase().includes(q)) return false;
      return true;
    });
  }, [documents, cat, courseFilter, query]);

  // Saved study guides are not documents: they follow the course filter and
  // the search, and show under "all" and "study guide" only.
  const shownGuides = React.useMemo(
    () => libraryGuides(saved.guides, { category: cat, courseFilter, query }),
    [saved.guides, cat, courseFilter, query],
  );

  // #449 (upstream, out of scope here): GET /api/graph/{userId}/courses
  // returns one row per ENROLLMENT, so a course with two offerings (e.g.
  // CS101 in both fall and spring) surfaces as two rows sharing the same
  // course_id — the API can't collapse that itself since enrollment_id-
  // keyed consumers (the gradebook) depend on the per-enrollment rows.
  // This is the Library render-side dedupe: one filter pill / label per
  // distinct abstract course, keeping the first enrollment's row (color,
  // course_code, course_name) as the stable representative.
  const dedupedCourses = React.useMemo(() => {
    const byId = new Map<string, EnrolledCourse>();
    for (const c of courses) {
      if (!byId.has(c.course_id)) byId.set(c.course_id, c);
    }
    return [...byId.values()];
  }, [courses]);

  const courseLookup = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of dedupedCourses) map[c.course_id] = c.course_code || c.course_name;
    return map;
  }, [dedupedCourses]);

  const groupedByCourse = React.useMemo(() => {
    const counts: Record<string, number> = { all: documents.length, uncategorized: 0 };
    for (const d of documents) {
      if (!d.course_id) { counts.uncategorized += 1; continue; }
      counts[d.course_id] = (counts[d.course_id] || 0) + 1;
    }
    return counts;
  }, [documents]);

  // The document list replays its stagger when the filter or the view
  // changes; a search keystroke only adds or drops cards.
  const listKey = `${view}:${cat}:${courseFilter}`;

  return (
    <FullHeightScreen direction="row">
      <div className={styles.screen}>
        <TopBar
          title="Library"
          subtitle={`${documents.length} document${documents.length === 1 ? "" : "s"} · auto-extracted summaries and takeaways`}
          actions={
            <>
              <div className={styles.searchWrap}>
                <input
                  data-testid="library-search"
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="Search documents…"
                  className={styles.search}
                />
              </div>
              {courseScanCourseId && (
                <button
                  data-testid="library-course-scan"
                  className="btn btn--sm"
                  onClick={runCourseScan}
                  disabled={courseScanning}
                  title={`Extend the concept graph for ${courseScanLabel}`}
                >
                  <Icon name="sparkle" size={13} />
                  {courseScanning ? "Scanning…" : `Scan ${courseScanLabel}`}
                </button>
              )}
              <button
                data-testid="library-upload"
                className="btn btn--sm btn--primary"
                onClick={() => setUploadOpen(true)}
                disabled={courses.length === 0}
                title={courses.length === 0 ? "Enroll in a course first" : "Upload documents"}
              >
                <Icon name="upload" size={13} /> Upload
              </button>
            </>
          }
        />

        <div className={styles.filters}>
          <FilterPills
            options={cats.map((c) => ({ value: c, label: c.replace("_", " ") }))}
            value={cat}
            onChange={setCat}
          />
          <div className={styles.spacer} />
          <Toggle
            options={[
              { value: "grid", label: "Grid" },
              { value: "list", label: "List" },
            ]}
            value={view}
            onChange={setView}
            size="sm"
          />
        </div>

        <div className={styles.main}>
          <div className={styles.content}>
            {loading ? (
              view === "grid" ? <LibraryGridSkeleton /> : <LibraryListSkeleton />
            ) : (
              <>
            {loadError && documents.length === 0 && (
              <div data-testid="library-load-error" role="alert" className={styles.empty}>
                <div className={`h-serif ${styles.emptyTitle}`}>Couldn&apos;t load your library</div>
                <div className={`body-serif ${styles.emptyBody}`}>
                  Your documents are safe. Check your connection and try again.
                </div>
                <button data-testid="library-load-retry" className={`btn btn--sm btn--primary ${styles.emptyAction}`} onClick={retryLoad}>
                  Try again
                </button>
              </div>
            )}
            {loadError && documents.length > 0 && (
              <div data-testid="library-load-error" role="alert" className={styles.staleNotice}>
                Couldn&apos;t refresh your library — showing what was last loaded.
                <button data-testid="library-load-retry" className="btn btn--ghost btn--sm" onClick={retryLoad}>Retry</button>
              </div>
            )}
            <LibraryGuides guides={shownGuides} courses={courses} failed={saved.failed} onRetry={saved.reload} />
            {/* Not quiet until the guides are known: they may be on their way, or unreadable. */}
            {filtered.length + shownGuides.length === 0 && !(loadError && documents.length === 0) && saved.known && (
              <motion.div className={styles.empty} {...asProps(m.fade)}>
                <div className={`h-serif ${styles.emptyTitle}`}>Your library is quiet</div>
                <div className={`body-serif ${styles.emptyBody}`}>
                  Upload a syllabus, lecture notes, or reading. Sapling reads them and starts
                  building your knowledge graph.
                </div>
              </motion.div>
            )}
            {view === "grid" ? (
              <motion.div
                key={listKey}
                className={styles.grid}
                variants={m.list.container}
                initial="hidden"
                animate="shown"
              >
                {filtered.map(d => {
                  const isSelected = detail?.id === d.id;
                  const courseLabel = courseLookup[d.course_id ?? ""];
                  return (
                    <motion.button
                      key={d.id}
                      data-testid={`library-doc-${d.id}`}
                      onClick={() => setDetail(d)}
                      className={`card ${styles.docCard}${isSelected ? ` ${styles.selected}` : ""}`}
                      variants={m.list.item}
                    >
                      <div className={styles.docCardHead}>
                        <div className={styles.tile} style={catVar(d)}>
                          <Icon name="doc" size={18} />
                        </div>
                        <span className={`chip ${styles.capitalize}`}>
                          {d.category.replace("_", " ")}
                        </span>
                      </div>
                      <div>
                        <div className={`h-serif ${styles.docTitle}`}>{d.file_name}</div>
                        <div className={styles.docMeta}>
                          {courseLabel ? `${courseLabel} · ` : ""}{new Date(d.created_at).toLocaleDateString()}
                        </div>
                      </div>
                      {d.summary && <div className={styles.docSummary}>{d.summary}</div>}
                    </motion.button>
                  );
                })}
              </motion.div>
            ) : (
              <motion.div
                key={listKey}
                className={`card ${styles.listCard}`}
                variants={m.list.container}
                initial="hidden"
                animate="shown"
              >
                {filtered.map(d => {
                  const isSelected = detail?.id === d.id;
                  return (
                    <motion.button
                      key={d.id}
                      data-testid={`library-doc-${d.id}`}
                      onClick={() => setDetail(d)}
                      className={`${styles.listRow}${isSelected ? ` ${styles.selected}` : ""}`}
                      variants={m.list.item}
                    >
                      <div className={styles.rowTile} style={catVar(d)}>
                        <Icon name="doc" size={14} />
                      </div>
                      <div className={styles.listText}>
                        <div className={`${styles.listTitle} ${styles.truncate}`}>{d.file_name}</div>
                        <div className={`${styles.listSub} ${styles.truncate}`}>{d.summary || "—"}</div>
                      </div>
                      <span className={`chip ${styles.capitalize} ${styles.noShrink}`}>
                        {d.category.replace("_", " ")}
                      </span>
                      <span className={styles.listDate}>
                        {new Date(d.created_at).toLocaleDateString()}
                      </span>
                    </motion.button>
                  );
                })}
              </motion.div>
            )}
              </>
            )}
          </div>

        </div>
      </div>

      {!isMobile && (
        <aside className={styles.rail}>
          <div className={`label-micro ${styles.railLabel}`}>Courses</div>
          <CourseRow
            testid="library-course-filter-all"
            label="All"
            count={groupedByCourse.all || 0}
            active={courseFilter === "all"}
            onClick={() => setCourseFilter("all")}
          />
          <CourseRow
            testid="library-course-filter-uncategorized"
            label="Uncategorized"
            count={groupedByCourse.uncategorized || 0}
            active={courseFilter === "uncategorized"}
            onClick={() => setCourseFilter("uncategorized")}
          />
          {dedupedCourses.map(c => (
            <CourseRow
              key={c.course_id}
              testid={`library-course-filter-${c.course_id}`}
              label={c.course_code || c.course_name}
              subLabel={c.course_code ? c.course_name : undefined}
              color={c.color || undefined}
              count={groupedByCourse[c.course_id] || 0}
              active={courseFilter === c.course_id}
              onClick={() => setCourseFilter(c.course_id)}
            />
          ))}
        </aside>
      )}

      {modalMounted && createPortal(
        <AnimatePresence>
          {detail && (
            <motion.div
              key="library-detail"
              onClick={() => setDetail(null)}
              className={styles.scrim}
              {...asProps(m.fade)}
            >
              <motion.div
                onClick={e => e.stopPropagation()}
                className={`card ${styles.modal}`}
                {...asProps(m.fadeUp)}
              >
                <div className={styles.modalScroll}>
                  <DetailPanel
                    doc={detail}
                    embedded
                    onClose={() => setDetail(null)}
                    onDeleted={async () => {
                      setDetail(null);
                      await load();
                      toast.success("Document deleted");
                    }}
                  />
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}

      <DocumentUploadModal
        open={uploadOpen}
        userId={userId}
        courses={courses}
        onClose={() => setUploadOpen(false)}
        onComplete={async (items) => {
          const hasSyllabus = items.some(it => it.category === "syllabus");
          await load();
          if (hasSyllabus) {
            // Brief delay for server-side ingestion races, then reload again.
            setTimeout(load, SYLLABUS_RELOAD_DELAY_MS);
            toast.info("Syllabus processed — new assignments will appear on the calendar.");
          }
        }}
      />
    </FullHeightScreen>
  );
}

function CourseRow({
  testid, label, subLabel, color, count, active, onClick,
}: {
  testid: string;
  label: string; subLabel?: string; color?: string;
  count: number; active: boolean; onClick: () => void;
}) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={`${styles.courseRow}${active ? ` ${styles.active}` : ""}`}
    >
      <span
        className={styles.courseDot}
        style={color ? ({ "--course": color } as React.CSSProperties) : undefined}
      />
      <div className={styles.courseText}>
        <div className={`${styles.courseLabel} ${styles.truncate}`}>{label}</div>
        {subLabel && <div className={styles.courseSub}>{subLabel}</div>}
      </div>
      {/* Tweens when an upload or a delete changes the count. */}
      <AnimatedNumber value={count} className={`mono ${styles.courseCount}`} />
    </button>
  );
}

function DetailPanel({
  doc, onClose, onDeleted, embedded = false,
}: {
  doc: Doc;
  onClose: () => void;
  onDeleted: () => void | Promise<void>;
  embedded?: boolean;
}) {
  const { userId } = useUser();
  const toast = useToast();
  const { flags } = useFlagMap();
  const isNavHidden = useIsNavHidden();
  const [scanState, setScanState] = React.useState<"idle" | "scanning" | "done">("idle");
  const [scanResult, setScanResult] = React.useState<{ added: number; existing: number } | null>(null);
  // The panel is reused across documents, so a scan started on doc A must not
  // mark doc B "done" (#769): switching documents cancels the in-flight
  // scan's claim on this panel's state.
  const scanReq = useLatestRequest();

  React.useEffect(() => {
    scanReq.cancel();
    setScanState("idle");
    setScanResult(null);
  }, [doc.id, scanReq]);

  const conceptCount = doc.concept_notes?.length ?? 0;
  const next = libraryNext({
    courseId: doc.course_id,
    conceptIds: conceptIdsFromNotes(doc.concept_notes),
    conceptCount,
    checkItemsStatus: doc.check_items_status ?? null,
    loopOn: flags[LEARNING_LOOP_FLAG] === "on",
    treeHidden: isNavHidden("/tree"),
    quizHidden: isNavHidden("/quiz"),
  });

  const runScan = async () => {
    const run = scanReq.begin();
    setScanState("scanning");
    try {
      const res = await scanDocumentConcepts(doc.id, userId);
      // The graph update is real either way — only the panel state is
      // per-document. The toast still reports it.
      if (run.isCurrent()) {
        setScanResult({ added: res.added, existing: res.existing });
        setScanState("done");
      }
      if (res.added > 0) {
        toast.success(`Added ${res.added} new concept${res.added === 1 ? "" : "s"} to your graph.`);
      } else if (res.existing > 0) {
        toast.info(`Course graph already covers this (${res.existing} concept${res.existing === 1 ? "" : "s"}).`);
      } else {
        toast.info("Nothing to add from this document yet.");
      }
    } catch (err: any) {
      if (run.isCurrent()) setScanState("idle");
      toast.error(`Scan failed: ${String(err?.message || err)}`);
    }
  };

  const del = useConfirm(async () => {
    try {
      await deleteDocument(doc.id, userId);
      await onDeleted();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't delete that document. Try again."));
    }
  });

  const m = useMotionPresets();
  const scanNote = scanState === "done" && scanResult
    ? scanResult.added > 0
      ? `Added ${scanResult.added} new concept${scanResult.added === 1 ? "" : "s"} on top of the existing ${scanResult.existing}.`
      : `Course graph already covers this (${scanResult.existing} concept${scanResult.existing === 1 ? "" : "s"}).`
    : "Extend this course's graph using this document's summary and takeaways.";

  return (
    <aside className={embedded ? styles.detail : styles.detailSide}>
      <div className={styles.detailHead}>
        <span className="chip">{doc.category.replace("_", " ")}</span>
        <button data-testid="library-detail-close" className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">
          <Icon name="x" size={12} />
        </button>
      </div>
      <h2 className={`h-serif ${styles.detailTitle}`}>{doc.file_name}</h2>
      <div className={styles.detailMeta}>
        Uploaded {new Date(doc.created_at).toLocaleDateString()}
      </div>

      {doc.summary && (
        <div className={styles.section}>
          <div className={`label-micro ${styles.sectionLabel}`}>Summary</div>
          <div className={styles.summary}>{doc.summary}</div>
        </div>
      )}

      {doc.concept_notes && doc.concept_notes.length > 0 && (
        <ConceptList notes={doc.concept_notes} />
      )}

      <LibraryNextCtas next={next} />

      <div className={styles.scanBox}>
        <div className={styles.scanRow}>
          <div className={styles.scanText}>
            <div className="label-micro">Concept scan</div>
            {/* The note swaps to the scan's result: fade the new text in (enter
                only, so the new note never waits on the old one's exit). */}
            <AnimatePresence initial={false}>
              <motion.div key={scanNote} className={styles.scanNote} {...asProps(m.fade)} exit={undefined}>
                {scanNote}
              </motion.div>
            </AnimatePresence>
          </div>
          <button
            data-testid="library-detail-scan"
            onClick={runScan}
            disabled={scanState === "scanning"}
            className={`btn btn--sm ${styles.noShrink}`}
          >
            <Icon name="sparkle" size={12} />
            {scanState === "scanning"
              ? "Scanning…"
              : scanState === "done"
                ? "Re-scan"
                : "Scan"}
          </button>
        </div>
      </div>

      <button
        data-testid="library-detail-delete"
        onClick={del.trigger}
        className={`btn ${styles.delete}${del.armed ? ` btn--danger ${styles.armed}` : ""}`}
      >
        <Icon name="x" size={13} /> {del.armed ? "Click again to confirm" : "Delete document"}
      </button>
    </aside>
  );
}

function ConceptList({ notes }: { notes: ConceptNote[] }) {
  const [open, setOpen] = React.useState<Record<number, boolean>>({});
  const m = useMotionPresets();
  const allOpen = notes.every((_, i) => open[i]);
  const toggleAll = () => {
    if (allOpen) setOpen({});
    else setOpen(Object.fromEntries(notes.map((_, i) => [i, true])));
  };

  return (
    <div className={styles.section}>
      <div className={styles.conceptsHead}>
        <div className="label-micro">Key concepts ({notes.length})</div>
        <button
          data-testid="library-concepts-toggle-all"
          onClick={toggleAll}
          className={`btn btn--ghost btn--sm ${styles.toggleAll}`}
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <div className={styles.concepts}>
        {notes.map((n, i) => {
          const isOpen = !!open[i];
          return (
            <div key={`${n.name}-${i}`} className={styles.concept}>
              <button
                data-testid={`library-concept-toggle-${i}`}
                onClick={() => setOpen(prev => ({ ...prev, [i]: !prev[i] }))}
                aria-expanded={isOpen}
                className={styles.conceptToggle}
              >
                <span className={`${styles.chev}${isOpen ? ` ${styles.open}` : ""}`}>
                  <Icon name="chev" size={12} />
                </span>
                <span className={`h-serif ${styles.conceptName}`}>{n.name}</span>
              </button>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div key="body" {...asProps(m.collapse)}>
                    <div className={styles.conceptBody}>
                      <MarkdownChat>{n.description}</MarkdownChat>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
