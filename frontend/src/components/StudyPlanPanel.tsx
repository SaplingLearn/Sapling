"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import {
  createStudyPlan, deleteStudyPlan, getStudyPlans, getStudyPlanSources, updateStudyPlan,
  type PlanChanges, type PlanInput, type PlanSources, type PlanTopic, type StudyPlan,
} from "@/lib/studyPlanApi";
import styles from "./StudyPlanPanel.module.css";
import { PageHeading, SaplingSurface } from "@/components/sapling";

const LABELS = { not_started: "Not started", in_progress: "Learning", needs_review: "Needs review", mastered: "Mastered" };
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function localDate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function offsetDate(value: string, days: number) {
  if (!value) return "";
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function initialInput(): PlanInput {
  return { title: "", assessment_type: "exam", assessment_date: "", start_date: localDate(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", coverage: "",
    document_ids: [], assignment_ids: [], study_days: [0, 1, 2, 3, 4, 5, 6], minutes_per_day: 60 };
}

function message(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 409) return "This plan changed in another window. Refresh progress, then try again.";
    if (error.status === 429) return "Please wait a moment before generating another plan.";
    const body = error.body as { detail?: unknown } | undefined;
    if (typeof body?.detail === "string") return body.detail;
  }
  return "Could not save or load your study plan. Please try again.";
}

function editableTopics(plan: StudyPlan): PlanTopic[] {
  return plan.topics.map(({ id, name, description, parent_id, prerequisite_ids, source_ids, importance, study_points }) =>
    ({ id, name, description, parent_id, prerequisite_ids, source_ids, importance, study_points }));
}

