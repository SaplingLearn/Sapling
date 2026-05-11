"use client";
import React from "react";
import { Icon } from "@/components/Icon";
import {
  createNote as apiCreateNote,
  deleteNote as apiDeleteNote,
  extractNoteConcepts,
  generateQuizFromNote,
  getCourses,
  type EnrolledCourse,
  linkNoteConcept,
  listNoteConcepts,
  listNotes,
  patchNote,
  sendNoteToTutor,
  summarizeNote,
  unlinkNoteConcept,
} from "@/lib/api";
import type { LinkedConcept, Note as ApiNote } from "@/lib/types";
import { useUser } from "@/context/UserContext";
import { useRouter } from "next/navigation";

type Mastery = "mastered" | "learning" | "struggling" | "unexplored";

type Course = {
  id: string;
  name: string;
  code: string;
  color: string;
};

type Concept = {
  id: string;
  name: string;
  course: string;
  mastery: Mastery;
};

type Note = {
  id: string;
  title: string;
  body: string;
  courseId: string;
  updatedAt: Date;
  tags: string[];
  linkedConcepts: Concept[];
  lastSummary: string | null;
};

const MASTERY_COLOR: Record<Mastery, string> = {
  mastered: "#4a7d5c",
  learning: "#c89b5e",
  struggling: "#b25855",
  unexplored: "#9a9a9a",
};

function relTime(d: Date) {
  const diff = Date.now() - d.getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

async function adaptNote(api: ApiNote, userId: string): Promise<Note> {
  const conceptsRes = await listNoteConcepts(api.id, userId).catch(
    () => ({ concepts: [] as LinkedConcept[] }),
  );
  return {
    id: api.id,
    title: api.title,
    body: api.body,
    courseId: api.course_id,
    updatedAt: new Date(api.updated_at),
    tags: api.tags,
    lastSummary: api.last_summary,
    linkedConcepts: conceptsRes.concepts.map((c) => ({
      id: c.id,
      name: c.concept_name,
      course: "",
      mastery: (c.mastery_tier === "subject_root"
        ? "unexplored"
        : c.mastery_tier) as Mastery,
    })),
  };
}

function EmptyNotetaker({
  courses,
  onCreate,
  pickerOpen,
  onPickerClose,
  onPick,
}: {
  courses: Course[];
  onCreate: () => void;
  pickerOpen: boolean;
  onPickerClose: () => void;
  onPick: (courseId: string) => void;
}) {
  return (
    <div
      style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        height: "100vh", flexDirection: "column", gap: 14,
      }}
    >
      <div className="label-micro">No notes yet</div>
      <button
        type="button"
        className="btn btn--primary"
        onClick={onCreate}
      >
        Create your first note
      </button>
      {pickerOpen && (
        <CoursePickerModal
          courses={courses}
          onPick={onPick}
          onClose={onPickerClose}
        />
      )}
    </div>
  );
}

