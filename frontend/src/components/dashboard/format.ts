import { now } from "@/lib/testMode";

/** "just now" / "5 min ago" / "3 h ago" / "yesterday" / "4 days ago" / a date. */
export function relativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const mins = Math.round((now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  const days = Math.round(hrs / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** An explicit due date: "Due Fri, Aug 1" (+ ", 11:59 PM" when the value carries a time). */
export function dueLabel(iso: string): string {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  // A bare date is a calendar day, not midnight UTC: read it as local.
  const d = dateOnly ? new Date(`${iso}T00:00:00`) : new Date(iso);
  if (Number.isNaN(d.getTime())) return "Due date unavailable";
  const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  if (dateOnly) return `Due ${day}`;
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `Due ${day}, ${time}`;
}

/** "Wednesday, March 11" for the Home date line. */
export function longDate(ms: number): string {
  return new Date(ms).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
}
