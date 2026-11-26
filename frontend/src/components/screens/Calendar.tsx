"use client";
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion, type MotionProps } from "framer-motion";
// Importing lib/motion also sets framer's test-mode skip (#383): every
// framer-motion consumer needs it for direct-navigation browser runs.
import { useMotionPresets, type MotionPreset } from "@/lib/motion";
import styles from "./Calendar.module.css";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Toggle } from "@/components/ui";
import { CustomSelect } from "../CustomSelect";
import { DocumentUploadModal } from "../DocumentUploadModal";
import { CalendarMonthSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useUser } from "@/context/UserContext";
import {
  getAllAssignments,
  getCourses,
  getCalendarStatus,
  disconnectCalendar,
  syncCalendar,
  calendarAuthUrl,
  updateAssignment,
  deleteAssignment,
  importGoogleEvents,
  exportToGoogleCalendar,
  type Assignment,
  type EnrolledCourse,
  type GoogleEvent,
} from "@/lib/api";
import { now } from "@/lib/testMode";
import { humanizeError } from "@/lib/errorMessage";
import { CALENDAR_ERROR_PARAM, calendarConnectError } from "@/lib/calendarConnect";
import { useFlag } from "@/context/FlagsContext";
import { CalendarV2 } from "../calendar/v2/CalendarV2";
import { GOOGLE_EVENTS_DAYS, GoogleEventsModal } from "../calendar/GoogleEventsModal";

// lib/motion types a preset's `initial` as TargetAndTransition, which
// motion.div's `initial` prop does not accept as written; the values are the
// same shape, so view one as the other.
const asProps = (p: MotionPreset): MotionProps => p as MotionProps;

type View = "month" | "week" | "day" | "table";

const TYPE_COLOR: Record<string, string> = {
  exam: "var(--c-rust)",
  project: "var(--c-teal)",
  homework: "var(--c-sage)",
  quiz: "var(--warn)",
  reading: "var(--c-plum)",
  other: "var(--text-muted)",
};

/** A syllabus's assignments land after the upload returns; reload once more after this. */
const SYLLABUS_RELOAD_DELAY_MS = 1500;
/** Assignments a month cell lists before "+N more". */
const MONTH_ITEMS_SHOWN = 3;
/** Six weeks of seven days: every month fits. */
const MONTH_CELLS = 42;

const TYPE_OPTIONS = [
  { value: "homework", label: "Homework" },
  { value: "exam", label: "Exam" },
  { value: "quiz", label: "Quiz" },
  { value: "reading", label: "Reading" },
  { value: "project", label: "Project" },
  { value: "other", label: "Other" },
];

