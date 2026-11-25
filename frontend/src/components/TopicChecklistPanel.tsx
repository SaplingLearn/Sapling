"use client";

import React, { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, type Target } from "framer-motion";
import { useMotionPresets, type MotionPreset } from "@/lib/motion";
import styles from "./TopicChecklistPanel.module.css";
import { getTopicChecklist, refreshTopicChecklist, setTopicReviewed, type TopicChecklist } from "@/lib/topicChecklistApi";

/** A preset as motion props. Its `initial` is narrowed to `Target`: spread
 *  as-is, framer's prop union is too wide for TypeScript to check. */
const asMotion = (p: MotionPreset) => ({ initial: p.initial as Target, animate: p.animate, exit: p.exit, transition: p.transition });

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
  const m = useMotionPresets();

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
    // A controlled checkbox only moves when state does: show the check now and
    // put it back if the save fails, rather than lagging behind the request.
    const setChecked = (value: boolean) => setData((prev) => {
      if (generation.current !== version || abort.signal.aborted || !prev) return prev;
      return { ...prev, topics: prev.topics.map((topic) => topic.id === topicId ? { ...topic, checked: value } : topic) };
    });
    if (topicId) setChecked(!!checked);
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
      if (generation.current === version && !abort.signal.aborted) {
        if (topicId) setChecked(!checked);
        setError("Could not save the checklist. Please try again.");
      }
    } finally {
      if (generation.current === version) setBusy(false);
    }
  }

  const names = new Map(data?.topics.map((topic) => [topic.id, topic.name]));
  const topics = data?.topics.filter((topic) => filter === "all" || topic.status === filter) ?? [];
  return (
    <section data-testid="topic-checklist" className={styles.root}>
      <button data-testid="topic-checklist-toggle" className="btn btn--sm" type="button" aria-expanded={open} aria-controls="topic-checklist-content" onClick={() => setOpen(!open)}>
        {open ? "Hide topic checklist" : "Topic checklist"}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="checklist" {...asMotion(m.collapse)}>
            <div id="topic-checklist-content" className={styles.content} aria-busy={busy}>
              <p className={styles.note}>Course topics from BU catalog information and your materials. Check a topic after studying it; mastery and review needs remain separate.</p>
              {data?.semester && <p className={styles.note}>Semester: {data.semester}</p>}
              <div className={styles.controls}>
                {!semester && semesters.length > 1 && <label className={styles.note}>Semester {" "}
                  <select data-testid="topic-checklist-semester" aria-label="Checklist semester" value={selectedSemester} onChange={(e) => setSelectedSemester(e.target.value)}>
                    <option value="">Current or most recent enrollment</option>
                    {semesters.map((term) => <option key={term} value={term}>{term}</option>)}
                  </select>
                </label>}
                <label className={styles.note}>Show topics {" "}
                  <select data-testid="topic-checklist-filter" aria-label="Filter checklist topics" value={filter} onChange={(e) => setFilter(e.target.value)}>
                    <option value="all">All topics</option>
                    {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <button data-testid="topic-checklist-refresh" className="btn btn--sm" type="button" disabled={busy} onClick={() => update()}>Update from materials</button>
                {busy && <motion.span role="status" {...asMotion(m.fade)}>Updating checklist…</motion.span>}
              </div>
              {error && <motion.p role="alert" {...asMotion(m.fade)}>{error}</motion.p>}
              {data?.needs_refresh && !busy && <p className={styles.note}>Showing the previous outline. Update from materials to include recent changes.</p>}
              {data?.warnings.map((warning) => <p key={warning} className={styles.note}>{warning}</p>)}
              {!!data?.assessments.length && (
                <p className={styles.note}>Upcoming assessments: {data.assessments.map((a) => `${a.title} (${a.due_date})`).join("; ")}. Topic coverage is shown only when supported by your materials.</p>
              )}
              {!busy && data && !topics.length && <p>No topics match this view.</p>}
              <motion.ul className={styles.list} variants={m.list.container} initial="hidden" animate="shown">
                {topics.map((topic) => (
                  <motion.li key={topic.id} data-testid={`topic-checklist-topic-${topic.id}`} className={styles.topic} variants={m.list.item}>
                    {topic.parent_id && <small>{names.get(topic.parent_id)}</small>}
                    <div className={styles.topicHead}>
                      <label><input data-testid={`topic-checklist-check-${topic.id}`} type="checkbox" aria-label={`Studied ${topic.name}`} checked={topic.checked} disabled={busy} onChange={(e) => update(topic.id, e.target.checked)} /> {topic.name}</label>
                      <span className={styles.meta}>{STATUS_LABELS[topic.status]}{topic.priority === "high" ? " · Prioritize" : ""}</span>
                      {topic.mastery_score !== null && <span className={styles.meta}>Mastery {Math.round(topic.mastery_score * 100)}%</span>}
                    </div>
                    <p className={styles.description}>{topic.description}</p>
                    {!!topic.review_reasons.length && <p className={styles.meta}>{topic.review_reasons.join(" · ")}</p>}
                    {!!topic.prerequisite_gaps.length && <p className={styles.meta}>Review prerequisites: {topic.prerequisite_gaps.join(", ")}</p>}
                    {!!topic.assessments.length && <p className={styles.meta}>For: {topic.assessments.map((a) => `${a.title} · ${a.due_date}`).join("; ")}</p>}
                    {!!topic.sources.length && <small>Sources: {topic.sources.map((s) => s.label).join(", ")}</small>}
                  </motion.li>
                ))}
              </motion.ul>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
