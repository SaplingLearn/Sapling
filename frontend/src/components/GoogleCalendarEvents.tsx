import type { GoogleEvent } from "@/lib/api";
import { googleEventKey } from "@/lib/googleCalendar";

export function GoogleCalendarEvents({ events, compact = false }: { events: GoogleEvent[]; compact?: boolean }) {
  return <>{events.map(event => (
    <div key={googleEventKey(event)} style={{ padding: compact ? "4px 0" : "12px 0", borderLeft: "2px solid var(--c-teal)", paddingLeft: 8, marginBottom: 6, minWidth: 0 }}>
      <div style={{ fontSize: compact ? 11 : 13, fontWeight: 600, overflowWrap: "anywhere" }}>
        {event.html_link?.startsWith("https://")
          ? <a href={event.html_link} target="_blank" rel="noreferrer">{event.title}</a>
          : event.title}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
        Google · {event.all_day ? "All day" : new Date(event.start_datetime || "").toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
        {!compact && ` · ${event.calendar_name || "Google Calendar"} · ${event.all_day
          ? event.start_date
          : new Date(event.start_datetime || "").toLocaleDateString("en-US")}`}
      </div>
      {!compact && event.location && <div style={{ fontSize: 12 }}>{event.location}</div>}
      {!compact && event.description && <p style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{event.description}</p>}
    </div>
  ))}</>;
}
