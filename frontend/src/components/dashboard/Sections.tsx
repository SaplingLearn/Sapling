"use client";
import React from "react";
import Link from "next/link";

import { StatusMessage } from "@/components/sapling";
import type { Assignment, Session } from "@/lib/api";
import type { Note } from "@/lib/types";
import { resumeHref } from "@/lib/dashboard/nextStep";
import { dueLabel, relativeTime } from "./format";
import { hasData, type Resource } from "./useResource";
import styles from "./Dashboard.module.css";

/** GET /api/notes/user/{id} also attaches the note's abstract course labels
 *  (routes/notes.py::_course_meta); the shared `Note` type predates that. */
export type ListedNote = Note & { course_code?: string | null; course_name?: string | null };

function Arrow() {
  return <span className={styles.arrow} aria-hidden="true">↗</span>;
}

function Pending({ children, testid }: { children: React.ReactNode; testid: string }) {
  return <StatusMessage tone="pending" testid={testid}>{children}</StatusMessage>;
}

/* ── Recent notes ────────────────────────────────────────────────────── */

/**
 * Notes are the Notetaker's owned, persisted `notes` rows (routes/notes.py:
 * require_self, encrypted title/body, newest `updated_at` first). At most two
 * rows, each opening that note in the Notetaker (`/notetaker?note=<id>`).
 * No sample rows, no browser-only drafts, no Add-note control here: notes are
 * written in the Notetaker. A failed read is an error with Retry, never
 * "no notes yet".
 */
