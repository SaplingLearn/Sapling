// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { GoogleCalendarEvents } from "./GoogleCalendarEvents";

afterEach(cleanup);

it("uses the viewer's local date for timed event metadata", () => {
  render(<GoogleCalendarEvents events={[{
    google_event_id: "g1", title: "Meeting", all_day: false,
    start_date: "2026-11-03", end_date: "2026-11-03",
    start_datetime: new Date(2026, 10, 2, 23, 30).toISOString(),
  }]} />);
  expect(screen.getByText(/11\/2\/2026/)).toBeInTheDocument();
  expect(screen.queryByText(/2026-11-03/)).toBeNull();
});

it("preserves floating all-day dates without timezone conversion", () => {
  render(<GoogleCalendarEvents events={[{
    google_event_id: "g1", title: "Holiday", all_day: true,
    start_date: "2026-11-02", end_date: "2026-11-03",
  }]} />);
  expect(screen.getByText(/All day.*2026-11-02/)).toBeInTheDocument();
});
