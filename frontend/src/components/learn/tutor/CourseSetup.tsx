"use client";
// Course setup (Tutor redesign, behind `course_setup`; design:
// learn/__fixtures__/setup.design.html, the Claude Design board), opened from
// the Tutor's course page. Four steps: Course (already chosen: the setup opens
// on a course), Syllabus (upload it, or skip to review what is there), Review
// and Done.
//
// Review is the board: the course's exams and assignments, each a milestone
// with its countdown (fix a date, remove one, add one), and the course's
// concepts, each ticked (untick the ones that aren't part of the course).
// The upload has already written the syllabus's dated work to the calendar
// (services/documents/persistence.py), so Confirm writes only the CHANGES,
// through the calendar's routes, with the Study hub's date rules
// (components/study/hubModel.ts: planDates). Unticked concepts go to
// /api/learn/setup (services/course_setup.py), which deletes them and keeps
// them out of later uploads; a concept the student has started cannot be
// unticked here and stays.
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useUser } from "@/context/UserContext";
import {
  deleteAssignment, fetchJSON, getAllAssignments, saveAssignments, updateAssignment, uploadSyllabus,
  type EnrolledCourse,
} from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { humanizeError } from "@/lib/errorMessage";
import { plural } from "@/lib/learningCopy";
import { assessmentsForCourse, draftsOf, newDraft, planDates, saveOutcome, type DatesPlan, type Draft, type SaveReply } from "../../study/hubModel";
import { classifyAssessment, type Assessment } from "../../study/studyModel";
import { invalidateMilestones } from "./milestones";
import styles from "./CourseSetup.module.css";

export const SETUP_COPY = {
  stepsLabel: "Setup steps",
  steps: ["Course", "Syllabus", "Review", "Done"],
  done: "done",
  entry: "Set up from syllabus",
  uploadTitle: (course: string) => `Upload your ${course} syllabus`,
  uploadLine: "We'll find its exams, assignments and concepts, and you check them next.",
  choose: "Choose your syllabus",
  fileLabel: "Syllabus file",
  skip: "Skip: review what's here",
  reading: "Reading your syllabus. This can take a minute.",
  found: (course: string) => `Here's what we found in your ${course} syllabus`,
  review: (course: string) => `Review ${course}`,
  loading: "Loading your course…",
  loadFailed: "Couldn't load your course's dates.",
  retry: "Try again",
  dates: "Exams and assignments",
  datesLine: "Each becomes a milestone with a countdown. Fix any date before you confirm.",
  noDates: "No dates yet. Add the exams and assignments you know.",
  date: (name: string) => (name ? `${name} date` : "Date"),
  name: "Name",
  remove: "Remove",
  removeNew: "Remove new date",
  addDate: "Add a date",
  concepts: (n: number) => plural(n, "concept"),
  conceptsLine: "Your tutor teaches and checks these. Untick any that aren't part of your course.",
  noConcepts: "No concepts yet. They appear as you upload lectures and notes.",
  startedStay: "Concepts you've started stay in the course.",
  practice: "Practice questions are being written from your lectures. You can start learning now.",
  confirm: "Confirm",
  saving: "Saving…",
  saveFailed: (why: string) => `Couldn't save: ${why}`,
  doneTitle: (course: string) => `${course} is set up`,
  doneLine: (dates: number, concepts: number) =>
    `${plural(dates, "milestone")} with a countdown and ${plural(concepts, "concept")} for your tutor.`,
  kept: (n: number) => `${plural(n, "concept")} you had started ${n === 1 ? "stays" : "stay"} in the course.`,
  start: "Start learning",
  back: (course: string) => `Back to ${course}`,
} as const;

/** The setup's one write of its own: take these concepts out of the course. */
export const excludeConcepts = (userId: string, courseId: string, nodeIds: string[]) =>
  fetchJSON<{ removed: string[]; kept: string[] }>("/api/learn/setup/exclude-concepts", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, course_id: courseId, node_ids: nodeIds }),
  });

/** A concept the student has started (it has a measure): setup keeps it. */
export const startedConcept = (n: GraphNode): boolean => n.mastery_tier !== "unexplored";

type Step = "syllabus" | "review" | "done";
const STEP_AT: Record<Step, number> = { syllabus: 1, review: 2, done: 3 };