export function RecentNotes({
  notes,
  notetakerHidden,
  courseLabel,
}: {
  notes: Resource<ListedNote[]>;
  notetakerHidden: boolean;
  courseLabel: (id: string | null | undefined) => string | null;
}) {
  const rows = (notes.data ?? []).slice(0, 2);
  return (
    <section aria-labelledby="dashboard-notes-title" data-testid="dashboard-notes">
      <div className={styles.sectionHead}>
        <h2 id="dashboard-notes-title" className={styles.sectionTitle}>Recent notes</h2>
        <Link className={styles.textLink} href="/library" data-testid="dashboard-view-library">
          View Library <Arrow />
        </Link>
      </div>
      {notetakerHidden ? (
        <p className={styles.muted} data-testid="dashboard-notes-off">
          Notes aren&apos;t turned on for your account. Your course materials are in Library.
        </p>
      ) : notes.status === "loading" ? (
        <Pending testid="dashboard-notes-loading">Loading your notes…</Pending>
      ) : notes.status === "error" ? (
        <StatusMessage tone="error" title="Couldn't load your notes" onRetry={notes.retry} testid="dashboard-notes-error">
          Your notes are safe; this is only a loading problem.
        </StatusMessage>
      ) : hasData(notes.status) && rows.length === 0 ? (
        <p className={styles.muted} data-testid="dashboard-notes-empty">
          No saved notes yet. Notes you write in{" "}
          <Link className={styles.textLink} style={{ minHeight: 0, display: "inline" }} href="/notetaker" data-testid="dashboard-open-notetaker">
            Notetaker
          </Link>{" "}
          appear here.
        </p>
      ) : (
        <>
          {notes.status === "stale" && (
            <StatusMessage tone="info" onRetry={notes.retry} testid="dashboard-notes-stale">
              Couldn&apos;t refresh your notes; showing the last list.
            </StatusMessage>
          )}
          <ul className={styles.rows}>
            {rows.map((n) => {
              const course = n.course_code || n.course_name || courseLabel(n.course_id);
              const edited = relativeTime(n.updated_at);
              return (
                <li key={n.id}>
                  <Link className={styles.rowLink} href={`/notetaker?note=${encodeURIComponent(n.id)}`} data-testid={`dashboard-note-${n.id}`}>
                    <span className={styles.rowText}>
                      <span className={styles.rowTitle}>{n.title?.trim() || "Untitled note"}</span>
                      <span className={styles.rowMeta}>{[course, edited ? `Edited ${edited}` : null].filter(Boolean).join(" · ")}</span>
                    </span>
                    <Arrow />
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

/* ── Coming up ───────────────────────────────────────────────────────── */

export interface DueSummary {
  count: number;
  courseCount: number;
}

/**
 * One or two genuinely time-sensitive items: the due-review queue (when the
 * graph says something is due — a named, scope=due quiz that carries the
 * dashboard return context) and the nearest DATED assignments. Undated
 * tasks never show here; every assignment stays reachable in Calendar.
 * Assignments are not semester-scoped, and the list says so when a semester
 * is picked.
 */
export function ComingUp({
  assignments,
  due,
  reviewHref,
  semesterScoped,
  onNavigate,
}: {
  assignments: Resource<Assignment[]>;
  due: DueSummary | null;
  reviewHref: string;
  semesterScoped: boolean;
  onNavigate: (href: string) => void;
}) {
  const dated = (assignments.data ?? [])
    .filter((a): a is Assignment & { due_date: string } => !!a.due_date)
    .sort((a, b) => a.due_date.localeCompare(b.due_date));
  const showReview = !!due && due.count > 0;
  const room = showReview ? 1 : 2;
  const rows = dated.slice(0, room);
  return (
    <section aria-labelledby="dashboard-coming-title" data-testid="dashboard-coming">
      <div className={styles.sectionHead}>
        <h2 id="dashboard-coming-title" className={styles.sectionTitle}>Coming up</h2>
        <Link className={styles.textLink} href="/calendar" data-testid="dashboard-open-calendar">
          Calendar <Arrow />
        </Link>
      </div>
      <ul className={styles.rows}>
        {showReview && (
          <li>
            <button type="button" className={styles.rowLink} onClick={() => onNavigate(reviewHref)} data-testid="dashboard-review-due">
              <span className={styles.rowText}>
                <span className={styles.rowTitle}>Review what&apos;s due · {due!.count}</span>
                <span className={styles.rowMeta}>
                  {due!.count} {due!.count === 1 ? "concept is" : "concepts are"} ready for review
                  {due!.courseCount > 1 ? ` across ${due!.courseCount} courses` : ""}
                </span>
              </span>
              <span className={styles.arrow} aria-hidden="true">→</span>
            </button>
          </li>
        )}
        {hasData(assignments.status) &&
          rows.map((a) => (
            <li key={a.id}>
              <Link className={styles.rowLink} href="/calendar" data-testid={`dashboard-assignment-${a.id}`}>
                <span className={styles.rowText}>
                  <span className={styles.rowTitle}>{a.title}</span>
                  <span className={styles.rowMeta}>{[a.course_code || a.course_name, dueLabel(a.due_date)].filter(Boolean).join(" · ")}</span>
                </span>
                <span className={styles.arrow} aria-hidden="true">→</span>
              </Link>
            </li>
          ))}
      </ul>
      {assignments.status === "loading" && <Pending testid="dashboard-assignments-loading">Loading upcoming work…</Pending>}
      {assignments.status === "error" && (
        <StatusMessage tone="error" title="Couldn't load upcoming work" onRetry={assignments.retry} testid="dashboard-assignments-error">
          Your assignments are still in Calendar.
        </StatusMessage>
      )}
      {assignments.status === "stale" && (
        <StatusMessage tone="info" onRetry={assignments.retry} testid="dashboard-assignments-stale">
          Couldn&apos;t refresh upcoming work; showing the last list.
        </StatusMessage>
      )}
      {hasData(assignments.status) && rows.length === 0 && !showReview && (
        <p className={styles.muted} data-testid="dashboard-coming-empty">Nothing with a due date coming up.</p>
      )}
      {hasData(assignments.status) && semesterScoped && rows.length > 0 && (
        <p className={styles.scopeNote}>Assignments from all semesters.</p>
      )}
    </section>
  );
}

/* ── Recent sessions (history) ───────────────────────────────────────── */

/** The three most recent tutor sessions, each resuming by its real id
 *  (`/learn?resume=<id>`: an open loop session resumes, in its own course;
 *  an ended or legacy one opens read-only). Sessions are not
 *  semester-scoped; the list says so when a semester is picked. */
export function RecentSessions({
  sessions,
  semesterScoped,
  courseLabel,
  onNavigate,
}: {
  sessions: Resource<Session[]>;
  semesterScoped: boolean;
  courseLabel: (id: string | null | undefined) => string | null;
  onNavigate: (href: string) => void;
}) {
  const rows = (sessions.data ?? []).slice(0, 3);
  return (
    <section aria-labelledby="dashboard-sessions-title" data-testid="dashboard-sessions">
      <div className={styles.sectionHead}>
        <h2 id="dashboard-sessions-title" className={styles.sectionTitle}>Recent sessions</h2>
        <Link className={styles.textLink} href="/learn" data-testid="dashboard-open-learn">
          Learn <Arrow />
        </Link>
      </div>
      {sessions.status === "loading" && <Pending testid="dashboard-sessions-loading">Loading your sessions…</Pending>}
      {sessions.status === "error" && (
        <StatusMessage tone="error" title="Couldn't load your sessions" onRetry={sessions.retry} testid="dashboard-sessions-error">
          Nothing was started or changed.
        </StatusMessage>
      )}
      {hasData(sessions.status) && rows.length === 0 && (
        <p className={styles.muted} data-testid="dashboard-sessions-empty">No sessions yet.</p>
      )}
      {rows.length > 0 && (
        <ul className={styles.rows}>
          {rows.map((s) => (
            <li key={s.id}>
              <button type="button" className={styles.rowLink} onClick={() => onNavigate(resumeHref(s.id))} data-testid={`dashboard-resume-${s.id}`}>
                <span className={styles.rowText}>
                  <span className={styles.rowTitle}>{s.topic || "Untitled session"}</span>
                  <span className={styles.rowMeta}>
                    {[courseLabel(s.course_id), s.is_active ? "Open" : "Ended", relativeTime(s.started_at)].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <span className={styles.arrow} aria-hidden="true">→</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {hasData(sessions.status) && semesterScoped && rows.length > 0 && (
        <p className={styles.scopeNote}>Sessions from all semesters.</p>
      )}
    </section>
  );
}
