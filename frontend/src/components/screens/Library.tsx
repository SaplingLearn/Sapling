"use client";
import React from "react";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Pill } from "../Pill";
import { DocumentUploadModal } from "../DocumentUploadModal";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useIsMobile } from "@/lib/useIsMobile";
import { useBodyScrollLock } from "@/lib/useBodyScrollLock";
import { useUser } from "@/context/UserContext";
import {
  getDocuments,
  deleteDocument,
  getCourses,
  type EnrolledCourse,
} from "@/lib/api";
import type { Document as Doc } from "@/lib/types";

const catColor: Record<Doc["category"], string> = {
  lecture_notes: "var(--c-sage)",
  syllabus: "var(--c-ink)",
  reading: "var(--c-plum)",
  slides: "var(--c-amber)",
  study_guide: "var(--c-teal)",
  assignment: "var(--c-rust)",
  other: "var(--text-muted)",
};

type Cat = Doc["category"] | "all";

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

  useBodyScrollLock(Boolean(detail) && isMobile);

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
      {!isMobile && (
        <aside style={{
          width: 240, borderRight: "1px solid var(--border)",
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
          padding: "14px 32px",
          display: "flex", gap: 6, borderBottom: "1px solid var(--border)", flexWrap: "wrap",
        }}>
          {cats.map((c) => (
            <Pill key={c} active={cat === c} onClick={() => setCat(c)}>
              {c.replace("_", " ")}
            </Pill>
          ))}
        </div>

        <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
          <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px" }}>
            {filtered.length === 0 && (
              <div style={{ textAlign: "center", padding: 60, color: "var(--text-muted)" }}>
                <div className="h-serif" style={{ fontSize: 20 }}>Nothing here yet</div>
                <div style={{ fontSize: 13, marginTop: 6 }}>Upload a document to get started.</div>
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
              {filtered.map((d) => (
                <button
                  key={d.id}
                  className="card"
                  onClick={() => setDetail(d)}
                  style={{
                    padding: "var(--pad-lg)", display: "flex", flexDirection: "column", gap: 10,
                    textAlign: "left", cursor: "pointer",
                    outline: detail?.id === d.id ? "2px solid var(--accent)" : "none",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{
                      width: 40, height: 48, borderRadius: "var(--r-sm)",
                      background: catColor[d.category], color: "#fff",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <Icon name="doc" size={18} />
                    </div>
                    <span className="chip">{d.category.replace("_", " ")}</span>
                  </div>
                  <div>
                    <div className="h-serif" style={{ fontSize: 16, lineHeight: 1.3 }}>{d.file_name}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                      {new Date(d.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  {d.summary && <div style={{ fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5 }}>{d.summary}</div>}
                  {d.key_takeaways && d.key_takeaways.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                      {d.key_takeaways.slice(0, 3).map((t) => (
                        <span key={t} className="chip chip--accent">{t}</span>
                      ))}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>

          {detail && !isMobile && (
            <DetailPanel
              doc={detail}
              onClose={() => setDetail(null)}
              onDeleted={async () => {
                setDetail(null);
                await load();
                toast.success("Document deleted");
              }}
            />
          )}
        </div>
      </div>

      {detail && isMobile && (
        <div
          onClick={() => setDetail(null)}
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
              padding: 0, maxHeight: "82vh", overflowY: "auto",
            }}
          >
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
  const [revealed, setRevealed] = React.useState<Set<number>>(new Set());
  const del = useConfirm(async () => {
    try {
      await deleteDocument(doc.id, userId);
      await onDeleted();
    } catch (err) {
      toast.error(`Delete failed: ${String(err)}`);
    }
  });

  const reveal = (idx: number) => {
    setRevealed(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx); else next.add(idx);
      return next;
    });
  };

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

      {doc.key_takeaways && doc.key_takeaways.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="label-micro" style={{ marginBottom: 6 }}>Key takeaways</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {doc.key_takeaways.map((t) => (
              <li key={t} style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 4 }}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      {doc.flashcards && doc.flashcards.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="label-micro" style={{ marginBottom: 6 }}>Q / A</div>
          {doc.flashcards.map((f, i) => (
            <div
              key={i}
              onClick={() => reveal(i)}
              role="button"
              style={{
                padding: "10px 12px", borderRadius: "var(--r-sm)",
                border: "1px solid var(--border)", background: "var(--bg-panel)",
                marginBottom: 6, cursor: "pointer",
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{f.question}</div>
              <div style={{ fontSize: 12, color: "var(--text-dim)", opacity: revealed.has(i) ? 1 : 0, filter: revealed.has(i) ? "none" : "blur(4px)", transition: "all var(--dur) var(--ease)" }}>
                {f.answer}
              </div>
            </div>
          ))}
        </div>
      )}

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