export default function NotetakerPage() {
  const { userId } = useUser();

  const [courses, setCourses] = React.useState<Course[]>([]);
  const [notes, setNotes] = React.useState<Note[]>([]);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [courseFilter, setCourseFilter] = React.useState<string | null>(null);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [conceptPickerOpen, setConceptPickerOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState<null | "summarize" | "extract" | "quiz" | "tutor">(null);
  const router = useRouter();

  React.useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    (async () => {
      try {
        const [coursesRes, notesRes] = await Promise.all([
          getCourses(userId),
          listNotes(userId),
        ]);
        if (cancelled) return;
        setCourses(
          coursesRes.courses.map((c: EnrolledCourse) => ({
            id: c.course_id,
            name: c.course_name,
            code: c.course_code,
            color: c.color ?? "#9a9a9a",
          })),
        );
        const adapted = await Promise.all(
          notesRes.notes.map((n) => adaptNote(n, userId)),
        );
        setNotes(adapted);
        setActiveId(adapted[0]?.id ?? null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const active = notes.find((n) => n.id === activeId) ?? notes[0] ?? null;

  const courseFor = React.useCallback(
    (id: string): Course =>
      courses.find((c) => c.id === id) ?? {
        id, name: "Course", code: "—", color: "#9a9a9a",
      },
    [courses],
  );

  const refreshConcepts = React.useCallback(async () => {
    if (!active || !userId) return;
    const fresh = await listNoteConcepts(active.id, userId);
    setNotes((prev) =>
      prev.map((n) =>
        n.id === active.id
          ? {
              ...n,
              linkedConcepts: fresh.concepts.map((c) => ({
                id: c.id, name: c.concept_name, course: "",
                mastery: (c.mastery_tier === "subject_root" ? "unexplored" : c.mastery_tier) as Mastery,
              })),
            }
          : n,
      ),
    );
  }, [active, userId]);

  const onSummarize = async () => {
    if (!active || !userId) return;
    setBusy("summarize");
    try {
      const { summary } = await summarizeNote(active.id, userId);
      setNotes((prev) =>
        prev.map((n) => (n.id === active.id ? { ...n, lastSummary: summary } : n)),
      );
    } finally {
      setBusy(null);
    }
  };

  const onExtractConcepts = async () => {
    if (!active || !userId) return;
    setBusy("extract");
    try {
      await extractNoteConcepts(active.id, userId);
      await refreshConcepts();
    } finally {
      setBusy(null);
    }
  };

  const onGenerateQuiz = async () => {
    if (!active || !userId) return;
    setBusy("quiz");
    try {
      const { concept_node_id } = await generateQuizFromNote(active.id, userId);
      router.push(`/quiz?concept=${encodeURIComponent(concept_node_id)}`);
    } catch (e) {
      console.error("Quiz generation failed", e);
    } finally {
      setBusy(null);
    }
  };

  const onSendToTutor = async () => {
    if (!active || !userId) return;
    setBusy("tutor");
    try {
      const { topic, course_id } = await sendNoteToTutor(active.id, userId);
      router.push(
        `/learn?topic=${encodeURIComponent(topic)}&course=${encodeURIComponent(course_id)}`,
      );
    } finally {
      setBusy(null);
    }
  };

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return notes.filter((n) => {
      if (courseFilter && n.courseId !== courseFilter) return false;
      if (!q) return true;
      const c = courseFor(n.courseId);
      return (
        n.title.toLowerCase().includes(q) ||
        n.body.toLowerCase().includes(q) ||
        c.code.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        n.tags.some((t) => t.toLowerCase().includes(q))
      );
    });
  }, [notes, query, courseFilter, courseFor]);

  const updateActive = React.useCallback(
    (patch: Partial<Pick<Note, "title" | "body" | "tags">>) => {
      if (!active) return;
      setNotes((prev) =>
        prev.map((n) =>
          n.id === active.id ? { ...n, ...patch, updatedAt: new Date() } : n,
        ),
      );
    },
    [active],
  );

  // Debounced autosave: any change to title/body/tags triggers a PATCH
  // 800ms after the user stops typing. Cancels prior pending saves.
  const saveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedSignature = React.useRef<string>("");

  React.useEffect(() => {
    if (!active || !userId) return;
    const signature = JSON.stringify({
      id: active.id,
      title: active.title,
      body: active.body,
      tags: active.tags,
    });
    if (signature === lastSavedSignature.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      patchNote(active.id, userId, {
        title: active.title,
        body: active.body,
        tags: active.tags,
      })
        .then(() => {
          lastSavedSignature.current = signature;
        })
        .catch(() => {
          // Save failed — leave the signature unchanged so the next edit
          // (or a retry from the effect) reattempts.
        });
    }, 800);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [active?.id, active?.title, active?.body, active?.tags, userId]);

  const createNoteIn = async (courseId: string) => {
    if (!userId) return;
    const fresh = await apiCreateNote(userId, courseId, "Untitled note");
    const adapted = await adaptNote(fresh, userId);
    setNotes((prev) => [adapted, ...prev]);
    setActiveId(adapted.id);
    setPickerOpen(false);
  };

  React.useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  React.useEffect(() => {
    if (!pickerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPickerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [pickerOpen]);

  if (!userId) return null;
  if (loading) {
    return <div style={{ padding: 24, fontSize: 13, color: "var(--text-muted)" }}>Loading…</div>;
  }
  if (!active) {
    return (
      <EmptyNotetaker
        courses={courses}
        onCreate={() => setPickerOpen(true)}
        pickerOpen={pickerOpen}
        onPickerClose={() => setPickerOpen(false)}
        onPick={async (courseId) => {
          const fresh = await apiCreateNote(userId, courseId, "Untitled note");
          const adapted = await adaptNote(fresh, userId);
          setNotes([adapted]);
          setActiveId(adapted.id);
          setPickerOpen(false);
        }}
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          gap: fullscreen ? 24 : 16,
          padding: fullscreen ? "24px 24px 24px 24px" : "32px 32px 24px",
          transition: "gap var(--dur-slow) var(--ease), padding var(--dur-slow) var(--ease)",
        }}
      >
        <div
          style={{
            flex: fullscreen ? "0 0 0px" : "0 0 clamp(260px, 22%, 320px)",
            minWidth: 0,
            opacity: fullscreen ? 0 : 1,
            overflow: "hidden",
            pointerEvents: fullscreen ? "none" : undefined,
            transition:
              "flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease)",
          }}
          aria-hidden={fullscreen}
        >
          <NotesList
            notes={filtered}
            totalCount={notes.length}
            courses={courses}
            activeId={active.id}
            query={query}
            onQueryChange={setQuery}
            courseFilter={courseFilter}
            onCourseFilterChange={setCourseFilter}
            onSelect={(id) => setActiveId(id)}
            onCreate={() => setPickerOpen(true)}
          />
        </div>

        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              width: "100%",
              maxWidth: fullscreen ? "min(1200px, 96%)" : "none",
              display: "flex",
              transition: "max-width var(--dur-slow) var(--ease)",
            }}
          >
            <NoteEditor
              note={active}
              onChange={updateActive}
              fullscreen={fullscreen}
              onToggleFullscreen={() => setFullscreen((f) => !f)}
            />
          </div>
        </div>

        <div
          style={{
            flex: fullscreen ? "0 0 0px" : "0 0 clamp(280px, 22%, 340px)",
            minWidth: 0,
            opacity: fullscreen ? 0 : 1,
            overflow: "hidden",
            pointerEvents: fullscreen ? "none" : undefined,
            transition:
              "flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease)",
          }}
          aria-hidden={fullscreen}
        >
          <NoteDetail
            note={active}
            course={courseFor(active.courseId)}
            onChange={(patch) => updateActive(patch)}
            onDelete={async () => {
              if (!userId) return;
              await apiDeleteNote(active.id, userId);
              setNotes((prev) => prev.filter((n) => n.id !== active.id));
              setActiveId((id) => {
                const remaining = notes.filter((n) => n.id !== id);
                return remaining[0]?.id ?? null;
              });
            }}
            onLink={() => setConceptPickerOpen(true)}
            onUnlink={async (conceptId: string) => {
              if (!userId) return;
              await unlinkNoteConcept(active.id, userId, conceptId);
              const fresh = await listNoteConcepts(active.id, userId);
              setNotes((prev) =>
                prev.map((n) =>
                  n.id === active.id
                    ? {
                        ...n,
                        linkedConcepts: fresh.concepts.map((c) => ({
                          id: c.id, name: c.concept_name, course: "",
                          mastery: (c.mastery_tier === "subject_root" ? "unexplored" : c.mastery_tier) as Mastery,
                        })),
                      }
                    : n,
                ),
              );
            }}
            onSummarize={onSummarize}
            onExtractConcepts={onExtractConcepts}
            onGenerateQuiz={onGenerateQuiz}
            onSendToTutor={onSendToTutor}
            busy={busy}
          />
        </div>

        <div
          style={{
            flex: fullscreen ? "0 0 clamp(300px, 24%, 380px)" : "0 0 0px",
            minWidth: 0,
            opacity: fullscreen ? 1 : 0,
            overflow: "hidden",
            pointerEvents: fullscreen ? undefined : "none",
            display: "flex",
            flexDirection: "column",
            paddingTop: fullscreen ? 32 : 0,
            paddingBottom: fullscreen ? 32 : 0,
            transition:
              "flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease), padding var(--dur-slow) var(--ease)",
          }}
          aria-hidden={!fullscreen}
        >
          <AIChatPanel />
        </div>
      </div>

      {pickerOpen && (
        <CoursePickerModal
          courses={courses}
          onPick={createNoteIn}
          onClose={() => setPickerOpen(false)}
        />
      )}
      {conceptPickerOpen && active && userId && (
        <ConceptPickerModal
          userId={userId}
          courseId={active.courseId}
          alreadyLinkedIds={new Set(active.linkedConcepts.map((c) => c.id))}
          onPick={async (cid) => {
            await linkNoteConcept(active.id, userId, cid);
            await refreshConcepts();
            setConceptPickerOpen(false);
          }}
          onClose={() => setConceptPickerOpen(false)}
        />
      )}
    </div>
  );
}

function NotesList({
  notes,
  totalCount,
  courses,
  activeId,
  query,
  onQueryChange,
  courseFilter,
  onCourseFilterChange,
  onSelect,
  onCreate,
}: {
  notes: Note[];
  totalCount: number;
  courses: Course[];
  activeId: string;
  query: string;
  onQueryChange: (v: string) => void;
  courseFilter: string | null;
  onCourseFilterChange: (v: string | null) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  return (
    <aside
      className="card"
      style={{
        padding: 0,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      <div style={{ padding: "14px 16px 10px", borderBottom: "1px solid var(--border)" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 10,
          }}
        >
          <div className="label-micro">All notes</div>
          <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {notes.length}
            {courseFilter ? ` / ${totalCount}` : ""}
          </span>
        </div>
        <div style={{ position: "relative", marginBottom: 10 }}>
          <span
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--text-muted)",
              display: "inline-flex",
              pointerEvents: "none",
            }}
          >
            <Icon name="search" size={13} />
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search notes…"
            style={{
              width: "100%",
              padding: "8px 10px 8px 30px",
              fontSize: 13,
              fontFamily: "var(--font-sans)",
              background: "var(--bg-input)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r-sm)",
              color: "var(--text)",
              outline: "none",
            }}
          />
        </div>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
          }}
        >
          <CourseFilterChip
            active={courseFilter === null}
            label="All"
            onClick={() => onCourseFilterChange(null)}
          />
          {courses.map((c) => (
            <CourseFilterChip
              key={c.id}
              active={courseFilter === c.id}
              label={c.code}
              color={c.color}
              onClick={() => onCourseFilterChange(courseFilter === c.id ? null : c.id)}
            />
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "6px" }}>
        {notes.length === 0 ? (
          <div
            style={{
              padding: "20px 12px",
              fontSize: 12,
              color: "var(--text-muted)",
              textAlign: "center",
            }}
          >
            No notes match the current filters.
          </div>
        ) : (
          notes.map((n) => {
            const isActive = n.id === activeId;
            const c = courses.find((x) => x.id === n.courseId) ?? { id: n.courseId, name: "Course", code: "—", color: "#9a9a9a" };
            return (
              <button
                key={n.id}
                type="button"
                onClick={() => onSelect(n.id)}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "10px 12px",
                  marginBottom: 2,
                  borderRadius: "var(--r-sm)",
                  background: isActive ? "var(--bg-soft)" : "transparent",
                  color: isActive ? "var(--text)" : "var(--text-dim)",
                  fontWeight: isActive ? 600 : 400,
                  border: "none",
                  cursor: "pointer",
                  transition: "background var(--dur-fast) var(--ease)",
                }}
              >
                <div
                  style={{
                    fontSize: 13,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    marginBottom: 4,
                  }}
                >
                  {n.title || "Untitled note"}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 11,
                    color: "var(--text-muted)",
                    fontWeight: 400,
                  }}
                >
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: c.color,
                      flexShrink: 0,
                    }}
                  />
                  <span>{c.code}</span>
                  <span aria-hidden>·</span>
                  <span>{relTime(n.updatedAt)}</span>
                </div>
              </button>
            );
          })
        )}
      </div>

      <div style={{ padding: 10, borderTop: "1px solid var(--border)" }}>
        <button
          type="button"
          onClick={onCreate}
          className="btn btn--primary"
          style={{ width: "100%", justifyContent: "center", display: "inline-flex" }}
        >
          <Icon name="plus" size={13} /> New note
        </button>
      </div>
    </aside>
  );
}

