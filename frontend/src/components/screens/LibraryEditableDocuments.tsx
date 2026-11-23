"use client";

import Link from "next/link";
import React from "react";
import { importEditableDocument, listNotes, noteOriginalHref, type EnrolledCourse } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import type { Note } from "@/lib/types";

export function LibraryEditableDocuments({ userId, courses, courseFilter, query }: {
  userId: string;
  courses: EnrolledCourse[];
  courseFilter: string;
  query: string;
}) {
  const [notes, setNotes] = React.useState<Note[]>([]);
  const [loadError, setLoadError] = React.useState(false);
  const [showImport, setShowImport] = React.useState(false);
  const [importing, setImporting] = React.useState(false);
  const [importError, setImportError] = React.useState("");

  React.useEffect(() => {
    let current = true;
    listNotes(userId).then(
      ({ notes }) => {
        if (current) setNotes((previous) => {
          const loaded = new Set(notes.map((note) => note.id));
          return [...previous.filter((note) => !loaded.has(note.id)), ...notes];
        });
      },
      () => { if (current) setLoadError(true); },
    );
    return () => { current = false; };
  }, [userId]);

  async function onImport(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (importing) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("original");
    const course = form.get("course");
    if (!(file instanceof File) || !file.size || typeof course !== "string" || !course) return;
    if (file.size > 2 * 1024 * 1024) {
      setImportError("Choose a file that is 2 MB or smaller.");
      return;
    }
    setImporting(true);
    setImportError("");
    try {
      const note = await importEditableDocument(userId, course, file);
      setNotes((previous) => [note, ...previous.filter((item) => item.id !== note.id)]);
      setShowImport(false);
      window.location.assign(`/notetaker?note=${encodeURIComponent(note.id)}`);
    } catch (error) {
      setImportError(humanizeError(error, "Couldn't import this document. Try again."));
    } finally {
      setImporting(false);
    }
  }

  const normalizedQuery = query.trim().toLowerCase();
  const visible = notes.filter((note) =>
    (!courseFilter || courseFilter === "all" || courseFilter === note.course_id)
    && (!normalizedQuery || [note.title, note.original_filename].some(
      (value) => value?.toLowerCase().includes(normalizedQuery),
    )),
  );

  return (
    <section aria-labelledby="library-editable-heading" style={{ marginBottom: 22 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <h2 id="library-editable-heading" className="h-serif" style={{ margin: 0, marginRight: "auto" }}>Editable documents</h2>
        <Link className="btn btn--ghost btn--sm" href="/notetaker">Open Notetaker</Link>
        <button
          type="button"
          className="btn btn--primary btn--sm"
          aria-expanded={showImport}
          disabled={!courses.length || importing}
          title={courses.length ? undefined : "Enroll in a course first"}
          onClick={() => { setShowImport(!showImport); setImportError(""); }}
        >
          {showImport ? "Cancel import" : "Import editable copy"}
        </button>
      </div>
      {showImport && (
        <form onSubmit={onImport} style={{ marginBlock: 12 }}>
          <fieldset disabled={importing} style={{ display: "flex", alignItems: "end", flexWrap: "wrap", gap: 12 }}>
            <label style={{ display: "grid", gap: 4 }}>
              Course
              <select name="course" required defaultValue={courses.some((course) => course.course_id === courseFilter) ? courseFilter : ""}>
                <option value="">Choose a course</option>
                {courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.course_code} · {course.course_name}</option>)}
              </select>
            </label>
            <label style={{ display: "grid", gap: 4 }}>
              PDF or Word document (up to 2 MB)
              <input name="original" type="file" accept=".pdf,.docx" required />
            </label>
            <button className="btn btn--primary btn--sm" type="submit">Import document</button>
          </fieldset>
          {importing && <p role="status">Reading the file and saving your original…</p>}
          {importError && <p role="alert">{importError}</p>}
        </form>
      )}
      {loadError && <p role="status">Editable documents couldn’t be loaded. Try refreshing the Library.</p>}
      {visible.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: 8 }}>
          {visible.map((note) => (
            <li key={note.id} style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
              <Link href={`/notetaker?note=${encodeURIComponent(note.id)}`}>{note.title || "Untitled note"}</Link>
              <span className="label-micro">{note.original_filename ? "Imported document" : "Note"}</span>
              {note.original_filename && <a href={noteOriginalHref(note.id)}>Download original</a>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
