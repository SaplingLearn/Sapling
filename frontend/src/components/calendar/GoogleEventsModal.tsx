"use client";
// The Calendar's "View Google events" modal (moved out of screens/Calendar.tsx
// so the redesigned calendar shares it).
import { PanelModal } from "@/components/ui/PanelModal";
import type { GoogleEvent } from "@/lib/api";

/** How far ahead "View Google events" looks, in days (the modal's copy says it too). */
export const GOOGLE_EVENTS_DAYS = 60;
/** A Google event's description is cut to this many characters in the modal. */
const DESCRIPTION_PREVIEW_CHARS = 140;

export function GoogleEventsModal({
  events, onClose,
}: {
  events: GoogleEvent[];
  onClose: () => void;
}) {
  return (
    <PanelModal label="Upcoming Google Calendar events" onClose={onClose} maxWidth="max-w-160" maxHeight="max-h-[82vh]">
        <div className="p-5">
          {events.length === 0 ? (
            <div className="text-text-muted text-md text-center p-7">
              No upcoming events in the next {GOOGLE_EVENTS_DAYS} days.
            </div>
          ) : (
            <div className="flex flex-col gap-2.5">
              {events.map(e => (
                <div key={e.google_event_id} className="card p-3">
                  <div className="flex justify-between items-baseline gap-2.5">
                    <div className="font-semibold text-md">{e.title}</div>
                    <span className="chip text-xs">
                      {e.all_day ? "All day" : e.start_datetime?.slice(11, 16) || ""}
                    </span>
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    {e.start_date} {e.end_date && e.end_date !== e.start_date ? `→ ${e.end_date}` : ""}
                    {e.location ? ` · ${e.location}` : ""}
                  </div>
                  {e.description && (
                    <div className="text-sm text-text-dim mt-1.5 leading-[1.5]">
                      {e.description.length > DESCRIPTION_PREVIEW_CHARS
                        ? e.description.slice(0, DESCRIPTION_PREVIEW_CHARS) + "…"
                        : e.description}
                    </div>
                  )}
                  {e.html_link && (
                    <a
                      href={e.html_link}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-accent mt-1.5 inline-block"
                    >
                      Open in Google Calendar →
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
    </PanelModal>
  );
}
