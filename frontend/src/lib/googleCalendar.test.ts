import { describe, expect, it } from "vitest";
import type { GoogleEvent } from "./api";
import { calendarRange, googleEventsByDate, linkedGoogleEvents } from "./googleCalendar";

const event: GoogleEvent = {
  google_event_id: "g1", calendar_id: "c1", primary_calendar: true, title: "Workshop",
  all_day: true, start_date: "2026-11-02", end_date: "2026-11-04",
};
const range = calendarRange(new Date(2026, 10, 2), "week");

describe("linked Google event identity", () => {
  it("replaces duplicate IDs but preserves distinct events with the same title and date", () => {
    expect(linkedGoogleEvents([event, { ...event, title: "Updated" }, { ...event, google_event_id: "g2" }], []))
      .toEqual([{ ...event, title: "Updated" }, { ...event, google_event_id: "g2" }]);
  });
  it("filters exported assignments only in the primary calendar", () => {
    const shared = { ...event, calendar_id: "shared", primary_calendar: false };
    expect(linkedGoogleEvents([event, shared], [{ id: "a1", user_id: "u1", title: "Workshop", due_date: null, google_event_id: "g1" }]))
      .toEqual([shared]);
  });
  it("honors Google's exclusive all-day end date", () => {
    expect([...googleEventsByDate([event], range).keys()]).toEqual(["2026-11-02", "2026-11-03"]);
  });
  it("places timed events on the viewer's local date and excludes a midnight end", () => {
    const start = new Date(2026, 10, 2, 23);
    const end = new Date(2026, 10, 3, 0);
    const timed = { ...event, all_day: false, start_datetime: start.toISOString(), end_datetime: end.toISOString() };
    expect([...googleEventsByDate([timed], range).keys()]).toEqual(["2026-11-02"]);
  });
  it("clips ongoing multi-day events to the displayed range", () => {
    expect([...googleEventsByDate([{ ...event, start_date: "2026-10-01", end_date: "2026-12-01" }], calendarRange(new Date(2026, 10, 2), "day")).keys()])
      .toEqual(["2026-11-02"]);
  });
});
