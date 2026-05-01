"use client";
import React from "react";
import { createPortal } from "react-dom";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Pill } from "../Pill";
import { DocumentUploadModal } from "../DocumentUploadModal";
import { MarkdownChat } from "../MarkdownChat";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useIsMobile } from "@/lib/useIsMobile";
import { useBodyScrollLock } from "@/lib/useBodyScrollLock";
import { useUser } from "@/context/UserContext";
import {
  getDocuments,
  deleteDocument,
  getCourses,
  scanDocumentConcepts,
  scanCourseConcepts,
  type EnrolledCourse,
} from "@/lib/api";
import type { Document as Doc } from "@/lib/types";

const catColor: Record<Doc["category"], string> = {
  lecture_notes: "var(--c-sage)",
  syllabus:      "var(--c-ink)",
  reading:       "var(--c-plum)",
  slides:        "var(--c-amber)",
  study_guide:   "var(--c-teal)",
  assignment:    "var(--c-rust)",
  other:         "var(--text-muted)",
};

type Cat = Doc["category"] | "all";
type View = "grid" | "list";

export function Library() {
  const toast = useToast();
  const isMobile = useIsMobile();
  const { userId, userReady } = useUser();
  const [documents, setDocuments] = React.useState<Doc[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [cat, setCat] = React.useState<Cat>("all");
  const [courseFilter, setCourseFilter] = React.useState<string>("all");
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [detail, setDetail] = React.useState<Doc | null>(null);
  const [query, setQuery] = React.useState("");
  const [view, setView] = React.useState<View>("grid");

  useBodyScrollLock(Boolean(detail));
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
    try {
      const [docs, crs] = await Promise.all([
        getDocuments(userId),
        getCourses(userId),
      ]);
      setDocuments(docs.documents || []);
      setCourses(crs.courses || []);
    } catch (err) {
      console.error("library load failed", err);
    }
  }, [userId]);

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

  const courseLookup = React.useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of courses) map[c.course_id] = c.course_code || c.course_name;
    return map;
  }, [courses]);

  const groupedByCourse = React.useMemo(() => {
    const counts: Record<string, number> = { all: documents.length, uncategorized: 0 };
    for (const d of documents) {
      if (!d.course_id) { counts.uncategorized += 1; continue; }
      counts[d.course_id] = (counts[d.course_id] || 0) + 1;
    }
    return counts;
  }, [documents]);

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar
          breadcrumb="Home / Library"
          title="Library"
          subtitle={`${documents.length} document${documents.length === 1 ? "" : "s"} · auto-extracted summaries and takeaways`}
          actions={
            <>
              <div style={{ position: "relative" }}>
                <input
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="Search documents…"
                  style={{
                    padding: "6px 12px", fontSize: 12,
                    border: "1px solid var(--border)", borderRadius: "var(--r-full)",
                    background: "var(--bg-panel)", width: 220,
                  }}
                />
              </div>
              {courseScanCourseId && (
                <button
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
                className="btn btn--sm btn--primary"
                onClick={() => setUploadOpen(true)}
                disabled={courses.length === 0}
                title={courses.length === 0 ? "Enroll in a course first" : "Upload documents"}
              >
                <Icon name="up" size={13} /> Upload
              </button>
            </>
          }
        />

        <div style={{
          padding: "14px 32px", display: "flex", gap: 6, alignItems: "center",
          borderBottom: "1px solid var(--border)", flexWrap: "wrap",
        }}>
          {cats.map((c) => (
            <Pill key={c} active={cat === c} onClick={() => setCat(c)}>
              {c.replace("_", " ")}
            </Pill>
          ))}
          <div style={{ flex: 1 }} />
          <div style={{
            display: "flex", border: "1px solid var(--border)",
            borderRadius: "var(--r-sm)", overflow: "hidden",
          }}>
            {(["grid", "list"] as View[]).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                style={{
                  padding: "4px 10px", fontSize: 11, textTransform: "capitalize",
                  background: view === v ? "var(--accent-soft)" : "transparent",
                  color: view === v ? "var(--accent)" : "var(--text-dim)",
                  border: "none", cursor: "pointer",
                }}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
          <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px" }}>
            {filtered.length === 0 && (
              <div style={{ textAlign: "center", padding: "60px 20px", color: "var(--text-muted)", maxWidth: 440, margin: "0 auto" }}>
                <div className="h-serif" style={{ fontSize: 22, color: "var(--text)" }}>Your library is quiet</div>
                <div className="body-serif" style={{ fontSize: 14, marginTop: 8, lineHeight: 1.6 }}>
                  Upload a syllabus, lecture notes, or reading. Sapling reads them and starts
                  building your knowledge graph.
                </div>
              </div>
            )}
            {view === "grid" ? (
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 16,
              }}>
                {filtered.map(d => {
                  const isSelected = detail?.id === d.id;
                  const courseLabel = courseLookup[d.course_id];
                  return (
                    <button
                      key={d.id}
                      onClick={() => setDetail(d)}
                      className="card"
                      style={{
                        padding: "var(--pad-lg)", display: "flex", flexDirection: "column",
                        gap: 10, textAlign: "left", cursor: "pointer",
                        borderColor: isSelected ? "var(--accent-border)" : undefined,
                        background: isSelected ? "var(--accent-soft)" : undefined,
                        transition: "border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                        <div style={{
                          width: 40, height: 48, borderRadius: "var(--r-sm)",
                          background: catColor[d.category], color: "#fff",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          flexShrink: 0,
                        }}>
                          <Icon name="doc" size={18} />
                        </div>
                        <span className="chip" style={{ textTransform: "capitalize" }}>
                          {d.category.replace("_", " ")}
                        </span>
                      </div>
                      <div>
                        <div className="h-serif" style={{
                          fontSize: 16, lineHeight: 1.3, color: "var(--text)",
                          display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                        }}>
                          {d.file_name}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                          {courseLabel ? `${courseLabel} · ` : ""}{new Date(d.created_at).toLocaleDateString()}
                        </div>
                      </div>
                      {d.summary && (
                        <div style={{
                          fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5,
                          display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden",
                        }}>
                          {d.summary}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="card" style={{ padding: 0 }}>
                {filtered.map((d, i) => {
                  const isSelected = detail?.id === d.id;
                  return (
                    <button
                      key={d.id}
                      onClick={() => setDetail(d)}
                      style={{
                        width: "100%", display: "flex", alignItems: "center", gap: 16,
                        padding: "14px 20px", textAlign: "left", cursor: "pointer",
                        borderBottom: i < filtered.length - 1 ? "1px solid var(--border)" : "none",
                        background: isSelected ? "var(--accent-soft)" : "transparent",
                        border: "none", borderTop: "none", borderLeft: "none", borderRight: "none",
                        transition: "background var(--dur-fast) var(--ease)",
                      }}
                    >
                      <div style={{
                        width: 28, height: 36, borderRadius: "var(--r-xs)",
                        background: catColor[d.category], color: "#fff",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        flexShrink: 0,
                      }}>
                        <Icon name="doc" size={14} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 14, fontWeight: 500, color: "var(--text)",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                          {d.file_name}
                        </div>
                        <div style={{
                          fontSize: 11, color: "var(--text-muted)",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>
                          {d.summary || "—"}
                        </div>
                      </div>
                      <span className="chip" style={{ textTransform: "capitalize", flexShrink: 0 }}>
                        {d.category.replace("_", " ")}
                      </span>
                      <span style={{
                        fontSize: 11, color: "var(--text-muted)",
                        width: 80, textAlign: "right", flexShrink: 0,
                      }}>
                        {new Date(d.created_at).toLocaleDateString()}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

        </div>
      </div>

      {!isMobile && (
        <aside style={{
          width: 240, borderLeft: "1px solid var(--border)", flexShrink: 0,
          background: "var(--bg-subtle)", padding: 16, overflowY: "auto",
        }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Courses</div>
          <CourseRow
            label="All"
            count={groupedByCourse.all || 0}
            active={courseFilter === "all"}
            onClick={() => setCourseFilter("all")}
          />
          <CourseRow
            label="Uncategorized"
            count={groupedByCourse.uncategorized || 0}
            active={courseFilter === "uncategorized"}
            onClick={() => setCourseFilter("uncategorized")}
          />
          {courses.map(c => (
            <CourseRow
              key={c.course_id}
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

      {detail && modalMounted && createPortal(
        <div
          onClick={() => setDetail(null)}
          style={{
            position: "fixed", inset: 0, background: "rgba(19,38,16,0.45)",
            zIndex: 200, display: "grid", placeItems: "center", padding: 20,
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            className="card slide-up"
            style={{
              width: "min(820px, 100%)", maxHeight: "88vh",
              overflow: "hidden", padding: 0, display: "flex", flexDirection: "column",
            }}
          >
            <div style={{ overflowY: "auto" }}>
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
          </div>
        </div>,
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
            setTimeout(load, 1500);
            toast.info("Syllabus processed — new assignments will appear on the calendar.");
          }
        }}
      />
    </div>
  );
}

function CourseRow({
  label, subLabel, color, count, active, onClick,
}: {
  label: string; subLabel?: string; color?: string;
  count: number; active: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%", display: "flex", alignItems: "center", gap: 8,
        padding: "8px 10px", borderRadius: "var(--r-sm)", marginBottom: 4,
        background: active ? "var(--bg-panel)" : "transparent",
        border: active ? "1px solid var(--border)" : "1px solid transparent",
        textAlign: "left",
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: "50%",
        background: color || "var(--text-muted)",
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: active ? 600 : 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</div>
        {subLabel && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{subLabel}</div>}
      </div>
      <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>{count}</span>
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
  const [scanState, setScanState] = React.useState<"idle" | "scanning" | "done">("idle");
  const [scanResult, setScanResult] = React.useState<{ added: number; existing: number } | null>(null);

  React.useEffect(() => {
    setScanState("idle");
    setScanResult(null);
  }, [doc.id]);

  const runScan = async () => {
    setScanState("scanning");
    try {
      const res = await scanDocumentConcepts(doc.id, userId);
      setScanResult({ added: res.added, existing: res.existing });
      setScanState("done");
      if (res.added > 0) {
        toast.success(`Added ${res.added} new concept${res.added === 1 ? "" : "s"} to your graph.`);
      } else if (res.existing > 0) {
        toast.info(`Course graph already covers this (${res.existing} concept${res.existing === 1 ? "" : "s"}).`);
      } else {
        toast.info("Nothing to add from this document yet.");
      }
    } catch (err: any) {
      setScanState("idle");
      toast.error(`Scan failed: ${String(err?.message || err)}`);
    }
  };

  const del = useConfirm(async () => {
    try {
      await deleteDocument(doc.id, userId);
      await onDeleted();
    } catch (err) {
      toast.error(`Delete failed: ${String(err)}`);
    }
  });

  const container: React.CSSProperties = embedded
    ? { padding: 20 }
    : { width: 360, borderLeft: "1px solid var(--border)", padding: 20, background: "var(--bg-subtle)", overflowY: "auto", flexShrink: 0 };

  return (
    <aside style={container}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="chip">{doc.category.replace("_", " ")}</span>
        <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">
          <Icon name="x" size={12} />
        </button>
      </div>
      <h2 className="h-serif" style={{ fontSize: 20, margin: "10px 0 6px", fontWeight: 500 }}>{doc.file_name}</h2>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 16 }}>
        Uploaded {new Date(doc.created_at).toLocaleDateString()}
      </div>

      {doc.summary && (
        <div style={{ marginBottom: 16 }}>
          <div className="label-micro" style={{ marginBottom: 4 }}>Summary</div>
          <div style={{ fontSize: 13, lineHeight: 1.55, color: "var(--text-dim)" }}>{doc.summary}</div>
        </div>
      )}

      {doc.concept_notes && doc.concept_notes.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="label-micro" style={{ marginBottom: 8 }}>Key concepts</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {doc.concept_notes.map((n) => (
              <div
                key={n.name}
                style={{
                  padding: "12px 14px", borderRadius: "var(--r-sm)",
                  border: "1px solid var(--border)", background: "var(--bg-panel)",
                }}
              >
                <div className="h-serif" style={{ fontSize: 14, fontWeight: 600, marginBottom: 6, color: "var(--text)" }}>
                  {n.name}
                </div>
                <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
                  <MarkdownChat>{n.description}</MarkdownChat>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{
        marginBottom: 10, padding: 12, borderRadius: "var(--r-sm)",
        border: "1px solid var(--border)", background: "var(--bg-panel)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <div className="label-micro">Concept scan</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.4 }}>
              {scanState === "done" && scanResult
                ? scanResult.added > 0
                  ? `Added ${scanResult.added} new concept${scanResult.added === 1 ? "" : "s"} on top of the existing ${scanResult.existing}.`
                  : `Course graph already covers this (${scanResult.existing} concept${scanResult.existing === 1 ? "" : "s"}).`
                : "Extend this course's graph using this document's summary and takeaways."}
            </div>
          </div>
          <button
            onClick={runScan}
            disabled={scanState === "scanning"}
            className="btn btn--sm"
            style={{ flexShrink: 0 }}
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
        onClick={del.trigger}
        className={`btn ${del.armed ? "btn--danger" : ""}`}
        style={{ width: "100%", background: del.armed ? "var(--err-soft)" : undefined, color: del.armed ? "var(--err)" : undefined }}
      >
        <Icon name="x" size={13} /> {del.armed ? "Click again to confirm" : "Delete document"}
      </button>
    </aside>
  );
}