function Steps({ at }: { at: number }) {
  return (
    <ol aria-label={SETUP_COPY.stepsLabel} className={styles.steps} data-testid="tutor-setup-steps">
      {SETUP_COPY.steps.map((name, i) => (
        <React.Fragment key={name}>
          {i > 0 && <li aria-hidden className={styles.rule} />}
          <li aria-current={i === at ? "step" : undefined} className={i === at ? styles.stepOn : styles.step}>
            <span className={i === at ? styles.dotOn : i < at ? styles.dotDone : styles.dot} aria-hidden>{i + 1}</span>
            {name}{i < at && <span className={styles.srOnly}> ({SETUP_COPY.done})</span>}
          </li>
        </React.Fragment>
      ))}
    </ol>
  );
}

/** The course's dated work as the review opens on it; null while loading. */
function useOpenedDates(userId: string, courseId: string, enabled: boolean) {
  const [state, setState] = useState<{ opened: Map<string, Assessment> | null; failed: boolean }>({ opened: null, failed: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled || !userId) return;
    let live = true;
    getAllAssignments(userId)
      .then((r) => {
        if (!live) return;
        setState({ opened: new Map(assessmentsForCourse(r.assignments ?? [], courseId).map((a) => [a.id, a])), failed: false });
      })
      .catch(() => { if (live) setState({ opened: null, failed: true }); });
    return () => { live = false; };
  }, [enabled, userId, courseId, attempt]);
  const retry = () => { setState({ opened: null, failed: false }); setAttempt((n) => n + 1); };
  return { ...state, retry };
}

/** Removals, edits, then new rows: the calendar's order (the Study hub's). */
async function writeDates(plan: DatesPlan, userId: string, courseId: string): Promise<SaveReply | null> {
  for (const id of plan.remove) await deleteAssignment(id, userId);
  for (const u of plan.update) await updateAssignment(u.id, userId, u.patch);
  if (!plan.add.length) return null;
  return saveAssignments(userId, plan.add.map((a) => ({ ...a, course_id: courseId })));
}

function SyllabusStep({ busy, error, onFile, onSkip }: {
  busy: boolean; error: string | null;
  onFile: (file: File) => void; onSkip: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <section className={styles.card} aria-labelledby="tutor-setup-title">
      <p className={styles.sub}>{SETUP_COPY.uploadLine}</p>
      <input ref={input} type="file" accept=".pdf,.docx,.pptx" className={styles.srOnly} tabIndex={-1}
        aria-label={SETUP_COPY.fileLabel} data-testid="tutor-setup-file"
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onFile(f); }} />
      <div className={styles.actions}>
        <button type="button" className="btn btn--primary" disabled={busy} data-testid="tutor-setup-choose"
          onClick={() => input.current?.click()}>{SETUP_COPY.choose}</button>
        <button type="button" className={styles.quiet} disabled={busy} data-testid="tutor-setup-skip" onClick={onSkip}>
          {SETUP_COPY.skip}
        </button>
      </div>
      <p role="status" className={styles.sub} data-testid="tutor-setup-status">{busy ? SETUP_COPY.reading : ""}</p>
      {error && <p role="alert" className={styles.error} data-testid="tutor-setup-error">{error}</p>}
    </section>
  );
}

function DateRows({ drafts, newName, addRef, onChange, onRemove, onAdd }: {
  drafts: Draft[];
  newName: React.RefObject<HTMLInputElement | null>;
  addRef: React.RefObject<HTMLButtonElement | null>;
  onChange: (id: string, patch: Partial<Draft>) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
}) {
  const lastNew = [...drafts].reverse().find((d) => d.isNew)?.id;
  return (
    <section className={styles.card} aria-labelledby="tutor-setup-dates">
      <h3 id="tutor-setup-dates" className={`h-serif ${styles.h3}`}>{SETUP_COPY.dates}</h3>
      <p className={styles.sub}>{drafts.length ? SETUP_COPY.datesLine : SETUP_COPY.noDates}</p>
      {drafts.length > 0 && (
        <ul className={styles.dates}>
          {drafts.map((d) => {
            const dateId = `tutor-setup-date-${d.id}`;
            const label = d.title.trim();
            return (
              <li key={d.id} className={styles.dateRow} data-testid={`tutor-setup-row-${d.id}`}>
                {d.isNew ? (
                  <input ref={d.id === lastNew ? newName : undefined} type="text" value={d.title} maxLength={200}
                    aria-label={SETUP_COPY.name} placeholder={SETUP_COPY.name} className={styles.input}
                    data-testid={`tutor-setup-name-${d.id}`}
                    onChange={(e) => onChange(d.id, { title: e.target.value, type: classifyAssessment("", e.target.value) })} />
                ) : <label htmlFor={dateId} className={styles.dateName}>{d.title}</label>}
                <input id={dateId} type="date" value={d.iso} required className={styles.input} data-testid={dateId}
                  aria-label={d.isNew ? SETUP_COPY.date(label) : undefined}
                  onChange={(e) => { if (e.target.value) onChange(d.id, { iso: e.target.value }); }} />
                <button type="button" className={styles.remove} aria-label={label ? `${SETUP_COPY.remove} ${label}` : SETUP_COPY.removeNew}
                  data-testid={`tutor-setup-remove-${d.id}`} onClick={() => onRemove(d.id)}>{SETUP_COPY.remove}</button>
              </li>
            );
          })}
        </ul>
      )}
      <button ref={addRef} type="button" className={`btn ${styles.add}`} data-testid="tutor-setup-add-date" onClick={onAdd}>
        {SETUP_COPY.addDate}
      </button>
    </section>
  );
}

