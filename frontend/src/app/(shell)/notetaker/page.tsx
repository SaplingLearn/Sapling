"use client";
import React, { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Icon } from "@/components/Icon";
import { useUser } from "@/context/UserContext";
import {
  listNotes,
  createNote as createNoteApi,
  deleteNote as deleteNoteApi,
  listNoteConcepts,
  linkNoteConcept,
  unlinkNoteConcept,
  summarizeNote,
  extractNoteConcepts,
  generateQuizFromNote,
  sendNoteToTutor,
  noteChat,
  getCourses,
  getGraph,
  type EnrolledCourse,
} from "@/lib/api";
import type {
  Note as ApiNote,
  LinkedConcept as ApiLinkedConcept,
  GraphNode,
} from "@/lib/types";
import { now } from "@/lib/testMode";
import { motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import styles from "./notetaker.module.css";
import { useToast } from "@/components/ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import { withheldNotice } from "@/lib/integrityNotice";
import { quizHrefForNote } from "@/lib/quiz/noteHref";
import { noteTutorHref } from "@/lib/data";
import { useNoteAutosave, type AutosaveStatus } from "@/lib/notes/useNoteAutosave";
import { CHAT_MESSAGE_MAX, NOTE_BODY_MAX, NOTE_TITLE_MAX } from "@/lib/inputLimits";
import { CrisisSupportCard, useCrisisSupport } from "@/components/safety/CrisisSupportCard";
import { crisisSupportIn, crisisSupportInError, markNoteCardShown, type CrisisSupport } from "@/lib/crisisSupport";
import {
  layoutRowStyle,
  notesListRailStyle,
  editorFrameStyle,
  noteDetailRailStyle,
  chatRailStyle,
} from "@/lib/notes/notetakerLayout";

type Mastery = "mastered" | "learning" | "struggling" | "unexplored";

type NoteAction = "delete" | "summarize" | "extract" | "quiz" | "tutor";

type Course = {
  id: string;
  name: string;
  code: string;
  color: string;
};

// `courseId`: the concept's own course (#866 K05: Send to tutor's goal names only its note's course's)
type Concept = { id: string; name: string; course: string; courseId: string | null; mastery: Mastery };

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

/** A course with no colour of its own: the brand green. */
const COURSE_FALLBACK_COLOR = "var(--sap-400)";

/** A modal card's click stays inside it (the backdrop's click closes). */
const stopClick = (e: React.MouseEvent) => e.stopPropagation();

/** A dot's colour, as the `--dot-color` the module's `.dot` reads. */
const dotColor = (color: string) => ({ "--dot-color": color }) as React.CSSProperties;

const MASTERY_COLOR: Record<Mastery, string> = {
  mastered: "var(--state-mastery)",
  learning: "var(--state-progress)",
  struggling: "var(--state-struggle)",
  unexplored: "var(--state-neutral)",
};

function normalizeMastery(tier: string): Mastery {
  if (tier === "mastered" || tier === "learning" || tier === "struggling") return tier;
  return "unexplored";
}

function relTime(d: Date) {
  const diff = now() - d.getTime();
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

function enrolledToCourse(e: EnrolledCourse): Course {
  return {
    id: e.course_id,
    name: e.nickname || e.course_name,
    code: e.course_code,
    color: e.color || COURSE_FALLBACK_COLOR,
  };
}

function apiNoteToNote(n: ApiNote): Note {
  return {
    id: n.id,
    title: n.title || "",
    body: n.body || "",
    courseId: n.course_id,
    updatedAt: new Date(n.updated_at || now()),
    tags: n.tags || [],
    linkedConcepts: [],
    lastSummary: n.last_summary || null,
  };
}

function apiConceptToConcept(c: ApiLinkedConcept, courseCode: string): Concept {
  return {
    id: c.id,
    name: c.concept_name,
    course: courseCode,
    courseId: c.course_id ?? null,
    mastery: normalizeMastery(c.mastery_tier),
  };
}

/**
 * `NotetakerScreen` reads `?note=<id>` off `useSearchParams`, which App Router
 * requires to sit under a Suspense boundary (the same convention `/quiz` and
 * `/dashboard` use — see their `page.tsx`).
 */
export default function NotetakerPage() {
  return (
    <Suspense fallback={null}>
      <NotetakerScreen />
    </Suspense>
  );
}

function NotetakerScreen() {
  const { userId, userReady } = useUser();
  const router = useRouter();
  const searchParams = useSearchParams();
  const toast = useToast();
  // docs/safety/crisis-support.md: the card a note action's answer carries.
  // A note that matched never blocks its action: the card shows BESIDE the
  // result (`crisis_support_alongside`), or beside an error that carries it.
  const crisis = useCrisisSupport();

  const [courses, setCourses] = React.useState<Course[]>([]);
  const [notes, setNotes] = React.useState<Note[]>([]);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [courseFilter, setCourseFilter] = React.useState<string | null>(null);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [conceptPickerOpen, setConceptPickerOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(true);

  const active = notes.find((n) => n.id === activeId) ?? notes[0] ?? null;

  const courseFor = React.useCallback(
    (id: string): Course =>
      courses.find((c) => c.id === id) ?? {
        id,
        name: "Unknown course",
        code: "—",
        color: "var(--fallback-muted)",
      },
    [courses],
  );

  // Initial load: courses + notes.
  React.useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    (async () => {
      try {
        const [coursesRes, notesRes] = await Promise.all([
          getCourses(userId),
          listNotes(userId),
        ]);
        if (cancelled) return;
        setCourses(coursesRes.courses.map(enrolledToCourse));
        const built = (notesRes.notes ?? []).map(apiNoteToNote);
        setNotes(built);
        setActiveId(built[0]?.id ?? null);
      } catch (e) {
        console.error("Failed to load notetaker data", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userReady, userId]);

  // `?note=<id>` reopens a specific note by URL — the arrival half of the
  // "Generate quiz" round trip (returnTo: `/notetaker?note=<id>`, §6). Applied
  // once per distinct `note` value, and only once notes have loaded: an id
  // that matches a loaded note becomes active; an id that matches nothing is
  // silently ignored (never traps the page on a blank state).
  const appliedNoteParamRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    const noteParam = searchParams.get("note");
    if (!noteParam || notes.length === 0) return;
    if (appliedNoteParamRef.current === noteParam) return;
    appliedNoteParamRef.current = noteParam;
    if (notes.some((n) => n.id === noteParam)) setActiveId(noteParam);
  }, [searchParams, notes]);

  // Load linked concepts when the active note changes.
  const activeIdForConcepts = active?.id ?? null;
  React.useEffect(() => {
    if (!activeIdForConcepts || !userId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await listNoteConcepts(activeIdForConcepts, userId);
        if (cancelled) return;
        setNotes((prev) =>
          prev.map((n) => {
            if (n.id !== activeIdForConcepts) return n;
            const code = courseFor(n.courseId).code;
            return {
              ...n,
              linkedConcepts: (res.concepts || []).map((c) => apiConceptToConcept(c, code)),
            };
          }),
        );
      } catch (e) {
        console.error("Failed to load concepts", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeIdForConcepts, userId, courseFor]);

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

  // Debounced, per-note autosave for title/body/tags (#768): failed saves keep
  // the edit and retry, a deleted note's queued save is cancelled, and the
  // footer status aggregates every note (see lib/notes/useNoteAutosave).
  const {
    status: saveStatus,
    queue: queueSave,
    flush: flushSave,
    cancel: cancelSave,
    retry: retrySave,
  } = useNoteAutosave(userId);

  // Flush pending edits before the active note changes, so switching notes
  // never waits out the debounce on a note the user has left.
  const prevActiveIdRef = React.useRef<string | null>(activeId);
  React.useEffect(() => {
    const prev = prevActiveIdRef.current;
    if (prev && prev !== activeId) void flushSave(prev);
    prevActiveIdRef.current = activeId;
  }, [activeId, flushSave]);

  // Per-note, per-action busy state (#768): each action clears its own flag in
  // `finally`, and an action on note A never locks or relabels note B.
  const [busyByNote, setBusyByNote] = React.useState<Record<string, NoteAction[]>>({});
  const busy: NoteAction | null = active ? (busyByNote[active.id]?.[0] ?? null) : null;
  const runAction = async (
    noteId: string,
    action: NoteAction,
    fn: () => Promise<void>,
  ) => {
    setBusyByNote((prev) => ({ ...prev, [noteId]: [...(prev[noteId] ?? []), action] }));
    try {
      await fn();
    } finally {
      setBusyByNote((prev) => {
        const rest = (prev[noteId] ?? []).filter((a) => a !== action);
        const next = { ...prev };
        if (rest.length) next[noteId] = rest;
        else delete next[noteId];
        return next;
      });
    }
  };

  const updateActive = (patch: Partial<Note>) => {
    if (!active) return;
    setNotes((prev) =>
      prev.map((n) =>
        n.id === active.id ? { ...n, ...patch, updatedAt: new Date(now()) } : n,
      ),
    );
    const apiPatch: Partial<Pick<ApiNote, "title" | "body" | "tags">> = {};
    if (patch.title !== undefined) apiPatch.title = patch.title;
    if (patch.body !== undefined) apiPatch.body = patch.body;
    if (patch.tags !== undefined) apiPatch.tags = patch.tags;
    if (Object.keys(apiPatch).length > 0) queueSave(active.id, apiPatch);
  };

  const createNoteIn = async (courseId: string) => {
    if (!userId) return;
    try {
      const created = await createNoteApi(userId, courseId);
      const fresh = apiNoteToNote(created);
      setNotes((prev) => [fresh, ...prev]);
      setActiveId(fresh.id);
      setPickerOpen(false);
    } catch (e) {
      console.error("Create note failed", e);
    }
  };

  const deleteActive = async () => {
    if (!active || !userId) return;
    const noteId = active.id;
    await runAction(noteId, "delete", async () => {
      // Drop the queued save first so its debounce can't PATCH the note
      // mid-delete; restore it if the delete fails (#768).
      const dropped = cancelSave(noteId);
      try {
        await deleteNoteApi(noteId, userId);
        cancelSave(noteId); // edits typed while the DELETE was in flight
        setNotes((prev) => {
          const next = prev.filter((n) => n.id !== noteId);
          setActiveId(next[0]?.id ?? null);
          return next;
        });
      } catch (e) {
        console.error("Delete failed", e);
        if (dropped) queueSave(noteId, dropped);
      }
    });
  };

  const refreshActiveConcepts = async () => {
    if (!active || !userId) return;
    try {
      const res = await listNoteConcepts(active.id, userId);
      const code = courseFor(active.courseId).code;
      setNotes((prev) =>
        prev.map((n) =>
          n.id === active.id
            ? {
                ...n,
                linkedConcepts: (res.concepts || []).map((c) =>
                  apiConceptToConcept(c, code),
                ),
              }
            : n,
        ),
      );
    } catch (e) {
      console.error("Refresh concepts failed", e);
    }
  };

  // Agent actions read the note server-side, so the latest edits must land
  // first; a failed save aborts the action instead of running on a stale body.
  const saveBeforeAgent = async (noteId: string): Promise<boolean> => {
    if (await flushSave(noteId)) return true;
    toast.error("Couldn't save your latest edits. Check your connection and try again.");
    return false;
  };

  const onSummarize = async () => {
    if (!active || !userId) return;
    const noteId = active.id;
    await runAction(noteId, "summarize", async () => {
      if (!(await saveBeforeAgent(noteId))) return;
      try {
        const res = await summarizeNote(noteId, userId);
        if (crisis.intercept(res) && !res.crisis_support_alongside) return; // no summary was made
        setNotes((prev) =>
          prev.map((n) => (n.id === noteId ? { ...n, lastSummary: res.summary ?? n.lastSummary } : n)),
        );
      } catch (e) {
        console.error("Summarize failed", e);
        crisis.intercept({ crisis_support: crisisSupportInError(e) });
        toast.error(humanizeError(e, "Couldn't summarize this note."));
      }
    });
  };

  const onExtract = async () => {
    if (!active || !userId) return;
    const noteId = active.id;
    await runAction(noteId, "extract", async () => {
      if (!(await saveBeforeAgent(noteId))) return;
      try {
        const res = await extractNoteConcepts(noteId, userId);
        if (crisis.intercept(res) && !res.crisis_support_alongside) return; // nothing was linked
        // spec §13 A125: names held back for giving away an open check's answer
        if (res?.withheld) toast.warn(withheldNotice(res.withheld, "concept"));
        await refreshActiveConcepts();
      } catch (e) {
        console.error("Extract failed", e);
        crisis.intercept({ crisis_support: crisisSupportInError(e) });
        toast.error(humanizeError(e, "Couldn't extract concepts from this note."));
      }
    });
  };

  const onGenerateQuiz = async () => {
    if (!active || !userId) return;
    const noteId = active.id;
    await runAction(noteId, "quiz", async () => {
      if (!(await saveBeforeAgent(noteId))) return;
      try {
        const { concept_node_id } = await generateQuizFromNote(noteId, userId);
        router.push(quizHrefForNote(noteId, concept_node_id));
      } catch (e) {
        console.error("Quiz failed", e);
        toast.error(humanizeError(e, "Couldn't generate a quiz from this note."));
      }
    });
  };

  const onSendToTutor = async () => {
    if (!active || !userId) return;
    const noteId = active.id;
    await runAction(noteId, "tutor", async () => {
      if (!(await saveBeforeAgent(noteId))) return;
      try {
        const res = await sendNoteToTutor(noteId, userId);
        // `note` names the note, so a start on its title unchanged is screened
        // as the student's stored material, not as a topic they typed
        // (docs/safety/crisis-support.md): the card shows beside the session.
        const open = () => router.push(noteTutorHref(res, noteId, active.linkedConcepts)); // K05
        // Beside a result, the tutor opens once the card is closed, told the
        // card was shown so its start does not pop the same one up again; a
        // card that stands in for the result opens nothing.
        const openAfterCard = () => { markNoteCardShown(noteId); open(); };
        if (crisis.intercept(res, res.crisis_support_alongside ? openAfterCard : undefined)) return;
        open();
      } catch (e) {
        console.error("Send to tutor failed", e);
        crisis.intercept({ crisis_support: crisisSupportInError(e) });
        toast.error(humanizeError(e, "Couldn't send this note to the tutor."));
      }
    });
  };

  const onLinkConcept = async (conceptNodeId: string) => {
    if (!active || !userId) return;
    try {
      await linkNoteConcept(active.id, userId, conceptNodeId);
      await refreshActiveConcepts();
      setConceptPickerOpen(false);
    } catch (e) {
      console.error("Link concept failed", e);
    }
  };

  const onUnlinkConcept = async (conceptNodeId: string) => {
    if (!active || !userId) return;
    try {
      await unlinkNoteConcept(active.id, userId, conceptNodeId);
      await refreshActiveConcepts();
    } catch (e) {
      console.error("Unlink concept failed", e);
    }
  };

  const onAddTag = (tag: string) => {
    if (!active) return;
    const trimmed = tag.trim();
    if (!trimmed || active.tags.includes(trimmed)) return;
    updateActive({ tags: [...active.tags, trimmed] });
  };

  const onRemoveTag = (tag: string) => {
    if (!active) return;
    updateActive({ tags: active.tags.filter((t) => t !== tag) });
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
    if (!pickerOpen && !conceptPickerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPickerOpen(false);
        setConceptPickerOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [pickerOpen, conceptPickerOpen]);

  if (!userReady || loading) {
    return (
      <div className={styles.loading}>
        Loading notes…
      </div>
    );
  }

  if (!active) {
    return renderEmptyState({
      courses,
      pickerOpen,
      onOpenPicker: () => setPickerOpen(true),
      onPick: createNoteIn,
      onClosePicker: () => setPickerOpen(false),
    });
  }

  return (
    <div className={styles.screen}>
      <div style={layoutRowStyle(fullscreen)}>
        {/* A collapsed pane is `inert`, not just aria-hidden: its controls stay
            in the DOM for the width transition, and inert also takes them out
            of the tab order (aria-hidden alone left them focusable; spec §13
            A135). */}
        <div style={notesListRailStyle(fullscreen)} inert={fullscreen}>
          <NotesList
            notes={filtered}
            totalCount={notes.length}
            courses={courses}
            activeId={active.id}
            courseFor={courseFor}
            query={query}
            onQueryChange={setQuery}
            courseFilter={courseFilter}
            onCourseFilterChange={setCourseFilter}
            onSelect={setActiveId}
            onCreate={() => setPickerOpen(true)}
          />
        </div>

        <div className={styles.editorSlot}>
          <div style={editorFrameStyle(fullscreen)}>
            <NoteEditor
              note={active}
              onChange={updateActive}
              saveStatus={saveStatus}
              onRetrySave={retrySave}
              fullscreen={fullscreen}
              onToggleFullscreen={() => setFullscreen((f) => !f)}
            />
          </div>
        </div>

        <div style={noteDetailRailStyle(fullscreen)} inert={fullscreen}>
          <NoteDetail
            note={active}
            course={courseFor(active.courseId)}
            busy={busy}
            onSummarize={onSummarize}
            onExtract={onExtract}
            onGenerateQuiz={onGenerateQuiz}
            onSendToTutor={onSendToTutor}
            onOpenConceptPicker={() => setConceptPickerOpen(true)}
            onUnlinkConcept={onUnlinkConcept}
            onAddTag={onAddTag}
            onRemoveTag={onRemoveTag}
            onDelete={deleteActive}
          />
        </div>

        <div style={chatRailStyle(fullscreen)} inert={!fullscreen}>
          {/* Keyed per note: switching notes starts a fresh thread + composer. */}
          <AIChatPanel key={active.id} noteId={active.id} userId={userId} />
        </div>
      </div>

      {pickerOpen && (
        <CoursePickerModal
          courses={courses}
          onPick={createNoteIn}
          onClose={() => setPickerOpen(false)}
        />
      )}
      {conceptPickerOpen && userId && (
        <ConceptPickerModal
          userId={userId}
          courseId={active.courseId}
          alreadyLinkedIds={new Set(active.linkedConcepts.map((c) => c.id))}
          onPick={onLinkConcept}
          onClose={() => setConceptPickerOpen(false)}
        />
      )}
      {crisis.dialog}
    </div>
  );
}

/**
 * The no-notes screen. A plain render helper rather than a component, so the
 * element tree (and its reconciliation against the editor layout once the
 * first note exists) is exactly what the inline branch rendered.
 */
function renderEmptyState({
  courses,
  pickerOpen,
  onOpenPicker,
  onPick,
  onClosePicker,
}: {
  courses: Course[];
  pickerOpen: boolean;
  onOpenPicker: () => void;
  onPick: (courseId: string) => void;
  onClosePicker: () => void;
}) {
  return (
    <>
      <div className={styles.empty}>
        <div className={styles.emptyHeader}><div className="label-micro">Notetaker</div></div>
        <div className={styles.emptyBody}>
        <h2 className={`h-serif ${styles.emptyTitle}`}>
          No notes yet
        </h2>
        <p className={styles.emptyCopy}>
          Pick a course to start — Sapling will link the concepts you write to its
          knowledge graph.
        </p>
        <button
          type="button"
          onClick={onOpenPicker}
          disabled={courses.length === 0}
          className={`btn btn--primary ${styles.emptyCta}`}
        >
          <Icon name="plus" size={13} /> Create your first note
        </button>
        {courses.length === 0 && (
          <p className={styles.hint}>
            Add a course first to start taking notes.
          </p>
        )}
        </div>
      </div>
      {pickerOpen && (
        <CoursePickerModal
          courses={courses}
          onPick={onPick}
          onClose={onClosePicker}
        />
      )}
    </>
  );
}

function NotesList({
  notes,
  totalCount,
  courses,
  activeId,
  courseFor,
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
  courseFor: (id: string) => Course;
  query: string;
  onQueryChange: (v: string) => void;
  courseFilter: string | null;
  onCourseFilterChange: (v: string | null) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  return (
    <aside className={`card ${styles.listCard}`}>
      <div className={styles.listHead}>
        <div className={styles.listTitleRow}>
          <div className="label-micro">All notes</div>
          <span className={`mono ${styles.count}`}>
            {notes.length}
            {courseFilter ? ` / ${totalCount}` : ""}
          </span>
        </div>
        <div className={styles.searchWrap}>
          <span className={styles.searchIcon}>
            <Icon name="search" size={13} />
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search notes…"
            className={`${styles.field} ${styles.fieldWithIcon}`}
          />
        </div>
        {courses.length > 0 && (
          <div className={styles.chips}>
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
                onClick={() =>
                  onCourseFilterChange(courseFilter === c.id ? null : c.id)
                }
              />
            ))}
          </div>
        )}
      </div>

      <div className={styles.listScroll}>
        {notes.length === 0 ? (
          <div className={styles.listEmpty}>
            No notes match the current filters.
          </div>
        ) : (
          notes.map((n) => {
            const isActive = n.id === activeId;
            const c = courseFor(n.courseId);
            return (
              <button
                key={n.id}
                type="button"
                onClick={() => onSelect(n.id)}
                className={`${styles.noteRow} ${isActive ? styles.noteRowActive : ""}`}
              >
                <div className={styles.noteTitle}>
                  {n.title || "Untitled note"}
                </div>
                <div className={styles.noteMeta}>
                  <span className={styles.dot} style={dotColor(c.color)} />
                  <span>{c.code}</span>
                  <span aria-hidden>·</span>
                  <span>{relTime(n.updatedAt)}</span>
                </div>
              </button>
            );
          })
        )}
      </div>

      <div className={styles.listFoot}>
        <button
          type="button"
          onClick={onCreate}
          className={`btn btn--primary ${styles.blockBtn}`}
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
      className={`chip ${styles.filterChip} ${active ? styles.filterChipActive : ""}`}
    >
      {color && <span className={`${styles.dot} ${styles.dotInline}`} style={dotColor(color)} />}
      {label}
    </button>
  );
}

function NoteEditor({
  note,
  onChange,
  saveStatus,
  onRetrySave,
  fullscreen,
  onToggleFullscreen,
}: {
  note: Note;
  onChange: (patch: Partial<Note>) => void;
  saveStatus: AutosaveStatus;
  onRetrySave: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  // Fullscreen is one modifier class: every size, inset and surface change
  // below tweens through the module's --dur-slow transitions.
  return (
    <section className={`${styles.editor} ${fullscreen ? styles.editorFull : ""}`}>
      <div className={styles.editorHead}>
        <input
          value={note.title}
          maxLength={NOTE_TITLE_MAX}
          onChange={(e) => onChange({ title: e.target.value })}
          placeholder="Untitled note"
          className={`h-serif ${styles.titleInput}`}
        />
        <button
          type="button"
          onClick={onToggleFullscreen}
          title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen editor"}
          className={`btn btn--ghost btn--sm ${styles.noShrink}`}
        >
          <Icon name={fullscreen ? "x" : "max"} size={12} />
        </button>
      </div>

      <div className={styles.editorBody}>
        <textarea
          value={note.body}
          maxLength={NOTE_BODY_MAX}
          onChange={(e) => onChange({ body: e.target.value })}
          placeholder="Start writing — Sapling will pick up concepts as you go."
          className={`body-serif ${styles.bodyInput}`}
        />
      </div>

      <div className={styles.editorFoot}>
        {saveStatus === "error" ? (
          <span role="status" className={`${styles.inlineRow} ${styles.saveError}`}>
            <Icon name="x" size={11} />
            Couldn&apos;t save ·
            <button
              type="button"
              className={`btn btn--ghost btn--sm ${styles.retryBtn}`}
              onClick={onRetrySave}
            >
              Retry
            </button>
          </span>
        ) : (
          <span className={styles.inlineRow}>
            <Icon name={saveStatus === "saved" ? "check" : "pencil"} size={11} />
            {saveStatus === "saving"
              ? "Saving…"
              : saveStatus === "unsaved"
                ? "Unsaved changes"
                : `Saved · ${relTime(note.updatedAt)}`}
          </span>
        )}
        <span className={`${styles.inlineRow} ${styles.inlineRowWide}`}>
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
  busy,
  onSummarize,
  onExtract,
  onGenerateQuiz,
  onSendToTutor,
  onOpenConceptPicker,
  onUnlinkConcept,
  onAddTag,
  onRemoveTag,
  onDelete,
}: {
  note: Note;
  course: Course;
  busy: string | null;
  onSummarize: () => void;
  onExtract: () => void;
  onGenerateQuiz: () => void;
  onSendToTutor: () => void;
  onOpenConceptPicker: () => void;
  onUnlinkConcept: (id: string) => void;
  onAddTag: (tag: string) => void;
  onRemoveTag: (tag: string) => void;
  onDelete: () => void;
}) {
  const [adding, setAdding] = React.useState(false);
  const [draftTag, setDraftTag] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  const commitTag = () => {
    if (draftTag.trim()) onAddTag(draftTag);
    setDraftTag("");
    setAdding(false);
  };

  return (
    <aside className={styles.detail}>
      <div className={`card ${styles.detailCard}`}>
        <div className={`label-micro ${styles.cardLabel}`}>
          Linked concepts
        </div>
        {note.linkedConcepts.length === 0 ? (
          <div className={styles.muted}>
            No concepts linked yet. Sapling will surface them as you write.
          </div>
        ) : (
          <div className={styles.stack}>
            {note.linkedConcepts.map((c) => (
              <div key={c.id} className={styles.conceptRow}>
                <span className={`${styles.dot} ${styles.dotMd}`} style={dotColor(MASTERY_COLOR[c.mastery])} />
                <span className={styles.conceptName}>
                  {c.name}
                </span>
                <span className={`mono ${styles.tier}`}>
                  {c.mastery}
                </span>
                <button
                  type="button"
                  onClick={() => onUnlinkConcept(c.id)}
                  title="Unlink concept"
                  aria-label={`Unlink ${c.name}`}
                  className={styles.iconBtn}
                >
                  <Icon name="x" size={11} />
                </button>
              </div>
            ))}
          </div>
        )}
        <button
          type="button"
          className={`btn btn--ghost btn--sm ${styles.blockBtn} ${styles.cardAction}`}
          onClick={onOpenConceptPicker}
        >
          <Icon name="plus" size={11} /> Link concept
        </button>
      </div>

      <div className={`card ${styles.detailCard}`}>
        <div className={`label-micro ${styles.cardLabel}`}>
          Tags
        </div>
        <div className={styles.tags}>
          {note.tags.length === 0 && !adding && (
            <span className={styles.muted}>No tags.</span>
          )}
          {note.tags.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => onRemoveTag(t)}
              title={`Remove ${t}`}
              className={`chip ${styles.tagChip}`}
            >
              {t}
              <Icon name="x" size={9} />
            </button>
          ))}
          {adding ? (
            <input
              ref={inputRef}
              value={draftTag}
              onChange={(e) => setDraftTag(e.target.value)}
              onBlur={commitTag}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitTag();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  setDraftTag("");
                  setAdding(false);
                }
              }}
              placeholder="tag"
              className={`chip ${styles.tagInput}`}
            />
          ) : (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className={`chip ${styles.tagAdd}`}
            >
              + Add
            </button>
          )}
        </div>
      </div>

      <div className={`card ${styles.detailCard}`}>
        <div className={`label-micro ${styles.cardLabel}`}>
          Sapling actions
        </div>
        <div className={`${styles.stack} ${styles.stackLoose}`}>
          <button
            type="button"
            className={`btn btn--ghost ${styles.actionBtn}`}
            onClick={onSummarize}
            disabled={busy !== null}
          >
            <Icon name="sparkle" size={13} />{" "}
            {busy === "summarize" ? "Summarizing…" : "Summarize note"}
          </button>
          <button
            type="button"
            className={`btn btn--ghost ${styles.actionBtn}`}
            onClick={onExtract}
            disabled={busy !== null}
          >
            <Icon name="brain" size={13} />{" "}
            {busy === "extract" ? "Extracting…" : "Extract concepts"}
          </button>
          <button
            type="button"
            className={`btn btn--ghost ${styles.actionBtn}`}
            onClick={onGenerateQuiz}
            disabled={busy !== null || note.linkedConcepts.length === 0}
          >
            <Icon name="flask" size={13} />{" "}
            {busy === "quiz" ? "Building quiz…" : "Generate quiz"}
          </button>
          <button
            type="button"
            className={`btn btn--ghost ${styles.actionBtn}`}
            onClick={onSendToTutor}
            disabled={busy !== null}
          >
            <Icon name="bolt" size={13} />{" "}
            {busy === "tutor" ? "Opening tutor…" : "Send to tutor"}
          </button>
        </div>
        {note.lastSummary && (
          <div className={styles.summary}>
            <div className={`label-micro ${styles.summaryLabel}`}>
              Last summary
            </div>
            {note.lastSummary}
          </div>
        )}
      </div>

      <div className={`card ${styles.detailCard}`}>
        <div className={`label-micro ${styles.cardLabel}`}>
          Note info
        </div>
        <dl className={styles.info}>
          <dt>Course</dt>
          <dd>{course.name}</dd>
          <dt>Updated</dt>
          <dd>{relTime(note.updatedAt)}</dd>
          <dt>Concepts</dt>
          <dd className="mono">
            {note.linkedConcepts.length}
          </dd>
        </dl>
        <button
          type="button"
          onClick={onDelete}
          disabled={busy !== null}
          className={`btn btn--danger btn--sm ${styles.blockBtn} ${styles.deleteBtn}`}
        >
          <Icon name="x" size={11} />{" "}
          {busy === "delete" ? "Deleting…" : "Delete note"}
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
  const m = useMotionPresets();
  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      className={styles.backdrop}
      {...m.fade}
    >
      <motion.div
        onClick={stopClick}
        className={`card ${styles.modal}`}
        {...m.scaleIn}
      >
        <div className={styles.modalHead}>
          <div className={`label-micro ${styles.modalEyebrow}`}>
            New note
          </div>
          <h2 className={`h-serif ${styles.modalTitle}`}>
            Which course is this for?
          </h2>
          <p className={styles.modalCopy}>
            Pick a course so Sapling can link concepts to the right knowledge graph.
          </p>
        </div>

        <div className={styles.modalList}>
          {courses.length === 0 ? (
            <div className={styles.modalEmpty}>
              No courses enrolled yet.
            </div>
          ) : (
            courses.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onPick(c.id)}
                className={styles.pickRow}
              >
                <span className={`${styles.dot} ${styles.dotLg}`} style={dotColor(c.color)} />
                <div className={styles.pickBody}>
                  <div className={styles.pickName}>
                    {c.name}
                  </div>
                  <div className={`mono ${styles.pickCode}`}>
                    {c.code}
                  </div>
                </div>
                <Icon name="chev" size={13} />
              </button>
            ))
          )}
        </div>

        <div className={styles.modalFoot}>
          <span className={styles.muted}>
            You can change this later.
          </span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
            Cancel
          </button>
        </div>
      </motion.div>
    </motion.div>
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
  const [nodes, setNodes] = React.useState<GraphNode[] | null>(null);
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getGraph(userId);
        if (cancelled) return;
        const filtered = (res.nodes || []).filter(
          (n) => !n.is_subject_root && (!courseId || n.course_id === courseId),
        );
        setNodes(filtered);
      } catch (e) {
        console.error("Graph load failed", e);
        if (!cancelled) setNodes([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, courseId]);

  const visible = React.useMemo(() => {
    if (!nodes) return [];
    const q = query.trim().toLowerCase();
    return nodes.filter((n) => {
      if (alreadyLinkedIds.has(n.id)) return false;
      if (!q) return true;
      return n.concept_name.toLowerCase().includes(q);
    });
  }, [nodes, query, alreadyLinkedIds]);
  const m = useMotionPresets();

  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      className={styles.backdrop}
      {...m.fade}
    >
      <motion.div
        onClick={stopClick}
        className={`card ${styles.modal} ${styles.modalTall}`}
        {...m.scaleIn}
      >
        <div className={styles.modalHead}>
          <div className={`label-micro ${styles.modalEyebrow}`}>
            Link concept
          </div>
          <h2 className={`h-serif ${styles.modalTitle}`}>
            Pick a concept to link
          </h2>
          <p className={styles.modalCopy}>
            From your knowledge graph for this course.
          </p>
        </div>

        <div className={styles.modalSearch}>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search concepts…"
            autoFocus
            className={styles.field}
          />
        </div>

        <div className={styles.modalScroll}>
          {nodes === null ? (
            <div className={styles.modalEmpty}>
              Loading…
            </div>
          ) : visible.length === 0 ? (
            <div className={styles.modalEmpty}>
              No matching concepts.
            </div>
          ) : (
            <div className={styles.stack}>
              {visible.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => onPick(n.id)}
                  className={`${styles.pickRow} ${styles.pickRowTight}`}
                >
                  <span
                    className={`${styles.dot} ${styles.dotMd}`}
                    style={dotColor(MASTERY_COLOR[normalizeMastery(n.mastery_tier)])}
                  />
                  <span className={styles.conceptName}>
                    {n.concept_name}
                  </span>
                  <span className={`mono ${styles.tier}`}>
                    {n.mastery_tier}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className={`${styles.modalFoot} ${styles.modalFootEnd}`}>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
            Cancel
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

type ChatMessage = { role: "user" | "ai"; text: string; crisis?: CrisisSupport };

function AIChatPanel({ noteId, userId }: { noteId: string; userId: string }) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [input, setInput] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const m = useMotionPresets();

  // Stale-reply guard (#768). The parent keys this panel on the note id, so a
  // note switch mounts a fresh thread; this ref additionally pins which note a
  // reply belongs to, and is cleared on unmount / note change, so a reply (or
  // failure) for a note that is no longer showing is dropped, never appended
  // to another note's thread.
  const currentNoteRef = React.useRef<string | null>(noteId);
  React.useEffect(() => {
    currentNoteRef.current = noteId;
    return () => {
      currentNoteRef.current = null;
    };
  }, [noteId]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, error]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending || !userId) return;
    const sentFor = noteId;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setError(null);
    setSending(true);
    try {
      const res = await noteChat(sentFor, userId, text);
      if (currentNoteRef.current !== sentFor) return;
      // docs/safety/crisis-support.md: the card instead of a reply (a typed
      // crisis message), or beside the reply (the note itself matched).
      const crisis = crisisSupportIn(res);
      const reply: ChatMessage = { role: "ai", text: res.reply };
      setMessages((prev) => [
        ...prev,
        ...(crisis ? [{ role: "ai" as const, text: "", crisis }] : []),
        ...(!crisis || res.crisis_support_alongside ? [reply] : []),
      ]);
    } catch (e) {
      console.error("Chat failed", e);
      if (currentNoteRef.current !== sentFor) return;
      const crisis = crisisSupportInError(e);
      // An error state, not a fake AI reply: take the unanswered question back
      // out of the thread and return it to the composer so it can be resent.
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        const kept = last && last.role === "user" && last.text === text ? prev.slice(0, -1) : prev;
        return crisis ? [...kept, { role: "ai", text: "", crisis }] : kept;
      });
      setInput((cur) => (cur ? cur : text));
      setError("Sorry — something went wrong. Try again?");
    } finally {
      if (currentNoteRef.current === sentFor) setSending(false);
    }
  };

  return (
    <aside className={styles.chat}>
      <div className={styles.chatHead}>
        <Icon name="sparkle" size={13} />
        <span className="label-micro">Quick questions</span>
      </div>

      <div ref={scrollRef} className={styles.thread}>
        {messages.length === 0 ? (
          <div className={styles.chatHint}>
            Ask Sapling anything about what you&apos;re writing — clarify a concept,
            check a definition, or surface related ideas.
          </div>
        ) : (
          // Each message mounts once, when it is sent or answered: it rises in.
          messages.map((msg, i) => msg.crisis ? (
            <CrisisSupportCard key={i} support={msg.crisis} />
          ) : (
            <motion.div
              key={i}
              className={`${styles.bubble} ${msg.role === "user" ? styles.bubbleUser : ""}`}
              {...m.fadeUp}
            >
              {msg.text}
            </motion.div>
          ))
        )}
        {sending && (
          <motion.div className={styles.thinking} {...m.fade}>
            Sapling is thinking…
          </motion.div>
        )}
        {error && (
          <motion.div role="alert" className={styles.chatError} {...m.fadeUp}>
            <Icon name="x" size={11} />
            {error}
          </motion.div>
        )}
      </div>

      <div className={styles.composer}>
        <input
          value={input}
          maxLength={CHAT_MESSAGE_MAX}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask a quick question…"
          disabled={sending}
          className={`${styles.field} ${styles.composerField}`}
        />
        <button
          type="button"
          onClick={send}
          className={`btn btn--sm btn--primary ${styles.noShrink}`}
          disabled={!input.trim() || sending}
        >
          <Icon name="bolt" size={12} />
        </button>
      </div>
    </aside>
  );
}