function CourseFilterChip({
  active,
  label,
  color,
  onClick,
}: {
  active: boolean;
  label: string;
  color?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="chip"
      style={{
        cursor: "pointer",
        border: "1px solid transparent",
        background: active ? "var(--accent-soft)" : "var(--bg-soft)",
        color: active ? "var(--accent)" : "var(--text-dim)",
        borderColor: active ? "var(--accent-border)" : "transparent",
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
      }}
    >
      {color && (
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: color,
            display: "inline-block",
          }}
        />
      )}
      {label}
    </button>
  );
}

function NoteEditor({
  note,
  onChange,
  fullscreen,
  onToggleFullscreen,
}: {
  note: Note;
  onChange: (patch: Partial<Note>) => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  const surfaceTransition =
    "background var(--dur-slow) var(--ease), border-color var(--dur-slow) var(--ease), box-shadow var(--dur-slow) var(--ease), border-radius var(--dur-slow) var(--ease)";

  return (
    <section
      style={{
        padding: 0,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        overflow: "hidden",
        width: "100%",
        background: fullscreen ? "transparent" : "var(--bg-panel)",
        border: "1px solid",
        borderColor: fullscreen ? "transparent" : "var(--border)",
        borderRadius: fullscreen ? 0 : "var(--r-lg)",
        boxShadow: fullscreen ? "none" : "var(--shadow-sm)",
        transition: surfaceTransition,
      }}
    >
      <div
        style={{
          padding: fullscreen ? "48px 56px 20px" : "20px 28px 16px",
          borderBottom: "1px solid",
          borderColor: fullscreen ? "transparent" : "var(--border)",
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          transition:
            "padding var(--dur-slow) var(--ease), border-color var(--dur-slow) var(--ease)",
        }}
      >
        <input
          value={note.title}
          onChange={(e) => onChange({ title: e.target.value })}
          placeholder="Untitled note"
          className="h-serif"
          style={{
            flex: 1,
            minWidth: 0,
            fontSize: fullscreen ? 42 : 30,
            fontWeight: 500,
            letterSpacing: "-0.015em",
            lineHeight: 1.2,
            color: "var(--text)",
            background: "transparent",
            border: "none",
            outline: "none",
            padding: 0,
            transition: "font-size var(--dur-slow) var(--ease)",
          }}
        />
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={onToggleFullscreen}
          title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen editor"}
          style={{ flexShrink: 0 }}
        >
          <Icon name={fullscreen ? "x" : "max"} size={12} />
        </button>
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: fullscreen ? "24px 56px" : "20px 28px",
          transition: "padding var(--dur-slow) var(--ease)",
        }}
      >
        <textarea
          value={note.body}
          onChange={(e) => onChange({ body: e.target.value })}
          placeholder="Start writing — Sapling will pick up concepts as you go."
          className="body-serif"
          style={{
            width: "100%",
            minHeight: fullscreen ? "calc(100vh - 280px)" : 320,
            border: "none",
            outline: "none",
            resize: "none",
            background: "transparent",
            fontSize: fullscreen ? 14 : 15,
            lineHeight: 1.7,
            color: "var(--text)",
            fontFamily: "var(--font-serif)",
            transition: "font-size var(--dur-slow) var(--ease)",
          }}
        />
      </div>

      <div
        style={{
          padding: fullscreen ? "14px 56px" : "10px 22px",
          borderTop: "1px solid",
          borderColor: fullscreen ? "transparent" : "var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          background: fullscreen ? "transparent" : "var(--bg-inset)",
          fontSize: 11,
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.04em",
          transition:
            "padding var(--dur-slow) var(--ease), background var(--dur-slow) var(--ease), border-color var(--dur-slow) var(--ease)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Icon name="check" size={11} />
          Saved · {relTime(note.updatedAt)}
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
          <span>{note.body.split(/\s+/).filter(Boolean).length} words</span>
          <span>{note.body.length} chars</span>
          {fullscreen && <span>Esc to exit</span>}
        </span>
      </div>
    </section>
  );
}

function NoteDetail({
  note,
  course,
  onChange,
  onDelete,
  onLink,
  onUnlink,
  onSummarize,
  onExtractConcepts,
  onGenerateQuiz,
  onSendToTutor,
  busy,
}: {
  note: Note;
  course: Course;
  onChange: (patch: Partial<Pick<Note, "tags">>) => void;
  onDelete: () => void;
  onLink: () => void;
  onUnlink: (conceptId: string) => void;
  onSummarize: () => void;
  onExtractConcepts: () => void;
  onGenerateQuiz: () => void;
  onSendToTutor: () => void;
  busy: null | "summarize" | "extract" | "quiz" | "tutor";
}) {
  const [tagDraft, setTagDraft] = React.useState("");
  const addTag = () => {
    const t = tagDraft.trim();
    if (!t) return;
    if (note.tags.includes(t)) {
      setTagDraft("");
      return;
    }
    onChange({ tags: [...note.tags, t] });
    setTagDraft("");
  };
  const removeTag = (t: string) => {
    onChange({ tags: note.tags.filter((x) => x !== t) });
  };

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        minHeight: 0,
        overflowY: "auto",
      }}
    >
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>
          Linked concepts
        </div>
        {note.linkedConcepts.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            No concepts linked yet. Sapling will surface them as you write.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {note.linkedConcepts.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onUnlink(c.id)}
                title="Unlink concept"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  borderRadius: "var(--r-sm)",
                  background: "var(--bg-subtle)",
                  border: "none",
                  width: "100%",
                  textAlign: "left",
                  cursor: "pointer",
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: MASTERY_COLOR[c.mastery],
                    flexShrink: 0,
                  }}
                />
                <span style={{ flex: 1, fontSize: 13, color: "var(--text)" }}>
                  {c.name}
                </span>
                <span
                  className="mono"
                  style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}
                >
                  {c.mastery}
                </span>
                <Icon name="chev" size={11} />
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={onLink}
          style={{ marginTop: 10, width: "100%", justifyContent: "center", display: "inline-flex" }}
        >
          <Icon name="plus" size={11} /> Link concept
        </button>
      </div>

      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>
          Tags
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {note.tags.map((t) => (
            <button
              key={t}
              type="button"
              className="chip"
              onClick={() => removeTag(t)}
              style={{ cursor: "pointer" }}
              title="Remove tag"
            >
              {t} ×
            </button>
          ))}
          <input
            value={tagDraft}
            onChange={(e) => setTagDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addTag();
              }
            }}
            placeholder="+ add tag"
            className="chip"
            style={{
              background: "transparent",
              border: "1px dashed var(--border-strong)",
              outline: "none",
              minWidth: 80,
              fontFamily: "var(--font-sans)",
            }}
          />
        </div>
      </div>

      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>
          Sapling actions
        </div>
        {note.lastSummary && (
          <div style={{ marginBottom: 10, padding: 10, background: "var(--bg-subtle)", borderRadius: "var(--r-sm)", fontSize: 12, lineHeight: 1.5 }}>
            {note.lastSummary}
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!!busy}
            onClick={onSummarize}
            style={{ justifyContent: "flex-start", textAlign: "left" }}
          >
            <Icon name="sparkle" size={13} /> {busy === "summarize" ? "Summarizing…" : "Summarize note"}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!!busy}
            onClick={onExtractConcepts}
            style={{ justifyContent: "flex-start", textAlign: "left" }}
          >
            <Icon name="brain" size={13} /> {busy === "extract" ? "Extracting…" : "Extract concepts"}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!!busy}
            onClick={onGenerateQuiz}
            style={{ justifyContent: "flex-start", textAlign: "left" }}
          >
            <Icon name="flask" size={13} /> {busy === "quiz" ? "Generating…" : "Generate quiz"}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!!busy}
            onClick={onSendToTutor}
            style={{ justifyContent: "flex-start", textAlign: "left" }}
          >
            <Icon name="bolt" size={13} /> {busy === "tutor" ? "Opening tutor…" : "Send to tutor"}
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>
          Note info
        </div>
        <dl
          style={{
            margin: 0,
            display: "grid",
            gridTemplateColumns: "auto 1fr",
            rowGap: 6,
            columnGap: 12,
            fontSize: 12,
          }}
        >
          <dt style={{ color: "var(--text-muted)" }}>Course</dt>
          <dd style={{ margin: 0, color: "var(--text)" }}>{course.name}</dd>
          <dt style={{ color: "var(--text-muted)" }}>Updated</dt>
          <dd style={{ margin: 0, color: "var(--text)" }}>{relTime(note.updatedAt)}</dd>
          <dt style={{ color: "var(--text-muted)" }}>Concepts</dt>
          <dd className="mono" style={{ margin: 0, color: "var(--text)" }}>
            {note.linkedConcepts.length}
          </dd>
        </dl>
        <button
          type="button"
          className="btn btn--danger btn--sm"
          onClick={onDelete}
          style={{ marginTop: 12, width: "100%", justifyContent: "center", display: "inline-flex" }}
        >
          <Icon name="x" size={11} /> Delete note
        </button>
      </div>
    </aside>
  );
}