function ConceptChips({ nodes, unticked, onToggle }: {
  nodes: GraphNode[]; unticked: ReadonlySet<string>; onToggle: (id: string) => void;
}) {
  const anyStarted = nodes.some(startedConcept);
  return (
    <section className={styles.card} aria-labelledby="tutor-setup-concepts">
      <h3 id="tutor-setup-concepts" className={`h-serif ${styles.h3}`}>{SETUP_COPY.concepts(nodes.length - unticked.size)}</h3>
      <p className={styles.sub}>{nodes.length ? SETUP_COPY.conceptsLine : SETUP_COPY.noConcepts}</p>
      {nodes.length > 0 && (
        <ul className={styles.chips}>
          {nodes.map((n) => {
            const started = startedConcept(n);
            const on = !unticked.has(n.id);
            return (
              <li key={n.id}>
                <label className={on ? styles.chip : styles.chipOff} data-testid={`tutor-setup-concept-${n.id}`}>
                  <input type="checkbox" checked={on} disabled={started} onChange={() => onToggle(n.id)} />
                  {n.name}
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {anyStarted && <p className={styles.sub}>{SETUP_COPY.startedStay}</p>}
    </section>
  );
}

type Done = { dates: number; concepts: number; kept: number; note: string | null };

export function CourseSetup({ course, concepts, hasMaterials, onClose, onStart, onConceptsChanged }: {
  course: EnrolledCourse;
  /** The course's concepts (subject roots left out), as the course page has them. */
  concepts: GraphNode[];
  /** The course has material the loop drafts practice questions from. */
  hasMaterials: boolean;
  onClose: () => void;
  onStart: () => void;
  /** Re-read the graph (after the upload added concepts, after Confirm removed some). */
  onConceptsChanged: () => Promise<void> | void;
}) {
  const { userId } = useUser();
  const courseName = course.course_code || course.course_name;
  const [step, setStep] = useState<Step>("syllabus");
  const [uploaded, setUploaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dates = useOpenedDates(userId, course.course_id, step === "review");
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [unticked, setUnticked] = useState<Set<string>>(() => new Set());
  const [done, setDone] = useState<Done | null>(null);
  const datesWritten = useRef<SaveReply | null | undefined>(undefined);
  const heading = useRef<HTMLHeadingElement>(null);
  const newName = useRef<HTMLInputElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const focusNew = useRef(false);
  const nodes = concepts.filter((n) => !n.is_subject_root && (!n.course_id || n.course_id === course.course_id));

  // spec §13 A135: each step replaces what was on screen, so its heading takes focus.
  useLayoutEffect(() => { heading.current?.focus({ preventScroll: true }); }, [step]);
  useEffect(() => {
    if (dates.opened && drafts === null) setDrafts(draftsOf([...dates.opened.values()]));
  }, [dates.opened, drafts]);
  useEffect(() => {
    if (!focusNew.current) return;
    focusNew.current = false;
    newName.current?.focus();
  }, [drafts]);

  const onFile = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      await uploadSyllabus({ userId, courseId: course.course_id, file });
      invalidateMilestones(); // the upload wrote the syllabus's dates
      await onConceptsChanged();
      setUploaded(true);
      setStep("review");
    } catch (err) {
      setError(`Upload failed: ${humanizeError(err, "Try again.")}`);
    } finally {
      setBusy(false);
    }
  };

  const change = (id: string, patch: Partial<Draft>) => setDrafts((ds) => (ds ?? []).map((d) => (d.id === id ? { ...d, ...patch } : d)));
  const remove = (id: string) => {
    setDrafts((ds) => (ds ?? []).filter((d) => d.id !== id));
    requestAnimationFrame(() => addRef.current?.focus()); // the row and its button are gone
  };
  const add = () => {
    focusNew.current = true;
    setDrafts((ds) => [...(ds ?? []), newDraft(new Date(), (ds ?? []).length)]);
  };
  const toggle = (id: string) => setUnticked((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const confirm = async () => {
    if (!drafts || !dates.opened) return;
    setBusy(true);
    setError(null);
    try {
      const plan = planDates(drafts, dates.opened);
      // A retry after a failed concept write does not write the dates twice.
      if (datesWritten.current === undefined) {
        datesWritten.current = await writeDates(plan, userId, course.course_id);
        invalidateMilestones();
      }
      const outcome = saveOutcome(plan, datesWritten.current);
      const removing = [...unticked].filter((id) => nodes.some((n) => n.id === id && !startedConcept(n)));
      const result = removing.length ? await excludeConcepts(userId, course.course_id, removing) : { removed: [], kept: [] };
      if (removing.length) await onConceptsChanged();
      const added = datesWritten.current?.saved_count ?? plan.add.length;
      setDone({
        dates: dates.opened.size - plan.remove.length + added,
        concepts: nodes.length - result.removed.length,
        kept: result.kept.length,
        note: outcome.saved ? null : outcome.message,
      });
      setStep("done");
    } catch (err) {
      setError(SETUP_COPY.saveFailed(humanizeError(err, "Try again.")));
    } finally {
      setBusy(false);
    }
  };

  const title = step === "syllabus" ? SETUP_COPY.uploadTitle(courseName)
    : step === "review" ? (uploaded ? SETUP_COPY.found(courseName) : SETUP_COPY.review(courseName))
      : SETUP_COPY.doneTitle(courseName);
  return (
    <div className={styles.page} data-testid="tutor-setup" data-step={step}>
      <div className={styles.col}>
        <button type="button" className={styles.back} onClick={onClose} aria-label={SETUP_COPY.back(courseName)}
          data-testid="tutor-setup-back">{courseName}</button>
        <Steps at={STEP_AT[step]} />
        <h2 id="tutor-setup-title" ref={heading} tabIndex={-1} className={`h-serif ${styles.title}`}>{title}</h2>
        {step === "syllabus" && (
          <SyllabusStep busy={busy} error={error} onFile={(f) => void onFile(f)}
            onSkip={() => setStep("review")} />
        )}
        {step === "review" && (dates.failed ? (
          <p role="alert" className={styles.error} data-testid="tutor-setup-load-failed">
            {SETUP_COPY.loadFailed}{" "}
            <button type="button" className={styles.quiet} onClick={dates.retry}>{SETUP_COPY.retry}</button>
          </p>
        ) : drafts === null ? (
          <p role="status" className={styles.sub}>{SETUP_COPY.loading}</p>
        ) : (
          <>
            <DateRows drafts={drafts} newName={newName} addRef={addRef} onChange={change} onRemove={remove} onAdd={add} />
            <ConceptChips nodes={nodes} unticked={unticked} onToggle={toggle} />
            <div className={styles.foot}>
              <p className={styles.footLine}>{hasMaterials || uploaded ? SETUP_COPY.practice : ""}</p>
              <button type="button" className="btn btn--primary" disabled={busy} data-testid="tutor-setup-confirm"
                onClick={() => void confirm()}>{busy ? SETUP_COPY.saving : SETUP_COPY.confirm}</button>
            </div>
            {error && <p role="alert" className={styles.error} data-testid="tutor-setup-error">{error}</p>}
          </>
        ))}
        {step === "done" && done && (
          <section className={styles.card} aria-labelledby="tutor-setup-title" data-testid="tutor-setup-done">
            <p className={styles.sub}>{SETUP_COPY.doneLine(done.dates, done.concepts)}</p>
            {done.kept > 0 && <p className={styles.sub}>{SETUP_COPY.kept(done.kept)}</p>}
            {done.note && <p className={styles.error}>{done.note}</p>}
            <div className={styles.actions}>
              <button type="button" className="btn btn--primary" data-testid="tutor-setup-start" onClick={onStart}>{SETUP_COPY.start}</button>
              <button type="button" className={styles.quiet} onClick={onClose}>{SETUP_COPY.back(courseName)}</button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
