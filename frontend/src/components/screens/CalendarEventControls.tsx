import type { Assignment, EnrolledCourse, GoogleEvent } from "@/lib/api";
import Dialog from "../Dialog";
import styles from "./CalendarEvents.module.css";

export type CalendarEventDetail =
  | { kind: "assignment"; event: Assignment }
  | { kind: "google"; event: GoogleEvent };

function localDate(value: string) {
  return new Date(`${value.slice(0, 10)}T12:00:00`);
}

function displayDate(date: Date) {
  return date.toLocaleDateString("en-US", { dateStyle: "long" });
}

function googleWhen(event: GoogleEvent) {
  if (!event.all_day) {
    const format = (value: string) => new Date(value).toLocaleString("en-US", {
      dateStyle: "medium", timeStyle: "short",
    });
    const start = event.start_datetime ? format(event.start_datetime) : event.start_date;
    return event.end_datetime ? `${start} – ${format(event.end_datetime)}` : start;
  }
  const start = localDate(event.start_date);
  const last = localDate(event.end_date);
  last.setDate(last.getDate() - 1);
  return last > start ? `All day · ${displayDate(start)} – ${displayDate(last)}` : `All day · ${displayDate(start)}`;
}

export function CalendarEventDialog({ detail, onClose }: {
  detail: CalendarEventDetail | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={detail !== null} title={detail?.event.title} onClose={onClose}>
      {detail?.kind === "assignment" && (
        <>
          <dl className={styles.eventDetails}>
            <dt>Course</dt><dd>{detail.event.course_code || detail.event.course_name || "No course"}</dd>
            <dt>Due date</dt><dd>{detail.event.due_date ? displayDate(localDate(detail.event.due_date)) : "No due date"}</dd>
            <dt>Type</dt><dd style={{ textTransform: "capitalize" }}>{detail.event.assignment_type || "Assignment"}</dd>
          </dl>
          {detail.event.notes && <p className={styles.eventNotes}>{detail.event.notes}</p>}
        </>
      )}
      {detail?.kind === "google" && (
        <>
          <dl className={styles.eventDetails}>
            <dt>Calendar</dt><dd>{detail.event.calendar_name || "Google Calendar"}</dd>
            <dt>When</dt><dd>{googleWhen(detail.event)}</dd>
            {detail.event.location && <><dt>Location</dt><dd>{detail.event.location}</dd></>}
          </dl>
          {detail.event.description && <p className={styles.eventNotes}>{detail.event.description}</p>}
          {detail.event.html_link?.startsWith("https://") && (
            <a className="btn btn--sm" href={detail.event.html_link} target="_blank" rel="noreferrer">
              Open in Google Calendar
            </a>
          )}
        </>
      )}
    </Dialog>
  );
}

export function CalendarCourseFilters({ courses, assignments, hidden, onToggle, onReset }: {
  courses: EnrolledCourse[];
  assignments: Assignment[];
  hidden: ReadonlySet<string>;
  onToggle: (courseId: string) => void;
  onReset: () => void;
}) {
  const options = new Map(courses.map(course => [course.course_id, course.course_code || course.course_name]));
  for (const assignment of assignments) {
    const id = assignment.course_id || "";
    if (!options.has(id)) options.set(id, assignment.course_code || assignment.course_name || "No course");
  }
  if (options.size === 0) return null;

  return (
    <fieldset className={styles.courseFilters}>
      <legend className="label-micro">Sapling courses</legend>
      <div className={styles.courseOptions}>
        {Array.from(options, ([id, label]) => (
          <label key={id} className={styles.courseOption}>
            <input type="checkbox" checked={!hidden.has(id)} onChange={() => onToggle(id)} />
            {label}
          </label>
        ))}
        {Array.from(options.keys()).some(id => hidden.has(id)) && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={onReset}>Show all courses</button>
        )}
      </div>
    </fieldset>
  );
}