export function StudyPlanPanel({ userId, courseId, semester, semesters = [], expanded = false, initialDocumentId = "" }: {
  userId: string; courseId: string; semester?: string; semesters?: string[]; expanded?: boolean; initialDocumentId?: string;
}) {
  const contentId = useId();
  const [open, setOpen] = useState(expanded);
  const [selectedSemester, setSelectedSemester] = useState("");
  const scopedSemester = semester || selectedSemester || undefined;
  const [term, setTerm] = useState("");
  const [plans, setPlans] = useState<StudyPlan[]>([]);
  const [sources, setSources] = useState<PlanSources>({ documents: [], assignments: [] });
  const [input, setInput] = useState<PlanInput>(initialInput);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [draft, setDraft] = useState<PlanTopic[] | null>(null);
  const [settings, setSettings] = useState<PlanInput | null>(null);
  const [filter, setFilter] = useState("all");
  const [reload, setReload] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const content = useRef<HTMLDivElement | null>(null);
  const generation = useRef(0);
  const initialDocumentHandled = useRef(false);

  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    controller.current = abort;
    const version = ++generation.current;
    setBusy(true);
    setError("");
    setLoaded(false);
    setPlans([]);
    setSources({ documents: [], assignments: [] });
    setDraft(null);
    setSettings(null);
    setCreating(false);
    setInput(initialInput());
    Promise.all([
      getStudyPlans(userId, courseId, scopedSemester, abort.signal),
      getStudyPlanSources(userId, courseId, scopedSemester, abort.signal),
    ]).then(([result, available]) => {
      if (abort.signal.aborted || generation.current !== version) return;
      setPlans(result.plans);
      setTerm(result.semester);
      setSources(available);
      setSelected((previous) => result.plans.some((p) => p.id === previous) ? previous : result.plans[0]?.id || "");
      setLoaded(true);
      if (initialDocumentId && !initialDocumentHandled.current && available.documents.some((doc) => doc.id === initialDocumentId)) {
        initialDocumentHandled.current = true;
        setInput((previous) => ({ ...previous, document_ids: [initialDocumentId] }));
        setCreating(true);
      }
    }).catch((err) => {
      if (!abort.signal.aborted && generation.current === version) setError(message(err));
    }).finally(() => {
      if (!abort.signal.aborted && generation.current === version) setBusy(false);
    });
    return () => { abort.abort(); controller.current?.abort(); };
  }, [open, userId, courseId, scopedSemester, reload, initialDocumentId]);

  // Returning from a quiz/tutoring tab refreshes progress without generating
  // topics or changing the student's schedule.
  useEffect(() => {
    const onFocus = () => { if (open && !busy && !draft && !creating && !settings) setReload((n) => n + 1); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [open, busy, draft, creating, settings]);

  async function mutate(action: (signal: AbortSignal) => Promise<StudyPlan | { deleted: boolean }>, rollback?: StudyPlan) {
    if (busy) return;
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    const version = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await action(abort.signal);
      if (abort.signal.aborted || generation.current !== version) return;
      if ("deleted" in result) {
        const deletedId = plans.find((p) => p.id === selected)?.id || plans[0]?.id;
        setPlans((previous) => previous.filter((p) => p.id !== deletedId));
        setSelected("");
      } else {
        if ((creating || draft || settings) && content.current) content.current.scrollTop = 0;
        setPlans((previous) => [result, ...previous.filter((p) => p.id !== result.id)]);
        setSelected(result.id);
        setCreating(false);
        setDraft(null);
        setSettings(null);
      }
    } catch (err) {
      if (!abort.signal.aborted && generation.current === version) {
        if (rollback) setPlans((previous) => previous.map((p) => p.id === rollback.id ? rollback : p));
        setError(message(err));
      }
    } finally {
      if (!abort.signal.aborted && generation.current === version) setBusy(false);
    }
  }

  useEffect(() => () => controller.current?.abort(), []);

  const plan = plans.find((p) => p.id === selected) || plans[0];
  const save = (changes: PlanChanges) => {
    if (!plan || busy) return;
    if (changes.session) {
      const edit = changes.session;
      setPlans((previous) => previous.map((p) => p.id === plan.id ? {
        ...p, sessions: p.sessions.map((s) => s.id === edit.id ? { ...s, ...edit } : s),
      } : p));
    }
    void mutate((signal) => updateStudyPlan(userId, courseId, plan, changes, scopedSemester, signal), changes.session ? plan : undefined);
  };
  const chooseSource = (field: "document_ids" | "assignment_ids", id: string, checked: boolean) => {
    setInput((previous) => ({ ...previous, [field]: checked ? [...previous[field], id] : previous[field].filter((v) => v !== id) }));
  };

  return <SaplingSurface><section className={`${styles.panel} ${expanded ? styles.expanded : ""}`} data-testid="study-plan">
    {!expanded && <button data-testid="study-plan-toggle" className="btn btn--sm" type="button" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen(!open)}>
      {open ? "Hide study guide" : "Study guide"}
    </button>}
    {open && <div ref={content} id={contentId} className={styles.content} aria-busy={busy}>
      <div className={styles.toolbar}>
        {!expanded && <PageHeading title="Prepare for your next assessment" level={2} description="Plan your study time. Watch your topic progress grow as you practice." />}
        {!semester && semesters.length > 1 && <label>Semester
          <select value={selectedSemester} onChange={(e) => setSelectedSemester(e.target.value)} aria-label="Study plan semester">
            <option value="">Current or most recent</option>
            {semesters.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>}
        {term && <small>{term}</small>}
        <button className="btn btn--sm" disabled={busy} onClick={() => setReload((n) => n + 1)}>Refresh progress</button>
        {loaded && <button className="btn btn--sm" disabled={busy} onClick={() => { setCreating(true); setDraft(null); }}>New assessment</button>}
      </div>
      {busy && <p role="status">{creating ? "Building your plan…" : "Updating study plan…"}</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {loaded && !plans.length && !creating && <div className={styles.empty}>
        <h3>What are you preparing for?</h3>
        <p>Add a quiz or exam and choose the materials it covers. Sapling will suggest topics and a schedule before the assessment.</p>
        <button data-testid="study-plan-create" className="btn btn--sm" disabled={busy} onClick={() => setCreating(true)}>Create a study plan</button>
      </div>}
      {creating && <form className={styles.setup} onSubmit={(e) => {
        e.preventDefault();
        void mutate((signal) => createStudyPlan(userId, courseId, input, scopedSemester, signal));
      }}>
        <fieldset disabled={busy}>
          <legend>Assessment details</legend>
          <p className={styles.hint}>Your materials do not need a date. Enter your quiz or exam date below, then attach any relevant documents or assignments.</p>
          <label>Existing quiz or exam (optional)<select data-testid="study-plan-existing-assessment" defaultValue="" onChange={(e) => {
            const assessment = sources.assignments.find((a) => a.id === e.target.value);
            if (!assessment) return;
            setInput((previous) => ({ ...previous, title: previous.title || assessment.title,
              assessment_type: assessment.assignment_type as "exam" | "quiz",
              assessment_date: assessment.due_date?.slice(0, 10) || previous.assessment_date,
              assignment_ids: [...new Set([...previous.assignment_ids, assessment.id])],
            }));
          }}><option value="">Create my own assessment</option>{sources.assignments.filter((a) => ["exam", "quiz"].includes(a.assignment_type)).map((a) => <option key={a.id} value={a.id}>{a.title}{a.due_date ? ` · ${a.due_date.slice(0, 10)}` : " · Add date manually"}</option>)}</select></label>
          <div className={styles.fields}>
            <label>Assessment name<input data-testid="study-plan-title" required maxLength={120} value={input.title} onChange={(e) => setInput({ ...input, title: e.target.value })} placeholder="Biology midterm" /></label>
            <label>Type<select value={input.assessment_type} onChange={(e) => setInput({ ...input, assessment_type: e.target.value as "quiz" | "exam" })}><option value="exam">Exam</option><option value="quiz">Quiz</option></select></label>
            <label>Start studying<input type="date" required min={localDate()} value={input.start_date} onChange={(e) => setInput({ ...input, start_date: e.target.value })} /></label>
            <label>Assessment date<input data-testid="study-plan-exam-date" type="date" required min={offsetDate(input.start_date, 1)} value={input.assessment_date} onChange={(e) => setInput({ ...input, assessment_date: e.target.value })} /></label>
            <label>Minutes per study day<input type="number" required min={15} max={480} value={input.minutes_per_day} onChange={(e) => setInput({ ...input, minutes_per_day: Number(e.target.value) })} /></label>
          </div>
          <label>What does it cover?<textarea data-testid="study-plan-coverage" maxLength={4000} value={input.coverage} onChange={(e) => setInput({ ...input, coverage: e.target.value })} placeholder="Chapters 3–5: cell structure, membranes and transport" /></label>
          <p className={styles.hint}>Describe the coverage, select materials below, or use both. Topics are suggested from this context.</p>
        </fieldset>
        <fieldset disabled={busy}><legend>Available study days</legend><div className={styles.days}>
          {DAYS.map((day, index) => <label key={day}><input type="checkbox" checked={input.study_days.includes(index)} onChange={(e) => setInput({ ...input, study_days: e.target.checked ? [...input.study_days, index] : input.study_days.filter((d) => d !== index) })} />{day}</label>)}
        </div><small>Dates use {input.timezone}. The assessment day is reserved for the assessment.</small></fieldset>
        <fieldset disabled={busy}><legend>Relevant library materials</legend>
          {!sources.documents.length && <p>No documents in this course yet. You can describe coverage above.</p>}
          <div className={styles.sourceList}>{sources.documents.map((doc) => <label key={doc.id}><input type="checkbox" checked={input.document_ids.includes(doc.id)} onChange={(e) => chooseSource("document_ids", doc.id, e.target.checked)} />{doc.file_name}</label>)}</div>
        </fieldset>
        <fieldset disabled={busy}><legend>Related assignments</legend>
          {!sources.assignments.length && <p>No assignments available.</p>}
          <div className={styles.sourceList}>{sources.assignments.map((assignment) => <label key={assignment.id}><input type="checkbox" checked={input.assignment_ids.includes(assignment.id)} onChange={(e) => {
            chooseSource("assignment_ids", assignment.id, e.target.checked);
            if (e.target.checked && ["exam", "quiz"].includes(assignment.assignment_type)) {
              setInput((previous) => ({ ...previous, title: previous.title || assignment.title,
                assessment_date: previous.assessment_date || assignment.due_date?.slice(0, 10) || "",
                assessment_type: assignment.assignment_type as "exam" | "quiz" }));
            }
          }} />{assignment.title}{assignment.due_date ? ` · ${assignment.due_date.slice(0, 10)}` : ""}</label>)}</div>
        </fieldset>
        <div className={styles.actions}>
          <button data-testid="study-plan-generate" className="btn btn--sm" type="submit" disabled={busy || !input.study_days.length || !(input.coverage.trim() || input.document_ids.length || input.assignment_ids.length)}>Generate study plan</button>
          <button className="btn btn--sm" type="button" disabled={busy} onClick={() => setCreating(false)}>Cancel</button>
        </div>
      </form>}
      {plan && !creating && <>
        <div className={styles.toolbar}>
          <label>Assessment<select aria-label="Selected assessment" disabled={busy} value={plan.id} onChange={(e) => { setSelected(e.target.value); setDraft(null); setSettings(null); }}>
            {plans.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.assessment_date}</option>)}
          </select></label>
          <span>{plan.assessment_type === "exam" ? "Exam" : "Quiz"} · {plan.assessment_date}</span>
          <button className="btn btn--sm" disabled={busy} onClick={() => setSettings(settings ? null : {
            title: plan.title, assessment_type: plan.assessment_type, assessment_date: plan.assessment_date,
            start_date: plan.start_date, timezone: plan.timezone, coverage: plan.coverage,
            document_ids: plan.document_ids, assignment_ids: plan.assignment_ids,
            study_days: plan.study_days, minutes_per_day: plan.minutes_per_day,
          })}>{settings ? "Cancel timing changes" : "Edit dates and availability"}</button>
          <button className="btn btn--sm" disabled={busy} onClick={() => save({ regenerate: true })}>Replan unfinished work</button>
          <details><summary>Manage plan</summary><button className="btn btn--sm" disabled={busy} onClick={() => {
            if (window.confirm(`Delete the study plan for ${plan.title}?`)) void mutate((signal) => deleteStudyPlan(userId, courseId, plan.id, scopedSemester, signal));
          }}>Delete plan</button></details>
        </div>
        {settings && <form onSubmit={(e) => { e.preventDefault(); save({ settings }); }}>
          <fieldset disabled={busy}><legend>Dates and availability</legend>
            <div className={styles.fields}>
              <label>Assessment name<input required maxLength={120} value={settings.title} onChange={(e) => setSettings({ ...settings, title: e.target.value })} /></label>
              <label>Start studying<input type="date" required value={settings.start_date} onChange={(e) => setSettings({ ...settings, start_date: e.target.value })} /></label>
              <label>Assessment date<input type="date" required min={offsetDate(localDate(), 1)} value={settings.assessment_date} onChange={(e) => setSettings({ ...settings, assessment_date: e.target.value })} /></label>
              <label>Minutes per study day<input type="number" required min={15} max={480} value={settings.minutes_per_day} onChange={(e) => setSettings({ ...settings, minutes_per_day: Number(e.target.value) })} /></label>
            </div>
            <div className={styles.days}>{DAYS.map((day, index) => <label key={day}><input type="checkbox" checked={settings.study_days.includes(index)} onChange={(e) => setSettings({ ...settings, study_days: e.target.checked ? [...settings.study_days, index] : settings.study_days.filter((d) => d !== index) })} />{day}</label>)}</div>
            <p className={styles.hint}>Saving rebuilds unfinished sessions and keeps completed sessions.</p>
            <button type="submit" className="btn btn--sm" disabled={!settings.study_days.length}>Save dates and replan</button>
          </fieldset>
        </form>}
        {plan.warnings.map((warning) => <p key={warning} className={styles.hint}>{warning}</p>)}
        {plan.guide_overview && <section aria-label="Study guide overview"><h3>Your assessment guide</h3><p>{plan.guide_overview}</p></section>}
        <div className={styles.layout}>
          <section aria-label="Study schedule">
            <h3>Your study schedule</h3>
            <p className={styles.hint}>{plan.minutes_per_day} minutes per day · {plan.study_days.map((d) => DAYS[d]).join(", ")} · {plan.timezone}</p>
            <p className={styles.hint}>Session times are estimates. Finishing a session does not change topic mastery.</p>
            {!plan.sessions.length && <p>No sessions fit in the remaining study days. Review the coverage and availability.</p>}
            {[...new Set(plan.sessions.map((s) => s.scheduled_date))].map((day) => <div className={styles.day} key={day}>
              <h4>{day}{day === localDate() ? " · Today" : ""}{day < localDate() ? " · Past" : ""} <small>{plan.sessions.filter((s) => s.scheduled_date === day).reduce((n, s) => n + s.minutes, 0)} min</small></h4>
              {plan.sessions.filter((s) => s.scheduled_date === day).map((session) => {
                const topic = plan.topics.find((t) => t.id === session.topic_id);
                return <div className={styles.session} key={session.id}>
                  <label><input data-testid={`study-plan-session-${session.id}`} type="checkbox" disabled={busy} checked={session.completed} onChange={(e) => save({ session: { id: session.id, completed: e.target.checked } })} />
                    <span>{session.kind === "review" ? "Review" : "Study"}: {topic?.name}<small>{session.minutes} min{session.completed ? " · Session finished" : ""}</small></span>
                  </label>
                  <label className={styles.move}>Move session<input aria-label={`Move ${session.kind}: ${topic?.name}`} type="date" disabled={busy} min={localDate() > plan.start_date ? localDate() : plan.start_date} max={offsetDate(plan.assessment_date, -1)} value={session.scheduled_date} onChange={(e) => {
                    if (e.target.value) save({ session: { id: session.id, scheduled_date: e.target.value } });
                  }} /></label>
                </div>;
              })}
            </div>)}
          </section>
          <section aria-label="Assessment topic checklist">
            <h3>Topics and study guide</h3>
            <p>{plan.mastered_count} of {plan.topics.length} mastered</p>
            <progress aria-label="Topics mastered" max={plan.topics.length} value={plan.mastered_count} />
            <p className={styles.hint}>Progress updates from your course practice and quiz results. Topics without evidence stay unassessed.</p>
            <div className={styles.actions}>
              <label>Show topics<select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">All topics</option>{Object.entries(LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <button className="btn btn--sm" disabled={busy} onClick={() => setDraft(draft ? null : editableTopics(plan))}>{draft ? "Cancel editing" : "Edit topics"}</button>
            </div>
            {draft ? <form onSubmit={(e) => { e.preventDefault(); save({ topics: draft }); }}>
              <p className={styles.hint}>Saving rebuilds unfinished sessions. Completed sessions are retained for topics you keep. Renaming a topic may change its mastery match.</p>
              {draft.map((topic, index) => <div className={styles.topicEdit} key={topic.id}>
                <label>Topic name<input required maxLength={120} value={topic.name} disabled={busy} onChange={(e) => setDraft(draft.map((t, i) => i === index ? { ...t, name: e.target.value } : t))} /></label>
                <label>Description<textarea maxLength={500} value={topic.description} disabled={busy} onChange={(e) => setDraft(draft.map((t, i) => i === index ? { ...t, description: e.target.value } : t))} /></label>
                <button type="button" className="btn btn--sm" disabled={busy || draft.length === 1} onClick={() => setDraft(draft.filter((t) => t.id !== topic.id).map((t) => ({ ...t, parent_id: t.parent_id === topic.id ? null : t.parent_id, prerequisite_ids: t.prerequisite_ids.filter((id) => id !== topic.id) })))}>Remove {topic.name}</button>
              </div>)}
              <div className={styles.actions}>
                <button type="button" className="btn btn--sm" disabled={busy || draft.length >= 60} onClick={() => setDraft([...draft, { id: crypto.randomUUID().replaceAll("-", ""), name: "", description: "", parent_id: null, prerequisite_ids: [], source_ids: [], importance: 0.5 }])}>Add topic</button>
                <button type="submit" className="btn btn--sm" disabled={busy}>Save topics and replan</button>
              </div>
            </form> : <>
              {[null, ...plan.topics.filter((t) => plan.topics.some((child) => child.parent_id === t.id)).map((t) => t.id)].map((parentId) => {
                const topics = plan.topics.filter((t) => t.parent_id === parentId && (filter === "all" || t.status === filter));
                if (!topics.length) return null;
                return <details key={parentId || "root"} open className={styles.group}><summary>{parentId ? plan.topics.find((t) => t.id === parentId)?.name : "Core topics"}</summary>
                  <ul>{topics.map((topic) => <li key={topic.id} data-testid={`study-plan-topic-${topic.id}`}>
                    <div className={styles.topicHeading}><span aria-label={`${topic.name}: ${LABELS[topic.status]}`}>{topic.checked ? "✓" : "○"}</span><strong>{topic.name}</strong><small>{LABELS[topic.status]}</small></div>
                    {topic.mastery_score !== null && <progress aria-label={`${topic.name} mastery`} max={1} value={topic.mastery_score} />}
                    <p>{topic.description}</p>
                    {!!topic.study_points?.length && <ul aria-label={`What to study: ${topic.name}`} style={{ listStyle: "disc", paddingLeft: 20, marginBottom: 12 }}>
                      {topic.study_points.map((point, index) => <li key={index} style={{ padding: "4px 0" }}>{point}</li>)}
                    </ul>}
                    {!!topic.source_ids.length && <small>Sources: {topic.source_ids.map((id) => plan.sources.find((s) => s.id === id)?.label).filter(Boolean).join(", ")}</small>}
                  </li>)}</ul>
                </details>;
              })}
              {!plan.topics.some((t) => filter === "all" || t.status === filter) && <p>No topics match this view.</p>}
            </>}
          </section>
        </div>
      </>}
    </div>}
  </section></SaplingSurface>;
}