function CoursePickerModal({
  courses,
  onPick,
  onClose,
}: {
  courses: Course[];
  onPick: (courseId: string) => void;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "rgba(19, 17, 13, 0.45)",
        backdropFilter: "blur(2px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{
          width: "100%",
          maxWidth: 520,
          padding: 0,
          boxShadow: "var(--shadow-lg)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "20px 24px 12px",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <div className="label-micro" style={{ marginBottom: 6 }}>
            New note
          </div>
          <h2
            className="h-serif"
            style={{ margin: 0, fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em" }}
          >
            Which course is this for?
          </h2>
          <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--text-dim)" }}>
            Pick a course so Sapling can link concepts to the right knowledge graph.
          </p>
        </div>

        <div style={{ padding: 10, display: "flex", flexDirection: "column", gap: 4 }}>
          {courses.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => onPick(c.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "12px 14px",
                borderRadius: "var(--r-md)",
                border: "1px solid var(--border)",
                background: "var(--bg-panel)",
                cursor: "pointer",
                textAlign: "left",
                transition: "background var(--dur-fast) var(--ease)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--bg-soft)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--bg-panel)";
              }}
            >
              <span
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: "50%",
                  background: c.color,
                  flexShrink: 0,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>
                  {c.name}
                </div>
                <div
                  className="mono"
                  style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}
                >
                  {c.code}
                </div>
              </div>
              <Icon name="chev" size={13} />
            </button>
          ))}
        </div>

        <div
          style={{
            padding: "12px 16px",
            borderTop: "1px solid var(--border)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            background: "var(--bg-subtle)",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            You can change this later.
          </span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function ConceptPickerModal({
  userId,
  courseId,
  alreadyLinkedIds,
  onPick,
  onClose,
}: {
  userId: string;
  courseId: string;
  alreadyLinkedIds: Set<string>;
  onPick: (conceptNodeId: string) => void;
  onClose: () => void;
}) {
  const [nodes, setNodes] = React.useState<{ id: string; concept_name: string; mastery_tier: string }[]>([]);
  const [q, setQ] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    import("@/lib/api").then(({ getGraph }) => getGraph(userId)).then((res) => {
      if (cancelled) return;
      const filtered = (res.nodes as { id: string; concept_name: string; mastery_tier: string; course_id?: string | null }[])
        .filter((n) => !n.course_id || n.course_id === courseId)
        .filter((n) => !alreadyLinkedIds.has(n.id));
      setNodes(filtered);
    });
    return () => { cancelled = true; };
  }, [userId, courseId, alreadyLinkedIds]);

  const filtered = nodes.filter((n) =>
    q ? n.concept_name.toLowerCase().includes(q.toLowerCase()) : true,
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 200,
        background: "rgba(19, 17, 13, 0.45)", backdropFilter: "blur(2px)",
        display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{ width: "100%", maxWidth: 520, padding: 0, boxShadow: "var(--shadow-lg)", overflow: "hidden" }}
      >
        <div style={{ padding: "20px 24px 12px", borderBottom: "1px solid var(--border)" }}>
          <div className="label-micro" style={{ marginBottom: 6 }}>Link concept</div>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search concepts…"
            style={{
              width: "100%", padding: "8px 10px", fontSize: 13,
              background: "var(--bg-input)", border: "1px solid var(--border)",
              borderRadius: "var(--r-sm)", color: "var(--text)", outline: "none",
            }}
          />
        </div>
        <div style={{ padding: 10, maxHeight: 380, overflowY: "auto" }}>
          {filtered.length === 0 ? (
            <div style={{ padding: 16, fontSize: 12, color: "var(--text-muted)", textAlign: "center" }}>
              No matching concepts in this course.
            </div>
          ) : filtered.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => onPick(n.id)}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "10px 12px", borderRadius: "var(--r-sm)",
                background: "transparent", border: "none",
                cursor: "pointer", fontSize: 13, color: "var(--text)",
              }}
            >
              {n.concept_name}
              <span className="mono" style={{ marginLeft: 8, fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>
                {n.mastery_tier}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

type ChatMessage = { role: "user" | "ai"; text: string };

function AIChatPanel() {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [input, setInput] = React.useState("");
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = () => {
    const text = input.trim();
    if (!text) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          role: "ai",
          text: "I'm thinking about that — once wired up, I'll pull from this note and your linked concepts.",
        },
      ]);
    }, 600);
  };

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-lg)",
        boxShadow: "var(--shadow-sm)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "14px 16px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Icon name="sparkle" size={13} />
        <span className="label-micro">Quick questions</span>
      </div>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "14px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {messages.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6 }}>
            Ask Sapling anything about what you&apos;re writing — clarify a concept, check a
            definition, or surface related ideas.
          </div>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              style={{
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "85%",
                padding: "8px 11px",
                borderRadius: "var(--r-md)",
                background: m.role === "user" ? "var(--accent-soft)" : "var(--bg-subtle)",
                color: m.role === "user" ? "var(--accent)" : "var(--text)",
                fontSize: 13,
                lineHeight: 1.5,
              }}
            >
              {m.text}
            </div>
          ))
        )}
      </div>

      <div
        style={{
          padding: 10,
          borderTop: "1px solid var(--border)",
          display: "flex",
          gap: 6,
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask a quick question…"
          style={{
            flex: 1,
            minWidth: 0,
            padding: "8px 10px",
            fontSize: 13,
            fontFamily: "var(--font-sans)",
            background: "var(--bg-input)",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-sm)",
            color: "var(--text)",
            outline: "none",
          }}
        />
        <button
          type="button"
          onClick={send}
          className="btn btn--sm btn--primary"
          disabled={!input.trim()}
          style={{ flexShrink: 0 }}
        >
          <Icon name="bolt" size={12} />
        </button>
      </div>
    </aside>
  );
}
