"use client";

import React, { useEffect, useRef, useState } from "react";
import { getCachedStudyGuides, getSavedStudyGuide, type StudyGuideCacheEntry, type StudyGuideContent } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";

/** Preserve existing saved content without a second assessment-creation flow. */
export function SavedStudyGuides({ userId, courseId, semester }: { userId: string; courseId: string; semester: string }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<StudyGuideCacheEntry[]>([]);
  const [guide, setGuide] = useState<StudyGuideContent | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!open) return;
    let current = true;
    setBusy(true);
    setGuide(null);
    setEntries([]);
    setError("");
    getCachedStudyGuides(userId).then((result) => {
      if (current) setEntries(result.guides.filter((entry) => (!courseId || entry.course_id === courseId)
        && (!semester || entry.semester === semester)));
    }).catch((err) => { if (current) setError(humanizeError(err, "Couldn't load saved guides.")); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; controller.current?.abort(); };
  }, [open, userId, courseId, semester]);

  async function read(id: string) {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    setGuide(null);
    try {
      const result = await getSavedStudyGuide(userId, id, abort.signal);
      if (!abort.signal.aborted) setGuide(result.guide);
    } catch (err) {
      if (!abort.signal.aborted) setError(humanizeError(err, "Couldn't open that saved guide."));
    } finally { if (!abort.signal.aborted) setBusy(false); }
  }

  return <section aria-label="Earlier saved guides" style={{ borderTop: "1px solid var(--sapling-line)", marginTop: 32, paddingTop: 20 }}>
    <button className="btn btn--sm" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Earlier saved guides</button>
    {open && <div aria-busy={busy}>
      <p>Previously generated content stays available here. New assessment guides above include your schedule and topic progress together.</p>
      {busy && <p role="status">Loading saved content…</p>}
      {error && <p role="alert">{error}</p>}
      {!busy && !entries.length && !error && <p>No earlier saved guides for this course and semester.</p>}
      {entries.map((entry) => <button key={entry.id} className="btn btn--sm" type="button" disabled={busy} onClick={() => void read(entry.id)}>{entry.exam_title}</button>)}
      {guide && <article><h3>{guide.exam}</h3><p>{guide.overview}</p>{guide.topics.map((topic, index) => <section key={index}><h4>{topic.name}</h4><p>{topic.importance}</p><ul>{topic.concepts.map((concept, i) => <li key={i}>{concept}</li>)}</ul></section>)}</article>}
    </div>}
  </section>;
}
