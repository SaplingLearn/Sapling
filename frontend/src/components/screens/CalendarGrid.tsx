import type { Assignment, EnrolledCourse, GoogleEvent } from "@/lib/api";
import { now } from "@/lib/testMode";
import { GoogleCalendarEvents } from "../GoogleCalendarEvents";
import styles from "./CalendarEvents.module.css";

type CalendarGridProps = {
  cursor: Date;
  byDate: Map<string, Assignment[]>;
  googleByDate: Map<string, GoogleEvent[]>;
  courses: EnrolledCourse[];
  onAssignment: (assignment: Assignment) => void;
  onGoogleEvent: (event: GoogleEvent) => void;
};

const TYPE_COLOR: Record<string, string> = {
  exam: "var(--c-rust)",
  project: "var(--c-teal)",
  homework: "var(--c-sage)",
  quiz: "var(--warn)",
  reading: "var(--c-plum)",
  other: "var(--text-muted)",
};

export function dateKey(d: Date) {
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

export function startOfWeekMon(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  const day = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - day);
  return x;
}

export function MonthView({
  cursor, byDate, googleByDate, courses, onAssignment, onGoogleEvent, today, onShowDay,
}: CalendarGridProps & { today: Date; onShowDay: (date: Date) => void }) {
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
              <GoogleCalendarEvents events={googleByDate.get(key) || []} onSelect={onGoogleEvent} compact />
              {items.slice(0, 3).map(a => {
                const color = TYPE_COLOR[a.assignment_type || "other"];
                const dotColor = a.course_id ? courseColor.get(a.course_id) || color : color;
                return (
                  <button
                    type="button"
                    className={styles.eventButton}
                    onClick={() => onAssignment(a)}
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
                  </button>
                );
              })}
              {items.length > 3 && (
                <button type="button" className={styles.eventButton} onClick={() => onShowDay(d)}
                  aria-label={`Show all events for ${d.toLocaleDateString("en-US", { dateStyle: "long" })}`}>
                  +{items.length - 3} more
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function WeekView({
  cursor, byDate, googleByDate, courses, onAssignment, onGoogleEvent, today,
}: CalendarGridProps & { today: Date }) {
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
              <GoogleCalendarEvents events={googleByDate.get(key) || []} onSelect={onGoogleEvent} compact />
              {items.length === 0 && !googleByDate.get(key)?.length && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>—</div>}
              {items.map(a => {
                const color = TYPE_COLOR[a.assignment_type || "other"];
                const dotColor = a.course_id ? courseColor.get(a.course_id) || color : color;
                return (
                  <button
                    type="button"
                    className={styles.eventButton}
                    onClick={() => onAssignment(a)}
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
                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: "block", fontWeight: 600, color: "var(--text)" }}>{a.title}</span>
                      <span style={{ display: "block", color: "var(--text-muted)", fontSize: 10 }}>
                        {a.course_code || a.course_name}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DayView({ cursor, byDate, googleByDate, courses, onAssignment, onGoogleEvent }: CalendarGridProps) {
  const key = dateKey(cursor);
  const items = byDate.get(key) || [];
  const courseColor = new Map(courses.map(c => [c.course_id, c.color]));
  return (
    <div style={{ padding: "20px 32px", maxWidth: 720 }}>
      <div className="h-serif" style={{ fontSize: 24, fontWeight: 500, marginBottom: 16 }}>
        {cursor.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
      </div>
      <GoogleCalendarEvents events={googleByDate.get(key) || []} onSelect={onGoogleEvent} />
      {items.length === 0 && !googleByDate.get(key)?.length && (
        <div className="card" style={{ padding: "var(--pad-lg)", textAlign: "center", color: "var(--text-muted)" }}>
          Nothing scheduled.
        </div>
      )}
      {items.map(a => {
        const color = TYPE_COLOR[a.assignment_type || "other"];
        const dotColor = a.course_id ? courseColor.get(a.course_id) || color : color;
        const dl = dueLabel(a.due_date);
        return (
          <button type="button" onClick={() => onAssignment(a)} key={a.id} className={`card ${styles.eventButton}`} style={{ width: "100%", padding: "var(--pad-lg)", marginBottom: 10, display: "flex", gap: 14, alignItems: "flex-start" }}>
            <span aria-hidden style={{
              width: 8, height: 8, borderRadius: "50%",
              background: dotColor, marginTop: 8, flexShrink: 0,
            }} />
            <span style={{ flex: 1 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <strong>{a.title}</strong>
                <span className={`chip ${dl.cls}`}>{dl.label}</span>
              </span>
              <span style={{ display: "block", fontSize: 12, color: "var(--text-muted)" }}>
                {a.course_code || a.course_name || "—"} · {a.assignment_type || "task"}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
