import type { Assignment, GoogleEvent } from "./api";

export function calendarRange(cursor: Date, view: string) {
  const start = new Date(cursor);
  start.setHours(0, 0, 0, 0);
  if (view === "month") start.setDate(1);
  if (view === "month" || view === "week") start.setDate(start.getDate() - (start.getDay() + 6) % 7);
  if (view === "table") start.setMonth(0, 1);
  const end = new Date(start);
  if (view === "table") end.setFullYear(end.getFullYear() + 1);
  else end.setDate(end.getDate() + (view === "month" ? 42 : view === "week" ? 7 : 1));
  return { start: start.toISOString(), end: end.toISOString() };
}

export function googleEventKey(event: GoogleEvent) {
  return JSON.stringify([event.calendar_id || "primary", event.google_event_id]);
}

export function linkedGoogleEvents(events: GoogleEvent[], assignments: Assignment[]) {
  const exported = new Set(assignments.map(a => a.google_event_id).filter(Boolean));
  return [...new Map(events.filter(e =>
    !((e.primary_calendar || !e.calendar_id) && exported.has(e.google_event_id)),
  ).map(e => [googleEventKey(e), e])).values()];
}

export function googleEventsByDate(events: GoogleEvent[], range: { start: string; end: string }) {
  const map = new Map<string, GoogleEvent[]>();
  for (const event of events) {
    // All-day dates are floating local dates; Google's end date is exclusive.
    const start = new Date(event.all_day ? `${event.start_date}T00:00:00` : event.start_datetime || "");
    const end = new Date(event.all_day ? `${event.end_date}T00:00:00` : event.end_datetime || "");
    if (!Number.isFinite(start.getTime())) continue;
    for (const day = new Date(range.start); day < new Date(range.end); day.setDate(day.getDate() + 1)) {
      const next = new Date(day);
      next.setDate(next.getDate() + 1);
      if (start < next && (Number.isFinite(end.getTime()) && end > start ? end > day : start >= day)) {
        const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
        map.set(key, [...(map.get(key) || []), event]);
      }
    }
  }
  return map;
}
