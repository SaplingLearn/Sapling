"use client";

import React, { useEffect, useRef, useState } from "react";
import { getTopicChecklist, refreshTopicChecklist, setTopicReviewed, type TopicChecklist } from "@/lib/topicChecklistApi";

const STATUS_LABELS = {
  not_started: "Not started",
  needs_review: "Needs review",
  in_progress: "In progress",
  mastered: "Mastered",
};

export function TopicChecklistPanel({ userId, courseId, semester, semesters = [] }: {
  userId: string; courseId: string; semester?: string; semesters?: string[];
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<TopicChecklist | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedSemester, setSelectedSemester] = useState("");
  const scopedSemester = semester || selectedSemester || undefined;
  const controller = useRef<AbortController | null>(null);
  const generation = useRef<object | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    controller.current = abort;
    const version = {};
    generation.current = version;
    let current = true;
    setBusy(true);
    setError("");
    setData(null);
    (async () => {
      try {
        let result = await getTopicChecklist(userId, courseId, scopedSemester, abort.signal);
        if (!current) return;
        setData(result);
        // Regenerate only when evidence changes, not when mastery changes.
        if (result.needs_refresh) result = await refreshTopicChecklist(userId, courseId, scopedSemester, abort.signal);
        if (current && generation.current === version) setData(result);
      } catch {
        if (current && !abort.signal.aborted) setError("Could not update the checklist. Please try again.");
      } finally {
        if (current && generation.current === version) setBusy(false);
      }
    })();
    return () => { current = false; abort.abort(); generation.current = null; };
  }, [open, userId, courseId, scopedSemester]);

  async function update(topicId?: string, checked?: boolean) {
    if (busy) return;
    const version = {};
    generation.current = version;
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    setBusy(true);
    setError("");
    try {
      if (topicId) {
        const progress = await setTopicReviewed(userId, courseId, topicId, !!checked, scopedSemester, abort.signal);
        // Freshness is not recomputed by a checkmark; keep the last read's.
        if (generation.current === version && !abort.signal.aborted) {
          setData((prev) => ({ needs_refresh: prev?.needs_refresh ?? false, warnings: prev?.warnings ?? [], ...progress }));
        }
      } else {
        const result = await refreshTopicChecklist(userId, courseId, scopedSemester, abort.signal);
        if (generation.current === version && !abort.signal.aborted) setData(result);
      }
    } catch {
      if (generation.current === version && !abort.signal.aborted) setError("Could not save the checklist. Please try again.");
    } finally {
      if (generation.current === version) setBusy(false);
    }
  }

  const names = new Map(data?.topics.map((topic) => [topic.id, topic.name]));
  const topics = data?.topics.filter((topic) => filter === "all" || topic.status === filter) ?? [];
  return (
    <section data-testid="topic-checklist" style={{ borderBottom: "1px solid var(--border)", padding: "10px 16px", flexShrink: 0 }}>
      <button data-testid="topic-checklist-toggle" className="btn btn--sm" type="button" aria-expanded={open} aria-controls="topic-checklist-content" onClick={() => setOpen(!open)}>
        {open ? "Hide topic checklist" : "Topic checklist"}
      </button>
      {open && (
        <div id="topic-checklist-content" style={{ maxHeight: "35vh", overflowY: "auto", paddingTop: 10 }} aria-busy={busy}>
          <p style={{ fontSize: 13 }}>Course topics from BU catalog information and your materials. Check a topic after studying it; mastery and review needs remain separate.</p>
          {data?.semester && <p style={{ fontSize: 13 }}>Semester: {data.semester}</p>}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", margin: "10px 0" }}>
            {!semester && semesters.length > 1 && <label style={{ fontSize: 13 }}>Semester {" "}
              <select data-testid="topic-checklist-semester" aria-label="Checklist semester" value={selectedSemester} onChange={(e) => setSelectedSemester(e.target.value)}>
                <option value="">Current or most recent enrollment</option>
                {semesters.map((term) => <option key={term} value={term}>{term}</option>)}
              </select>
            </label>}
            <label style={{ fontSize: 13 }}>Show topics {" "}
              <select data-testid="topic-checklist-filter" aria-label="Filter checklist topics" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="all">All topics</option>
                {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <button data-testid="topic-checklist-refresh" className="btn btn--sm" type="button" disabled={busy} onClick={() => update()}>Update from materials</button>
            {busy && <span role="status">Updating checklist…</span>}
          </div>
          {error && <p role="alert">{error}</p>}
          {data?.needs_refresh && !busy && <p style={{ fontSize: 13 }}>Showing the previous outline. Update from materials to include recent changes.</p>}
          {data?.warnings.map((warning) => <p key={warning} style={{ fontSize: 13 }}>{warning}</p>)}
          {!!data?.assessments.length && (
            <p style={{ fontSize: 13 }}>Upcoming assessments: {data.assessments.map((a) => `${a.title} (${a.due_date})`).join("; ")}. Topic coverage is shown only when supported by your materials.</p>
          )}
          {!busy && data && !topics.length && <p>No topics match this view.</p>}
          <ul style={{ listStyle: "none", padding: 0 }}>
            {topics.map((topic) => (
              <li key={topic.id} data-testid={`topic-checklist-topic-${topic.id}`} style={{ borderTop: "1px solid var(--border)", padding: "10px 0" }}>
                {topic.parent_id && <small>{names.get(topic.parent_id)}</small>}
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
                  <label><input data-testid={`topic-checklist-check-${topic.id}`} type="checkbox" aria-label={`Studied ${topic.name}`} checked={topic.checked} disabled={busy} onChange={(e) => update(topic.id, e.target.checked)} /> {topic.name}</label>
                  <span style={{ fontSize: 12 }}>{STATUS_LABELS[topic.status]}{topic.priority === "high" ? " · Prioritize" : ""}</span>
                  {topic.mastery_score !== null && <span style={{ fontSize: 12 }}>Mastery {Math.round(topic.mastery_score * 100)}%</span>}
                </div>
                <p style={{ fontSize: 13, margin: "6px 0" }}>{topic.description}</p>
                {!!topic.review_reasons.length && <p style={{ fontSize: 12 }}>{topic.review_reasons.join(" · ")}</p>}
                {!!topic.prerequisite_gaps.length && <p style={{ fontSize: 12 }}>Review prerequisites: {topic.prerequisite_gaps.join(", ")}</p>}
                {!!topic.assessments.length && <p style={{ fontSize: 12 }}>For: {topic.assessments.map((a) => `${a.title} · ${a.due_date}`).join("; ")}</p>}
                {!!topic.sources.length && <small>Sources: {topic.sources.map((s) => s.label).join(", ")}</small>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
