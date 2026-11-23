"use client";
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion, MotionGlobalConfig, useReducedMotion } from "framer-motion";
import { IS_TEST_MODE } from "@/lib/testMode";

// Deterministic DOM for browser tests (#383): framer-motion's own test
// seam jumps every animation straight to its final keyframe. No-op in
// production builds (flag inlined to false at build time). Same gate as
// Study.tsx / HowItWorks.tsx — the flag is module-side-effect scoped, so
// every framer-motion consumer must set it for direct-navigation runs.
if (IS_TEST_MODE) MotionGlobalConfig.skipAnimations = true;
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { GoogleCalendarActions, GoogleCalendarStatus } from "./CalendarGoogleControls";
import { GoogleCalendarEvents } from "../GoogleCalendarEvents";
import { CalendarCourseFilters, CalendarEventDialog, type CalendarEventDetail } from "./CalendarEventControls";
import { dateKey, startOfWeekMon, MonthView, WeekView, DayView } from "./CalendarGrid";
import styles from "./CalendarEvents.module.css";
import { calendarRange, googleEventsByDate, linkedGoogleEvents } from "@/lib/googleCalendar";
import { Toggle } from "@/components/ui";
import { CustomSelect } from "../CustomSelect";
import { useIsNavHidden } from "@/lib/useNavHidden";
import { CalendarMonthSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import {
  getAllAssignments,
  getCourses,
  getCalendarStatus,
  disconnectCalendar,
  connectCalendarEvents,
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

type View = "month" | "week" | "day" | "table";

const TYPE_OPTIONS = [
  { value: "homework", label: "Homework" },
  { value: "exam", label: "Exam" },
  { value: "quiz", label: "Quiz" },
  { value: "reading", label: "Reading" },
  { value: "project", label: "Project" },
  { value: "other", label: "Other" },
];

export function Calendar() {
  const router = useRouter();
  const isNavHidden = useIsNavHidden();
  const search = useSearchParams();
  const toast = useToast();
  const { userId, userReady } = useUser();
  // Disable the view-swap fade/slide for users who ask for reduced motion.
  // The global CSS reduced-motion rule only neutralises CSS transitions;
  // framer's JS-driven animations need this explicit opt-out.
  const prefersReduced = useReducedMotion();

  const [assignments, setAssignments] = React.useState<Assignment[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [hiddenCourses, setHiddenCourses] = React.useState<Set<string>>(new Set());
  const [eventDetail, setEventDetail] = React.useState<CalendarEventDetail | null>(null);
  const [view, setView] = React.useState<View>("month");
  const [cursor, setCursor] = React.useState(() => new Date(now()));
  const [googleConnected, setGoogleConnected] = React.useState(false);
  const [googleEventsEnabled, setGoogleEventsEnabled] = React.useState(false);
  const [changingGoogleEvents, setChangingGoogleEvents] = React.useState(false);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [googleEvents, setGoogleEvents] = React.useState<{ userId: string; range: string; events: GoogleEvent[] } | null>(null);
  const [googleError, setGoogleError] = React.useState<string | null>(null);
  const [googleRefresh, setGoogleRefresh] = React.useState(0);
  const [importingGoogle, setImportingGoogle] = React.useState(false);
  const [exportingGoogle, setExportingGoogle] = React.useState(false);
  const exportInFlight = React.useRef(false);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  // True once a load has succeeded — gates HOW a later failure surfaces.
  // `load` doubles as the background reload (AssignmentTable's onReload,
  // the OAuth-reconnect effect, upload onComplete), and a reload failure
  // must never blank an already-populated calendar behind the full-page
  // banner (PR #463 review; same `error && !data` gating as the Gradebook
  // screen's ErrorBanner).
  const hasLoadedRef = React.useRef(false);
  const eventsPreferenceGeneration = React.useRef(0);

  const load = React.useCallback(async () => {
    if (!userId) return;
    const preferenceGeneration = eventsPreferenceGeneration.current;
    try {
      const [a, c, s] = await Promise.all([
        getAllAssignments(userId),
        getCourses(userId),
        getCalendarStatus(userId).catch(() => ({ connected: false, events_enabled: false })),
      ]);
      setAssignments(a.assignments || []);
      setCourses(c.courses || []);
      setGoogleConnected(Boolean(s.connected));
      if (preferenceGeneration === eventsPreferenceGeneration.current) {
        setGoogleEventsEnabled(Boolean(s.connected && (s.events_enabled ?? true)));
      }
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

  const handledCallback = React.useRef<string | null>(null);
  // Consume callback feedback once, including under Strict Mode effect replay.
  React.useEffect(() => {
    const error = search.get(CALENDAR_ERROR_PARAM);
    const connected = search.get("connected") === "true";
    if (!error && !connected) {
      handledCallback.current = null;
      return;
    }
    const callback = search.toString();
    if (handledCallback.current === callback) return;
    handledCallback.current = callback;
    if (error) {
      toast.error(calendarConnectError(error));
    } else {
      toast.success("Google Calendar connected");
      void load();
    }
    const next = new URLSearchParams(search.toString());
    next.delete("connected");
    next.delete(CALENDAR_ERROR_PARAM);
    const qs = next.toString();
    router.replace(qs ? `/calendar?${qs}` : "/calendar");
  }, [search, router, toast, load]);

  const today = React.useMemo(() => {
    const d = new Date(now()); d.setHours(0, 0, 0, 0); return d;
  }, []);

  const visibleAssignments = React.useMemo(
    () => assignments.filter(a => !hiddenCourses.has(a.course_id || "")),
    [assignments, hiddenCourses],
  );
  const byDate = React.useMemo(() => {
    const map = new Map<string, Assignment[]>();
    for (const a of visibleAssignments) {
      // Gradebook/Gradescope items may have no due date; they only show in the list view.
      if (!a.due_date) continue;
      const k = a.due_date.slice(0, 10);
      const arr = map.get(k) || [];
      arr.push(a);
      map.set(k, arr);
    }
    return map;
  }, [visibleAssignments]);

  const toggleCourse = (courseId: string) => {
    const next = new Set(hiddenCourses);
    if (!next.delete(courseId)) {
      next.add(courseId);
      const hiddenIds = new Set(assignments.filter(a => (a.course_id || "") === courseId).map(a => a.id));
      setSelected(previous => new Set([...previous].filter(id => !hiddenIds.has(id))));
    }
    setHiddenCourses(next);
  };

  const connect = () => {
    if (!userId) return;
    window.location.href = calendarAuthUrl(userId);
  };

  const exportGoogle = async (ids?: string[]) => {
    if (!userId || exportInFlight.current) return;
    exportInFlight.current = true;
    setExportingGoogle(true);
    try {
      if (ids) {
        const res = await exportToGoogleCalendar(userId, ids);
        toast.success(`Exported ${res.exported_count}${res.skipped_count ? ` (${res.skipped_count} skipped)` : ""}.`);
      } else {
        const res = await syncCalendar(userId);
        toast.success(`Exported ${res.synced_count} new event${res.synced_count === 1 ? "" : "s"} to Google.`);
      }
      await load();
    } catch (err) {
      toast.error(`Export failed: ${humanizeError(err, "Please try again.")}`);
    } finally {
      exportInFlight.current = false;
      setExportingGoogle(false);
    }
  };

  const range = React.useMemo(() => calendarRange(cursor, view), [cursor, view]);
  const rangeKey = `${range.start}/${range.end}`;
  React.useEffect(() => {
    if (!googleConnected || !googleEventsEnabled || !userId) return;
    let active = true;
    setImportingGoogle(true);
    setGoogleError(null);
    void importGoogleEvents(userId, 60, range).then(result => {
      if (active) setGoogleEvents({ userId, range: rangeKey, events: result.events || [] });
    }).catch(err => {
      if (active) setGoogleError(humanizeError(err, "Couldn't load Google events. Refresh or reconnect Google."));
    }).finally(() => { if (active) setImportingGoogle(false); });
    return () => { active = false; };
  }, [googleConnected, googleEventsEnabled, userId, range, rangeKey, googleRefresh]);
  const linkedEvents = React.useMemo(() => linkedGoogleEvents(
    googleConnected && googleEventsEnabled && googleEvents?.userId === userId && googleEvents.range === rangeKey ? googleEvents.events : [], assignments,
  ), [googleConnected, googleEventsEnabled, googleEvents, rangeKey, assignments, userId]);
  const googleByDate = React.useMemo(() => googleEventsByDate(linkedEvents, range), [linkedEvents, range]);

  const toggleGoogleEvents = async () => {
    if (changingGoogleEvents) return;
    eventsPreferenceGeneration.current += 1;
    setChangingGoogleEvents(true);
    try {
      if (googleEventsEnabled) await disconnectCalendar(userId);
      else await connectCalendarEvents(userId);
      setGoogleEventsEnabled(!googleEventsEnabled);
      setGoogleEvents(null);
      setGoogleError(null);
      toast.success(googleEventsEnabled ? "Google events disconnected. Your Google account stays connected." : "Google events reconnected.");
    } catch (err) {
      toast.error(`Couldn't update Google events: ${humanizeError(err, "Please try again.")}`);
    } finally {
      eventsPreferenceGeneration.current += 1;
      setChangingGoogleEvents(false);
    }
  };

  const exportCsv = () => {
    const ids = selected.size ? visibleAssignments.filter(a => selected.has(a.id)) : visibleAssignments;
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

  const refreshGoogleEvents = () => setGoogleRefresh(n => n + 1);

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
          <button data-testid="calendar-prev" className="btn btn--sm" onClick={() => shift(setCursor, view, -1)}>
            <Icon name="chevron-left" size={12} /> Prev
          </button>
          <button data-testid="calendar-today" className="btn btn--sm" onClick={() => setCursor(new Date(now()))}>Today</button>
          <button data-testid="calendar-next" className="btn btn--sm" onClick={() => shift(setCursor, view, 1)}>
            Next <Icon name="chev" size={12} />
          </button>
        </>
      )}
      {!isNavHidden("/library") && <button data-testid="calendar-import-syllabus" className="btn btn--sm" onClick={() => router.push("/library?upload=syllabus")}>
        <Icon name="upload" size={12} /> Import syllabus
      </button>}
      <GoogleCalendarActions
        connected={googleConnected}
        eventsEnabled={googleEventsEnabled}
        exporting={exportingGoogle}
        updating={changingGoogleEvents}
        importing={importingGoogle}
        calendarUnavailable={loading || Boolean(loadError)}
        onConnect={connect}
        onExport={() => void exportGoogle()}
        onRefresh={refreshGoogleEvents}
        onToggle={toggleGoogleEvents}
      />
    </>
  );

  const rangeLabel = formatRange(cursor, view);
  const showAssignment = (event: Assignment) => setEventDetail({ kind: "assignment", event });
  const showGoogleEvent = (event: GoogleEvent) => setEventDetail({ kind: "google", event });
  const gridProps = { cursor, byDate, googleByDate, courses, onAssignment: showAssignment, onGoogleEvent: showGoogleEvent };

  return (
    <div>
      <TopBar
        title="Calendar"
        subtitle={`${rangeLabel} · ${visibleAssignments.length} assignment${visibleAssignments.length === 1 ? "" : "s"}`}
        actions={topActions}
      />

      <CalendarCourseFilters
        courses={courses} assignments={assignments} hidden={hiddenCourses}
        onToggle={toggleCourse} onReset={() => setHiddenCourses(new Set())}
      />

      <GoogleCalendarStatus
        connected={googleConnected}
        eventsEnabled={googleEventsEnabled}
        importing={importingGoogle}
        error={googleError}
        eventCount={linkedEvents.length}
        isYearView={view === "table"}
        onConnect={connect}
        onRefresh={refreshGoogleEvents}
      />

      {/* Crossfade/slide the calendar body when the view (or load state)
          changes, keyed on that state. Mirrors Study.tsx's mode="wait"
          pattern so the swap settles instead of snapping (#295). */}
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={loading ? "loading" : loadError ? "error" : view}
          initial={prefersReduced ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={prefersReduced ? { opacity: 1 } : { opacity: 0, y: -8 }}
          transition={{ duration: prefersReduced ? 0 : 0.22, ease: [0.2, 0.85, 0.35, 1] }}
        >
          {loading ? (
            <CalendarMonthSkeleton />
          ) : loadError ? (
            <LoadErrorBanner message={loadError} onRetry={retryLoad} />
          ) : view === "month" ? (
            <MonthView {...gridProps} today={today} onShowDay={date => { setCursor(date); setView("day"); }} />
          ) : view === "week" ? (
            <WeekView {...gridProps} today={today} />
          ) : view === "day" ? (
            <DayView {...gridProps} />
          ) : (
            <AssignmentTable
              assignments={visibleAssignments}
              selected={selected}
              onSelectedChange={setSelected}
              onExport={exportCsv}
              onReload={load}
              googleConnected={googleConnected}
              exporting={exportingGoogle || changingGoogleEvents}
              onGoogleExport={exportGoogle}
              onAssignment={showAssignment}
            />
          )}
        </motion.div>
      </AnimatePresence>

      {view === "table" && googleConnected && googleEventsEnabled && (
        <section aria-label="Linked Google events" style={{ padding: "20px 32px" }}>
          <h2 className="h-serif">Google events · {cursor.getFullYear()}</h2>
          <GoogleCalendarEvents events={linkedEvents} onSelect={showGoogleEvent} />
        </section>
      )}
      <CalendarEventDialog detail={eventDetail} onClose={() => setEventDetail(null)} />
    </div>
  );
}

// Load-failure state distinct from a legitimately empty calendar (#185).
// Mirrors the Gradebook course ErrorBanner: what went wrong + a retry.
function LoadErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{ padding: "20px 32px" }}>
      <div
        role="alert"
        data-testid="calendar-load-error"
        style={{
          padding: "20px 24px",
          borderRadius: "var(--r-md)",
          background: "var(--err-soft)",
          border: "1px solid color-mix(in oklab, var(--err) 20%, transparent)",
          display: "flex",
          gap: 16,
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontWeight: 600, color: "var(--err)", marginBottom: 4 }}>
            We couldn&apos;t load your calendar.
          </div>
          <div style={{ fontSize: 13, color: "var(--text-dim)" }}>{message}</div>
        </div>
        <button
          type="button"
          className="btn btn--primary"
          data-testid="calendar-load-retry"
          onClick={onRetry}
          style={{ padding: "8px 16px" }}
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
    if (view === "month") {
      const day = d.getDate();
      d.setDate(1);
      d.setMonth(d.getMonth() + dir);
      const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
      d.setDate(Math.min(day, lastDay));
    }
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

function AssignmentTable({
  assignments, selected, onSelectedChange, onExport, onReload, googleConnected, exporting, onGoogleExport, onAssignment,
}: {
  assignments: Assignment[];
  selected: Set<string>;
  onSelectedChange: (s: Set<string>) => void;
  onExport: () => void;
  onReload: () => void | Promise<void>;
  googleConnected: boolean;
  exporting: boolean;
  onGoogleExport: (ids: string[]) => Promise<void>;
  onAssignment: (assignment: Assignment) => void;
}) {
  const toast = useToast();
  const { userId } = useUser();
  const [editing, setEditing] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<Partial<Assignment>>({});
  const [saving, setSaving] = React.useState(false);
  const [deletingId, setDeletingId] = React.useState<string | null>(null);
  type SortKey = "due_date" | "title" | "course" | "type";
  const [sortKey, setSortKey] = React.useState<SortKey>("due_date");
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("asc");

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
    await onGoogleExport(Array.from(selected));
  };

  const beginEdit = (a: Assignment) => {
    setEditing(a.id);
    setDraft({ title: a.title, due_date: a.due_date, assignment_type: a.assignment_type || "" });
  };
  const cancel = () => { setEditing(null); setDraft({}); };
  const saveEdit = async () => {
    if (!editing || !userId) return;
    setSaving(true);
    try {
      await updateAssignment(editing, userId, {
        title: draft.title,
        // An empty date input means "no date": send null, never "" (invalid for a DATE column).
        due_date: draft.due_date ? draft.due_date.slice(0, 10) : null,
        assignment_type: draft.assignment_type || undefined,
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
    <div style={{ padding: "20px 32px" }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div className="label-micro">{selected.size} of {assignments.length} selected</div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="label-micro" style={{ fontSize: 10 }}>Sort</span>
          <div style={{ minWidth: 140 }}>
            <CustomSelect
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
            data-testid="calendar-sort-direction"
            className="btn btn--sm btn--ghost"
            onClick={() => setSortDir(d => (d === "asc" ? "desc" : "asc"))}
            title={sortDir === "asc" ? "Ascending" : "Descending"}
            aria-label="Toggle sort direction"
          >
            {sortDir === "asc" ? "↑" : "↓"}
          </button>
        </div>
        <button data-testid="calendar-export-csv" className="btn btn--sm" onClick={onExport}>
          <Icon name="doc" size={12} /> Export CSV
        </button>
        {googleConnected && (
          <button
            data-testid="calendar-export-selected-google"
            className="btn btn--sm"
            onClick={bulkExport}
            disabled={exporting || selected.size === 0}
            title={selected.size === 0 ? "Select assignments first" : "Push selected assignments to Google Calendar"}
          >
            <Icon name="cal" size={12} /> {exporting ? "Exporting…" : "Export to Google"}
          </button>
        )}
      </div>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)", textAlign: "left" }}>
              <th style={{ padding: 10, width: 32 }}>
                <input data-testid="calendar-select-all" type="checkbox" aria-label="Select all assignments" checked={selected.size === assignments.length && assignments.length > 0} onChange={toggleAll} />
              </th>
              <th style={{ padding: 10 }}>Title</th>
              <th style={{ padding: 10 }}>Course</th>
              <th style={{ padding: 10 }}>Type</th>
              <th style={{ padding: 10 }}>Due</th>
              <th style={{ padding: 10, width: 90 }}></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((a, i) => {
              const editingThis = editing === a.id;
              return (
                <tr key={a.id} style={{ borderTop: i === 0 ? "none" : "1px solid var(--border)" }}>
                  <td style={{ padding: 10 }}>
                    <input data-testid={`calendar-select-${a.id}`} type="checkbox" aria-label={`Select ${a.title}`} checked={selected.has(a.id)} onChange={() => toggleOne(a.id)} />
                  </td>
                  <td style={{ padding: 10 }}>
                    {editingThis ? (
                      <input
                        data-testid={`calendar-title-${a.id}`}
                        value={draft.title || ""}
                        onChange={e => setDraft(d => ({ ...d, title: e.target.value }))}
                        style={{ padding: "4px 6px", border: "1px solid var(--border)", borderRadius: "var(--r-xs)", fontSize: 12, width: "100%" }}
                      />
                    ) : (
                      <button type="button" data-testid={`calendar-details-${a.id}`} className={styles.eventButton} onClick={() => onAssignment(a)}><strong>{a.title}</strong></button>
                    )}
                  </td>
                  <td style={{ padding: 10 }}>
                    <span title="Course is tied to this assignment's enrollment.">
                      {a.course_code || a.course_name || "—"}
                    </span>
                  </td>
                  <td style={{ padding: 10 }}>
                    {editingThis ? (
                      <CustomSelect
                        size="sm"
                        value={draft.assignment_type || ""}
                        onChange={v => setDraft(d => ({ ...d, assignment_type: v }))}
                        options={TYPE_OPTIONS}
                        placeholder="—"
                      />
                    ) : (
                      <span style={{ textTransform: "capitalize" }}>{a.assignment_type || "—"}</span>
                    )}
                  </td>
                  <td style={{ padding: 10 }}>
                    {editingThis ? (
                      <input
                        data-testid={`calendar-date-${a.id}`}
                        type="date"
                        value={(draft.due_date || "").slice(0, 10)}
                        onChange={e => setDraft(d => ({ ...d, due_date: e.target.value }))}
                        style={{ padding: "4px 6px", border: "1px solid var(--border)", borderRadius: "var(--r-xs)", fontSize: 12 }}
                      />
                    ) : (
                      a.due_date || "No date"
                    )}
                  </td>
                  <td style={{ padding: 10, display: "flex", gap: 4 }}>
                    {editingThis ? (
                      <>
                        <button data-testid={`calendar-save-${a.id}`} className="btn btn--sm btn--primary" onClick={saveEdit} disabled={saving}>
                          {saving ? "Saving…" : "Save"}
                        </button>
                        <button data-testid={`calendar-cancel-${a.id}`} className="btn btn--sm btn--ghost" onClick={cancel} disabled={saving}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button data-testid={`calendar-edit-${a.id}`} className="btn btn--sm btn--ghost" onClick={() => beginEdit(a)} title="Edit">
                          <Icon name="pencil" size={11} />
                        </button>
                        <button
                          data-testid={`calendar-delete-${a.id}`}
                          className="btn btn--sm btn--ghost"
                          onClick={() => removeOne(a)}
                          disabled={deletingId === a.id}
                          title="Delete"
                          style={{ color: "var(--err)" }}
                        >
                          {deletingId === a.id ? "…" : <Icon name="x" size={11} />}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
            {assignments.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
                  No assignments yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