function dateKey(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dueLabel(date: string | null) {
  if (!date) return { label: "no date", cls: "chip--info" };
  const nowMs = now();
  const due = new Date(date).getTime();
  const diffMs = due - nowMs;
  const diffHours = diffMs / (1000 * 60 * 60);
  if (diffHours <= 0) return { label: "overdue", cls: "chip--err" };
  if (diffHours <= 24) return { label: "due soon", cls: "chip--err" };
  const days = Math.ceil(diffHours / 24);
  if (days <= 3) return { label: `${days}d`, cls: "chip--warn" };
  return { label: `${days}d`, cls: "chip--info" };
}

export function Calendar() {
  const router = useRouter();
  const search = useSearchParams();
  const toast = useToast();
  const { userId, userReady } = useUser();
  // The view-swap fade/rise; already opacity-only under reduced motion.
  const m = useMotionPresets();
  const v2 = useFlag("calendar_v2") === "on";

  const [assignments, setAssignments] = React.useState<Assignment[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [view, setView] = React.useState<View>("month");
  const [cursor, setCursor] = React.useState(() => new Date(now()));
  const [googleConnected, setGoogleConnected] = React.useState(false);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [googleEvents, setGoogleEvents] = React.useState<GoogleEvent[] | null>(null);
  const [importingGoogle, setImportingGoogle] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  // True once a load has succeeded — gates HOW a later failure surfaces.
  // `load` doubles as the background reload (AssignmentTable's onReload,
  // the OAuth-reconnect effect, upload onComplete), and a reload failure
  // must never blank an already-populated calendar behind the full-page
  // banner (PR #463 review; same `error && !data` gating as the Gradebook
  // screen's ErrorBanner).
  const hasLoadedRef = React.useRef(false);

  const load = React.useCallback(async () => {
    if (!userId) return;
    try {
      const [a, c, s] = await Promise.all([
        getAllAssignments(userId),
        getCourses(userId),
        getCalendarStatus(userId).catch(() => ({ connected: false })),
      ]);
      setAssignments(a.assignments || []);
      setCourses(c.courses || []);
      setGoogleConnected(Boolean(s.connected));
      setLoadError(null);
      hasLoadedRef.current = true;
    } catch (err) {
      // Surface the failure (#185) — a swallowed error here renders a
      // normal-looking empty calendar, indistinguishable from an empty
      // account. Initial load → full-page banner (there is nothing else to
      // show); background reload → toast, keeping the loaded view intact.
      console.error("calendar load failed", err);
      const message = humanizeError(err, "Check your connection and try again.");
      if (hasLoadedRef.current) {
        toast.error(`Couldn't refresh the calendar. ${message}`);
      } else {
        setLoadError(message);
      }
    } finally {
      setLoading(false);
    }
  }, [userId, toast]);

  const retryLoad = React.useCallback(() => {
    setLoading(true);
    void load();
  }, [load]);

  React.useEffect(() => {
    if (userReady && userId) load();
  }, [userReady, userId, load]);

  // Clear ?connected=true after OAuth success.
  React.useEffect(() => {
    if (search.get("connected") === "true") {
      toast.success("Google Calendar connected");
      setGoogleConnected(true);
      const next = new URLSearchParams(search.toString());
      next.delete("connected");
      const qs = next.toString();
      router.replace(qs ? `/calendar?${qs}` : "/calendar");
      void load();
    }
  }, [search, router, toast, load]);

  // The consent flow came back without access (started here or from
  // onboarding's Connect step): say why, then clear the code.
  React.useEffect(() => {
    const code = search.get(CALENDAR_ERROR_PARAM);
    if (!code) return;
    toast.error(calendarConnectError(code));
    const next = new URLSearchParams(search.toString());
    next.delete(CALENDAR_ERROR_PARAM);
    const qs = next.toString();
    router.replace(qs ? `/calendar?${qs}` : "/calendar");
  }, [search, router, toast]);

  const today = React.useMemo(() => {
    const d = new Date(now()); d.setHours(0, 0, 0, 0); return d;
  }, []);

  const byDate = React.useMemo(() => {
    const map = new Map<string, Assignment[]>();
    for (const a of assignments) {
      // Gradebook/Gradescope items may have no due date; they only show in the list view.
      if (!a.due_date) continue;
      const k = a.due_date.slice(0, 10);
      const arr = map.get(k) || [];
      arr.push(a);
      map.set(k, arr);
    }
    return map;
  }, [assignments]);

  const connect = () => {
    if (!userId) return;
    window.location.href = calendarAuthUrl(userId);
  };

  const doSync = async () => {
    try {
      const res = await syncCalendar(userId);
      toast.success(`Synced ${res.synced_count} event${res.synced_count === 1 ? "" : "s"} to Google.`);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't sync your calendar. Try again."));
    }
  };

  const doImport = async () => {
    setImportingGoogle(true);
    try {
      const res = await importGoogleEvents(userId, GOOGLE_EVENTS_DAYS);
      setGoogleEvents(res.events || []);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't import those events."));
    } finally {
      setImportingGoogle(false);
    }
  };

  const doDisconnect = async () => {
    try {
      await disconnectCalendar(userId);
      setGoogleConnected(false);
      toast.success("Google Calendar disconnected.");
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't disconnect that calendar."));
    }
  };
  const disconnectConfirm = useConfirm(doDisconnect);

  const exportCsv = () => {
    const ids = selected.size ? assignments.filter(a => selected.has(a.id)) : assignments;
    if (ids.length === 0) {
      toast.warn("Nothing to export.");
      return;
    }
    const rows = [
      ["Title", "Course", "Type", "Due Date", "Notes"],
      ...ids.map(a => [a.title, a.course_code || a.course_name || "", a.assignment_type || "", a.due_date || "", a.notes || ""]),
    ];
    const csv = rows.map(r => r.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `assignments-${dateKey(new Date(now()))}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${ids.length} row${ids.length === 1 ? "" : "s"}.`);
  };

  const topActions = (
    <>
      <Toggle
        options={[
          { value: "month", label: "Month" },
          { value: "week", label: "Week" },
          { value: "day", label: "Day" },
          { value: "table", label: "Table" },
        ]}
        value={view}
        onChange={setView}
        size="sm"
      />
      {view !== "table" && (
        <>
          <button className="btn btn--sm" onClick={() => shift(setCursor, view, -1)}>
            <Icon name="chev" size={12} /> Prev
          </button>
          <button className="btn btn--sm" onClick={() => setCursor(new Date(now()))}>Today</button>
          <button className="btn btn--sm" onClick={() => shift(setCursor, view, 1)}>
            Next <Icon name="chev" size={12} />
          </button>
        </>
      )}
      <button className="btn btn--sm" data-testid="calendar-import-syllabus" onClick={() => setUploadOpen(true)}>
        <Icon name="upload" size={12} /> Import syllabus
      </button>
      {googleConnected ? (
        <>
          <button className="btn btn--sm" onClick={doSync}>
            <Icon name="send" size={12} /> Sync
          </button>
          <button className="btn btn--sm" onClick={doImport} disabled={importingGoogle}>
            <Icon name="cal" size={12} /> {importingGoogle ? "Loading…" : "View Google events"}
          </button>
          <button
            className={`btn btn--sm${disconnectConfirm.armed ? ` ${styles.armed}` : ""}`}
            onClick={disconnectConfirm.trigger}
          >
            {disconnectConfirm.armed ? "Click again" : "Disconnect"}
          </button>
        </>
      ) : (
        <button className="btn btn--sm btn--primary" onClick={connect}>
          <Icon name="cal" size={12} /> Connect Google
        </button>
      )}
    </>
  );

  const rangeLabel = formatRange(cursor, view);

  return (
    <div className={styles.screen}>
      {v2 && !loading && !loadError ? (
        <CalendarV2 assignments={assignments} courses={courses} now={new Date(now())} googleConnected={googleConnected}
          importingGoogle={importingGoogle} disconnectArmed={disconnectConfirm.armed} onImportSyllabus={() => setUploadOpen(true)}
          onConnectGoogle={connect} onSyncGoogle={doSync} onViewGoogleEvents={doImport} onDisconnectGoogle={disconnectConfirm.trigger}
          onExportCsv={exportCsv} onReload={() => void load()} />
      ) : (<>
      <TopBar
        title="Calendar"
        subtitle={`${rangeLabel} · ${assignments.length} assignment${assignments.length === 1 ? "" : "s"}`}
        actions={v2 ? undefined : topActions}
      />

      {/* Rise the body in when the view, range or load state changes (not on
          first paint). Enter only: a mode="wait" exit hand-off stalled the
          Table view under load, so the old body unmounts at once. */}
      <AnimatePresence initial={false}>
        <motion.div
          key={loading ? "loading" : loadError ? "error" : `${view}:${rangeLabel}`}
          {...asProps(m.fadeUp)} exit={undefined}
        >
          {loading ? (
            <CalendarMonthSkeleton />
          ) : loadError ? (
            <LoadErrorBanner message={loadError} onRetry={retryLoad} />
          ) : view === "month" ? (
            <MonthView cursor={cursor} byDate={byDate} today={today} courses={courses} />
          ) : view === "week" ? (
            <WeekView cursor={cursor} byDate={byDate} today={today} courses={courses} />
          ) : view === "day" ? (
            <DayView cursor={cursor} byDate={byDate} courses={courses} />
          ) : (
            <AssignmentTable
              assignments={assignments}
              courses={courses}
              selected={selected}
              onSelectedChange={setSelected}
              onExport={exportCsv}
              onReload={load}
              googleConnected={googleConnected}
            />
          )}
        </motion.div>
      </AnimatePresence>
      </>)}

      <DocumentUploadModal
        open={uploadOpen}
        userId={userId}
        courses={courses}
        onClose={() => setUploadOpen(false)}
        onComplete={async (items) => {
          const hasSyllabus = items.some(it => it.category === "syllabus");
          await load();
          if (hasSyllabus) {
            setTimeout(load, SYLLABUS_RELOAD_DELAY_MS);
            toast.success("Syllabus processed — new assignments added.");
          }
        }}
      />

      <AnimatePresence>
        {googleEvents !== null && (
          <GoogleEventsModal
            key="google-events"
            events={googleEvents}
            onClose={() => setGoogleEvents(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// Load-failure state distinct from a legitimately empty calendar (#185).
// Mirrors the Gradebook course ErrorBanner: what went wrong + a retry.
function LoadErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className={styles.body}>
      <div role="alert" data-testid="calendar-load-error" className={styles.errorBanner}>
        <div>
          <div className={styles.errorTitle}>We couldn&apos;t load your calendar.</div>
          <div className={styles.errorMessage}>{message}</div>
        </div>
        <button
          type="button"
          className={`btn btn--primary ${styles.retry}`}
          data-testid="calendar-load-retry"
          onClick={onRetry}
        >
          Try again
        </button>
      </div>
    </div>
  );
}

function shift(setCursor: React.Dispatch<React.SetStateAction<Date>>, view: View, dir: -1 | 1) {
  setCursor(prev => {
    const d = new Date(prev);
    if (view === "month") d.setMonth(d.getMonth() + dir);
    else if (view === "week") d.setDate(d.getDate() + 7 * dir);
    else if (view === "day") d.setDate(d.getDate() + dir);
    return d;
  });
}

function formatRange(d: Date, view: View) {
  if (view === "month") return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  if (view === "day") return d.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  if (view === "week") {
    const start = startOfWeekMon(d);
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    return `${start.toLocaleDateString("en-US", { month: "short", day: "numeric" })} – ${end.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
  }
  return "All assignments";
}

function startOfWeekMon(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  const day = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - day);
  return x;
}

/** An assignment's dot: its course colour, else its type's. */
function dotStyle(a: Assignment, courseColor: Map<string, string | null | undefined>): React.CSSProperties {
  const color = TYPE_COLOR[a.assignment_type || "other"];
  const dot = a.course_id ? courseColor.get(a.course_id) || color : color;
  return { "--dot": dot } as React.CSSProperties;
}

function MonthView({ cursor, byDate, today, courses }: { cursor: Date; byDate: Map<string, Assignment[]>; today: Date; courses: EnrolledCourse[] }) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = startOfWeekMon(first);
  const cells: Date[] = Array.from({ length: MONTH_CELLS }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const courseColor = new Map(courses.map(c => [c.course_id, c.color]));
  return (
    <div className={styles.body}>
      <div className={styles.monthHead}>
        {weekdays.map(d => <div key={d} className={`label-micro ${styles.weekday}`}>{d}</div>)}
      </div>
      <div className={styles.monthGrid}>
        {cells.map((d, i) => {
          const key = dateKey(d);
          const items = byDate.get(key) || [];
          const inMonth = d.getMonth() === cursor.getMonth();
          const isToday = d.getTime() === today.getTime();
          const cls = [
            "card",
            styles.monthCell,
            inMonth ? "" : styles.outside,
            isToday ? styles.today : "",
          ].filter(Boolean).join(" ");
          return (
            <div key={i} className={cls}>
              <div className={styles.monthDate}>{d.getDate()}</div>
              {items.slice(0, MONTH_ITEMS_SHOWN).map(a => (
                <div key={a.id} className={styles.monthItem} title={a.title}>
                  <span aria-hidden className={styles.dot} style={dotStyle(a, courseColor)} />
                  <span className={styles.ellipsis}>{a.title}</span>
                </div>
              ))}
              {items.length > MONTH_ITEMS_SHOWN && (
                <div className={styles.more}>+{items.length - MONTH_ITEMS_SHOWN} more</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WeekView({ cursor, byDate, today, courses }: { cursor: Date; byDate: Map<string, Assignment[]>; today: Date; courses: EnrolledCourse[] }) {
  const start = startOfWeekMon(cursor);
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start); d.setDate(start.getDate() + i); return d;
  });
  const courseColor = new Map(courses.map(c => [c.course_id, c.color]));
  return (
    <div className={styles.body}>
      <div className={styles.weekGrid}>
        {days.map((d, i) => {
          const key = dateKey(d);
          const items = byDate.get(key) || [];
          const isToday = d.getTime() === today.getTime();
          return (
            <div key={i} className={`card ${styles.weekCell}${isToday ? ` ${styles.today}` : ""}`}>
              <div className={styles.weekHead}>
                <span className={`h-serif ${styles.weekNum}`}>{d.getDate()}</span>
                <span className="label-micro">{d.toLocaleDateString("en-US", { weekday: "short" })}</span>
              </div>
              {items.length === 0 && <div className={styles.weekEmpty}>—</div>}
              {items.map(a => (
                <div key={a.id} className={styles.weekItem}>
                  <span aria-hidden className={styles.dot} style={dotStyle(a, courseColor)} />
                  <div className={styles.minW0}>
                    <div className={styles.itemTitle}>{a.title}</div>
                    <div className={styles.itemCourse}>{a.course_code || a.course_name}</div>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DayView({ cursor, byDate, courses }: { cursor: Date; byDate: Map<string, Assignment[]>; courses: EnrolledCourse[] }) {
  const key = dateKey(cursor);
  const items = byDate.get(key) || [];
  const courseColor = new Map(courses.map(c => [c.course_id, c.color]));
  const m = useMotionPresets();
  return (
    <div className={`${styles.body} ${styles.dayBody}`}>
      <div className={`h-serif ${styles.dayTitle}`}>
        {cursor.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
      </div>
      {items.length === 0 && <div className={`card ${styles.dayEmpty}`}>Nothing scheduled.</div>}
      <motion.div variants={m.list.container} initial="hidden" animate="shown">
        {items.map(a => {
          const dl = dueLabel(a.due_date);
          return (
            <motion.div key={a.id} className={`card ${styles.dayItem}`} variants={m.list.item}>
              <span aria-hidden className={styles.dot} style={dotStyle(a, courseColor)} />
              <div className={styles.grow}>
                <div className={styles.dayItemHead}>
                  <strong>{a.title}</strong>
                  <span className={`chip ${dl.cls}`}>{dl.label}</span>
                </div>
                <div className={styles.dayMeta}>
                  {a.course_code || a.course_name || "—"} · {a.assignment_type || "task"}
                </div>
                {a.notes && <div className={styles.dayNotes}>{a.notes}</div>}
              </div>
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}

function AssignmentTable({
  assignments, courses, selected, onSelectedChange, onExport, onReload, googleConnected,
}: {
  assignments: Assignment[];
  courses: EnrolledCourse[];
  selected: Set<string>;
  onSelectedChange: (s: Set<string>) => void;
  onExport: () => void;
  onReload: () => void | Promise<void>;
  googleConnected: boolean;
}) {
  const toast = useToast();
  const { userId } = useUser();
  const [editing, setEditing] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<Partial<Assignment>>({});
  const [saving, setSaving] = React.useState(false);
  const [exporting, setExporting] = React.useState(false);
  const [deletingId, setDeletingId] = React.useState<string | null>(null);
  type SortKey = "due_date" | "title" | "course" | "type";
  const [sortKey, setSortKey] = React.useState<SortKey>("due_date");
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("asc");
  const m = useMotionPresets();

  const sorted = React.useMemo(() => {
    const copy = [...assignments];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "due_date") {
        // Undated rows sort last in both directions, so skip the asc/desc flip.
        if (!a.due_date || !b.due_date) return Number(!a.due_date) - Number(!b.due_date);
        cmp = a.due_date.localeCompare(b.due_date);
      } else if (sortKey === "title") cmp = (a.title || "").localeCompare(b.title || "");
      else if (sortKey === "course") cmp = (a.course_code || a.course_name || "").localeCompare(b.course_code || b.course_name || "");
      else if (sortKey === "type") cmp = (a.assignment_type || "").localeCompare(b.assignment_type || "");
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [assignments, sortKey, sortDir]);

  const toggleAll = () => {
    if (selected.size === assignments.length) onSelectedChange(new Set());
    else onSelectedChange(new Set(assignments.map(a => a.id)));
  };

  const toggleOne = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    onSelectedChange(next);
  };

  const removeOne = async (a: Assignment) => {
    if (!userId) return;
    if (!window.confirm(`Delete "${a.title}"?`)) return;
    setDeletingId(a.id);
    try {
      await deleteAssignment(a.id, userId);
      const next = new Set(selected);
      next.delete(a.id);
      onSelectedChange(next);
      toast.success("Assignment deleted.");
      await onReload();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't delete that. Try again."));
    } finally {
      setDeletingId(null);
    }
  };

  const bulkExport = async () => {
    if (!userId || selected.size === 0) {
      toast.warn("Select assignments first.");
      return;
    }
    setExporting(true);
    try {
      const res = await exportToGoogleCalendar(userId, Array.from(selected));
      toast.success(
        `Exported ${res.exported_count}${res.skipped_count ? ` (${res.skipped_count} skipped)` : ""}.`
      );
      await onReload();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't export that. Try again."));
    } finally {
      setExporting(false);
    }
  };

  const beginEdit = (a: Assignment) => {
    setEditing(a.id);
    setDraft({ title: a.title, course_id: a.course_id, due_date: a.due_date, assignment_type: a.assignment_type || "", notes: a.notes || "" });
  };
  const cancel = () => { setEditing(null); setDraft({}); };
  const saveEdit = async () => {
    if (!editing || !userId) return;
    setSaving(true);
    try {
      await updateAssignment(editing, userId, {
        title: draft.title,
        course_id: draft.course_id ?? "",
        // An empty date input means "no date": send null, never "" (invalid for a DATE column).
        due_date: draft.due_date ? draft.due_date.slice(0, 10) : null,
        assignment_type: draft.assignment_type || undefined,
        notes: draft.notes || undefined,
      });
      toast.success("Assignment updated.");
      await onReload();
      cancel();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't save that. Try again."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.body}>
      <div className={styles.toolbar}>
        <div className="label-micro">{selected.size} of {assignments.length} selected</div>
        <div className={styles.spacer} />
        <div className={styles.sortGroup}>
          <span className={`label-micro ${styles.sortLabel}`}>Sort</span>
          <div className={styles.sortSelect}>
            <CustomSelect
              ariaLabel="Sort"
              size="sm"
              value={sortKey}
              onChange={v => setSortKey(v as SortKey)}
              options={[
                { value: "due_date", label: "Due date" },
                { value: "title", label: "Title" },
                { value: "course", label: "Course" },
                { value: "type", label: "Type" },
              ]}
            />
          </div>
          <button
            className="btn btn--sm btn--ghost"
            onClick={() => setSortDir(d => (d === "asc" ? "desc" : "asc"))}
            title={sortDir === "asc" ? "Ascending" : "Descending"}
            aria-label="Toggle sort direction"
          >
            {sortDir === "asc" ? "↑" : "↓"}
          </button>
        </div>
        <button className="btn btn--sm" onClick={onExport}>
          <Icon name="doc" size={12} /> Export CSV
        </button>
        {googleConnected && (
          <button
            className="btn btn--sm"
            onClick={bulkExport}
            disabled={exporting || selected.size === 0}
            title={selected.size === 0 ? "Select assignments first" : "Push selected assignments to Google Calendar"}
          >
            <Icon name="cal" size={12} /> {exporting ? "Exporting…" : "Export to Google"}
          </button>
        )}
      </div>
      <div className={`card ${styles.tableCard}`}>
        <table className={styles.table}>
          <thead>
            <tr className={styles.headRow}>
              <th className={styles.colCheck}>
                <input type="checkbox" aria-label="Select all assignments" checked={selected.size === assignments.length && assignments.length > 0} onChange={toggleAll} />
              </th>
              <th>Title</th>
              <th>Course</th>
              <th>Type</th>
              <th>Due</th>
              <th className={styles.colActions}></th>
            </tr>
          </thead>
          {/* Rows arrive with the list stagger: on the view swap and when a
              reload adds one; a re-sort keeps its rows (stable keys). */}
          <motion.tbody variants={m.list.container} initial="hidden" animate="shown">
            {sorted.map(a => {
              const editingThis = editing === a.id;
              return (
                <motion.tr key={a.id} className={styles.row} variants={m.list.item}>
                  <td>
                    <input type="checkbox" aria-label={`Select ${a.title}`} checked={selected.has(a.id)} onChange={() => toggleOne(a.id)} />
                  </td>
                  <td>
                    {editingThis ? (
                      <input
                        value={draft.title || ""}
                        onChange={e => setDraft(d => ({ ...d, title: e.target.value }))}
                        className={`${styles.input} ${styles.inputWide}`}
                      />
                    ) : (
                      <strong>{a.title}</strong>
                    )}
                  </td>
                  <td>
                    {editingThis ? (
                      <CustomSelect
                        ariaLabel="Course"
                        size="sm"
                        value={draft.course_id || ""}
                        onChange={v => setDraft(d => ({ ...d, course_id: v }))}
                        options={courses.map(c => ({ value: c.course_id, label: c.course_code || c.course_name }))}
                        placeholder="—"
                      />
                    ) : (
                      a.course_code || a.course_name || "—"
                    )}
                  </td>
                  <td>
                    {editingThis ? (
                      <CustomSelect
                        ariaLabel="Type"
                        size="sm"
                        value={draft.assignment_type || ""}
                        onChange={v => setDraft(d => ({ ...d, assignment_type: v }))}
                        options={TYPE_OPTIONS}
                        placeholder="—"
                      />
                    ) : (
                      <span className={styles.capitalize}>{a.assignment_type || "—"}</span>
                    )}
                  </td>
                  <td>
                    {editingThis ? (
                      <input
                        type="date"
                        value={(draft.due_date || "").slice(0, 10)}
                        onChange={e => setDraft(d => ({ ...d, due_date: e.target.value }))}
                        className={styles.input}
                      />
                    ) : (
                      a.due_date || "No date"
                    )}
                  </td>
                  <td className={styles.actions}>
                    {editingThis ? (
                      <>
                        <button className="btn btn--sm btn--primary" onClick={saveEdit} disabled={saving}>
                          {saving ? "Saving…" : "Save"}
                        </button>
                        <button className="btn btn--sm btn--ghost" onClick={cancel} disabled={saving}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button className="btn btn--sm btn--ghost" onClick={() => beginEdit(a)} title="Edit">
                          <Icon name="pencil" size={11} />
                        </button>
                        <button
                          className={`btn btn--sm btn--ghost ${styles.danger}`}
                          onClick={() => removeOne(a)}
                          disabled={deletingId === a.id}
                          title="Delete"
                        >
                          {deletingId === a.id ? "…" : <Icon name="x" size={11} />}
                        </button>
                      </>
                    )}
                  </td>
                </motion.tr>
              );
            })}
            {assignments.length === 0 && (
              <tr>
                <td colSpan={6} className={styles.emptyRow}>
                  No assignments yet.
                </td>
              </tr>
            )}
          </motion.tbody>
        </table>
      </div>
    </div>
  );
}
