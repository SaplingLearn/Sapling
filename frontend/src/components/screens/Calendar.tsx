"use client";
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Pill } from "../Pill";
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

type View = "month" | "week" | "day" | "table";

const TYPE_COLOR: Record<string, string> = {
  exam: "var(--c-rust)",
  project: "var(--c-teal)",
  homework: "var(--c-sage)",
  quiz: "var(--warn)",
  reading: "var(--c-plum)",
  other: "var(--text-muted)",
};

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

function dueLabel(date: string) {
  const now = Date.now();
  const due = new Date(date).getTime();
  const diffMs = due - now;
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

  const [assignments, setAssignments] = React.useState<Assignment[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [view, setView] = React.useState<View>("month");
  const [cursor, setCursor] = React.useState(new Date());
  const [googleConnected, setGoogleConnected] = React.useState(false);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [googleEvents, setGoogleEvents] = React.useState<GoogleEvent[] | null>(null);
  const [importingGoogle, setImportingGoogle] = React.useState(false);
  const [loading, setLoading] = React.useState(true);

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
    } catch (err) {
      console.error("calendar load failed", err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

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

  const today = React.useMemo(() => {
    const d = new Date(); d.setHours(0, 0, 0, 0); return d;
  }, []);

  const byDate = React.useMemo(() => {
    const map = new Map<string, Assignment[]>();
    for (const a of assignments) {
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
      toast.error(`Sync failed: ${String(err)}`);
    }
  };

  const doImport = async () => {
    setImportingGoogle(true);
    try {
      const res = await importGoogleEvents(userId, 60);
      setGoogleEvents(res.events || []);
    } catch (err) {
      toast.error(`Import failed: ${String(err)}`);
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
      toast.error(`Disconnect failed: ${String(err)}`);
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
      ...ids.map(a => [a.title, a.course_code || a.course_name || "", a.assignment_type || "", a.due_date, a.notes || ""]),
    ];
    const csv = rows.map(r => r.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `assignments-${dateKey(new Date())}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${ids.length} row${ids.length === 1 ? "" : "s"}.`);
  };

  const topActions = (
    <>
      <div style={{ display: "flex", border: "1px solid var(--border)", borderRadius: "var(--r-sm)", overflow: "hidden" }}>
        {(["month", "week", "day", "table"] as View[]).map(v => (
          <button
            key={v}
            onClick={() => setView(v)}
            style={{
              padding: "5px 10px", fontSize: 11,
              background: view === v ? "var(--accent-soft)" : "transparent",
              color: view === v ? "var(--accent)" : "var(--text-dim)",
              textTransform: "capitalize",
            }}
          >
            {v}
          </button>
        ))}
      </div>
      {view !== "table" && (
        <>
          <button className="btn btn--sm" onClick={() => shift(setCursor, view, -1)}>
            <Icon name="chev" size={12} /> Prev
          </button>
          <button className="btn btn--sm" onClick={() => setCursor(new Date())}>Today</button>
          <button className="btn btn--sm" onClick={() => shift(setCursor, view, 1)}>
            Next <Icon name="chev" size={12} />
          </button>
        </>
      )}
      <button className="btn btn--sm" onClick={() => setUploadOpen(true)}>
        <Icon name="up" size={12} /> Import syllabus
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
            className="btn btn--sm"
            onClick={disconnectConfirm.trigger}
            style={disconnectConfirm.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
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
    <div>
      <TopBar
        title="Calendar"
        subtitle={`${rangeLabel} · ${assignments.length} assignment${assignments.length === 1 ? "" : "s"}`}
        actions={topActions}
      />

      {loading && <CalendarMonthSkeleton />}
      {!loading && view === "month" && <MonthView cursor={cursor} byDate={byDate} today={today} courses={courses} />}
      {!loading && view === "week" && <WeekView cursor={cursor} byDate={byDate} today={today} courses={courses} />}
      {!loading && view === "day" && <DayView cursor={cursor} byDate={byDate} courses={courses} />}
      {!loading && view === "table" && (
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

      <DocumentUploadModal
        open={uploadOpen}
        userId={userId}
        courses={courses}
        onClose={() => setUploadOpen(false)}
        onComplete={async (items) => {
          const hasSyllabus = items.some(it => it.category === "syllabus");
          await load();
          if (hasSyllabus) {
            setTimeout(load, 1500);
            toast.success("Syllabus processed — new assignments added.");
          }
        }}
      />

      {googleEvents !== null && (
        <GoogleEventsModal
          events={googleEvents}
          onClose={() => setGoogleEvents(null)}
        />
      )}
    </div>
  );
}

function GoogleEventsModal({
  events, onClose,
}: {
  events: GoogleEvent[];
  onClose: () => void;
}) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 120,
        background: "rgba(19,38,16,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--bg)", borderRadius: "var(--r-lg)",
          border: "1px solid var(--border)", maxWidth: 640, width: "100%",
          maxHeight: "82vh", overflow: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--border)", position: "sticky", top: 0, background: "var(--bg)" }}>
          <div className="label-micro">Upcoming Google Calendar events</div>
          <button className="btn btn--sm btn--ghost" onClick={onClose} aria-label="Close">
            <Icon name="x" size={12} /> Close
          </button>
        </div>
        <div style={{ padding: 20 }}>
          {events.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: 28 }}>
              No upcoming events in the next 60 days.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {events.map(e => (
                <div key={e.google_event_id} className="card" style={{ padding: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10 }}>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{e.title}</div>
                    <span className="chip" style={{ fontSize: 10 }}>
                      {e.all_day ? "All day" : e.start_datetime?.slice(11, 16) || ""}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
                    {e.start_date} {e.end_date && e.end_date !== e.start_date ? `→ ${e.end_date}` : ""}
                    {e.location ? ` · ${e.location}` : ""}
                  </div>
                  {e.description && (
                    <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 6, lineHeight: 1.5 }}>
                      {e.description.length > 140 ? e.description.slice(0, 140) + "…" : e.description}
                    </div>
                  )}
                  {e.html_link && (
                    <a
                      href={e.html_link}
                      target="_blank"
                      rel="noreferrer"
                      style={{ fontSize: 11, color: "var(--accent)", marginTop: 6, display: "inline-block" }}
                    >
                      Open in Google Calendar →
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
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

function MonthView({ cursor, byDate, today, courses }: { cursor: Date; byDate: Map<string, Assignment[]>; today: Date; courses: EnrolledCourse[] }) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = startOfWeekMon(first);
  const cells: Date[] = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const courseColor = new Map(courses.map(c => [c.course_id, c.color]));
  return (
    <div style={{ padding: "20px 32px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4, marginBottom: 4 }}>
        {weekdays.map(d => <div key={d} className="label-micro" style={{ padding: 6 }}>{d}</div>)}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4 }}>
        {cells.map((d, i) => {
          const key = dateKey(d);
          const items = byDate.get(key) || [];
          const inMonth = d.getMonth() === cursor.getMonth();
          const isToday = d.getTime() === today.getTime();
          return (
            <div
              key={i}
              className="card"
              style={{
                padding: 8, minHeight: 96, display: "flex", flexDirection: "column", gap: 4,
                opacity: inMonth ? 1 : 0.45,
                background: isToday ? "var(--accent-soft)" : "var(--bg-panel)",
                borderColor: isToday ? "var(--accent-border)" : "var(--border)",
              }}
            >
              <div style={{ fontSize: 11, fontWeight: 600, color: isToday ? "var(--accent)" : "var(--text-dim)" }}>
                {d.getDate()}
              </div>
              {items.slice(0, 3).map(a => {
                const color = TYPE_COLOR[a.assignment_type || "other"];
                const dotColor = a.course_id ? courseColor.get(a.course_id) || color : color;
                return (
                  <div
                    key={a.id}
                    style={{
                      fontSize: 10, padding: "3px 6px", borderRadius: "var(--r-xs)",
                      background: "transparent", color: "var(--text)",
                      display: "flex", alignItems: "center", gap: 5,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}
                    title={a.title}
                  >
                    <span aria-hidden style={{
                      width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0,
                    }} />
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{a.title}</span>
                  </div>
                );
              })}
              {items.length > 3 && (
                <div style={{ fontSize: 10, color: "var(--text-muted)" }}>+{items.length - 3} more</div>
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
    <div style={{ padding: "20px 32px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 8 }}>
        {days.map((d, i) => {
          const key = dateKey(d);
          const items = byDate.get(key) || [];
          const isToday = d.getTime() === today.getTime();
          return (
            <div
              key={i}
              className="card"
              style={{
                padding: 10, minHeight: 200,
                background: isToday ? "var(--accent-soft)" : "var(--bg-panel)",
                borderColor: isToday ? "var(--accent-border)" : "var(--border)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                <span className="h-serif" style={{ fontSize: 20 }}>{d.getDate()}</span>
                <span className="label-micro">{d.toLocaleDateString("en-US", { weekday: "short" })}</span>
              </div>
              {items.length === 0 && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>—</div>}
              {items.map(a => {
                const color = TYPE_COLOR[a.assignment_type || "other"];
                const dotColor = a.course_id ? courseColor.get(a.course_id) || color : color;
                return (
                  <div
                    key={a.id}
                    style={{
                      fontSize: 11, padding: "6px 0", marginBottom: 6,
                      display: "flex", gap: 8, alignItems: "flex-start",
                    }}
                  >
                    <span aria-hidden style={{
                      width: 6, height: 6, borderRadius: "50%",
                      background: dotColor, marginTop: 5, flexShrink: 0,
                    }} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 600, color: "var(--text)" }}>{a.title}</div>
                      <div style={{ color: "var(--text-muted)", fontSize: 10 }}>
                        {a.course_code || a.course_name}
                      </div>
                    </div>
                  </div>
                );
              })}
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
  return (
    <div style={{ padding: "20px 32px", maxWidth: 720 }}>
      <div className="h-serif" style={{ fontSize: 24, fontWeight: 500, marginBottom: 16 }}>
        {cursor.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
      </div>
      {items.length === 0 && (
        <div className="card" style={{ padding: "var(--pad-lg)", textAlign: "center", color: "var(--text-muted)" }}>
          Nothing scheduled.
        </div>
      )}
      {items.map(a => {
        const color = TYPE_COLOR[a.assignment_type || "other"];
        const dotColor = a.course_id ? courseColor.get(a.course_id) || color : color;
        const dl = dueLabel(a.due_date);
        return (
          <div key={a.id} className="card" style={{ padding: "var(--pad-lg)", marginBottom: 10, display: "flex", gap: 14, alignItems: "flex-start" }}>
            <span aria-hidden style={{
              width: 8, height: 8, borderRadius: "50%",
              background: dotColor, marginTop: 8, flexShrink: 0,
            }} />
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <strong>{a.title}</strong>
                <span className={`chip ${dl.cls}`}>{dl.label}</span>
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {a.course_code || a.course_name || "—"} · {a.assignment_type || "task"}
              </div>
              {a.notes && <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 6 }}>{a.notes}</div>}
            </div>
          </div>
        );
      })}
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

  const sorted = React.useMemo(() => {
    const copy = [...assignments];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "due_date") cmp = (a.due_date || "").localeCompare(b.due_date || "");
      else if (sortKey === "title") cmp = (a.title || "").localeCompare(b.title || "");
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
      toast.error(`Delete failed: ${String(err)}`);
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
      toast.error(`Export failed: ${String(err)}`);
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
        due_date: (draft.due_date || "").slice(0, 10),
        assignment_type: draft.assignment_type || undefined,
        notes: draft.notes || undefined,
      });
      toast.success("Assignment updated.");
      await onReload();
      cancel();
    } catch (err) {
      toast.error(`Save failed: ${String(err)}`);
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
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)", textAlign: "left" }}>
              <th style={{ padding: 10, width: 32 }}>
                <input type="checkbox" checked={selected.size === assignments.length && assignments.length > 0} onChange={toggleAll} />
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
                    <input type="checkbox" checked={selected.has(a.id)} onChange={() => toggleOne(a.id)} />
                  </td>
                  <td style={{ padding: 10 }}>
                    {editingThis ? (
                      <input
                        value={draft.title || ""}
                        onChange={e => setDraft(d => ({ ...d, title: e.target.value }))}
                        style={{ padding: "4px 6px", border: "1px solid var(--border)", borderRadius: "var(--r-xs)", fontSize: 12, width: "100%" }}
                      />
                    ) : (
                      <strong>{a.title}</strong>
                    )}
                  </td>
                  <td style={{ padding: 10 }}>
                    {editingThis ? (
                      <CustomSelect
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
                        type="date"
                        value={(draft.due_date || "").slice(0, 10)}
                        onChange={e => setDraft(d => ({ ...d, due_date: e.target.value }))}
                        style={{ padding: "4px 6px", border: "1px solid var(--border)", borderRadius: "var(--r-xs)", fontSize: 12 }}
                      />
                    ) : (
                      a.due_date
                    )}
                  </td>
                  <td style={{ padding: 10, display: "flex", gap: 4 }}>
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
