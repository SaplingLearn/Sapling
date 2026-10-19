"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Check, ChevronDown, LockKeyhole, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { BotanicalIcon, SaplingWordmark } from "@/components/sapling";
import { DocumentUploadModal, type UploadItem } from "@/components/DocumentUploadModal";
import Dialog from "@/components/Dialog";
import { deleteDocument, getCourses, getDocuments, getGraph, getMe, onboardingCoursesSearch, submitOnboardingProfile, type EnrolledCourse, type OnboardingCourse } from "@/lib/api";
import { onboardingRedirect } from "@/lib/localSeed";
import { hrefOnboardingLearning, readOnboardingIntent, writeOnboardingIntent } from "@/lib/onboardingHandoff";
import { academicChoices, canContinueOnboarding, emptyOnboardingDraft, readOnboardingDraft, writeOnboardingDraft, YEARS, type OnboardingDraft, type OnboardingStep } from "./Onboarding.state";
import "@/components/sapling/sapling.css";
import styles from "./Onboarding.module.css";

const STEPS = ["PROFILE", "ACADEMIC CONTEXT", "COURSES", "MATERIALS · OPTIONAL", "GOAL", "CHECK-IN"];
const HEADINGS = ["Welcome to Sapling.", "What are you studying?", "Connect your courses.", "Bring your course materials.", "What would you like to work toward?", "Ready for your first check-in."];
const SUBTITLES = ["First, what should we call you?", "A little context helps keep your courses together.", "Choose at least one. You can add more later.", "Add a file now, or come back to it in Library.", "Choose your scope, then put the goal in your own words.", "Your answers help us choose a starting point."];
interface Concept { id: string; name: string; courseId: string }

/** Six native Pen screens share one full-page canvas, outside the app shell. */
export function Onboarding() {
  const router = useRouter();
  const { userId, userReady, isAuthenticated, signOut, refreshProfile } = useUser();
  const [draft, setDraft] = useState<OnboardingDraft | null>(null);
  const [identityError, setIdentityError] = useState("");
  const [identityRetry, setIdentityRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedLocally, setSavedLocally] = useState(false);
  const [enrolled, setEnrolled] = useState<EnrolledCourse[]>([]);
  const [enrollmentError, setEnrollmentError] = useState("");
  const [enrollmentRetry, setEnrollmentRetry] = useState(0);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [conceptError, setConceptError] = useState("");
  const [conceptRetry, setConceptRetry] = useState(0);
  const [editingConcepts, setEditingConcepts] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [exitOpen, setExitOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const identityRef = useRef(userId);
  identityRef.current = userId;
  const submitLock = useRef(false);

  // Confirm the cookie-backed account before reading any personal local draft.
  useEffect(() => {
    if (!userReady) return;
    if (!isAuthenticated || !userId) { router.replace("/"); return; }
    let cancelled = false;
    setDraft(null);
    setIdentityError("");
    setEnrolled([]);
    setConcepts([]);
    setError("");
    setUploadOpen(false);
    setExitOpen(false);
    setEditingConcepts(false);
    submitLock.current = false;
    setBusy(false);
    void (async () => {
      try {
        const me = await getMe();
        if (cancelled) return;
        if (me.user_id !== userId) throw new Error("Your account changed. Refresh this page to continue with the signed-in account.");
        const checkpoint = readOnboardingDraft(me.user_id);
        if (!checkpoint) {
          if (me.onboarding_completed) { router.replace("/dashboard"); return; }
          const route = await onboardingRedirect();
          if (cancelled) return;
          if (route) { router.replace(route); return; }
        }
        setDraft(checkpoint ? (!me.onboarding_completed && checkpoint.requiredSaved ? { ...checkpoint, requiredSaved: false, step: 2 } : checkpoint) : emptyOnboardingDraft(me.user_id, me.name));
      } catch (err) {
        if (!cancelled) setIdentityError(err instanceof Error ? err.message : "We couldn't confirm your account. Your saved draft is kept.");
      }
    })();
    return () => { cancelled = true; };
  }, [userId, userReady, isAuthenticated, identityRetry, router]);

  useEffect(() => {
    if (!draft || draft.userId !== userId) return;
    setSavedLocally(writeOnboardingDraft(draft));
  }, [draft, userId]);

  const step = draft?.step ?? 0;
  const requiredSaved = draft?.requiredSaved ?? false;
  const draftUserId = draft?.userId;
  const hydrated = Boolean(draft);
  useEffect(() => { if (hydrated) headingRef.current?.focus(); }, [step, hydrated]);

  useEffect(() => {
    if (!draftUserId || !requiredSaved) return;
    let cancelled = false;
    setEnrollmentError("");
    void getCourses(draftUserId).then(response => {
      if (cancelled) return;
      const courses = dedupeCourses(response.courses);
      setEnrolled(courses);
      setDraft(current => {
        if (!current || current.userId !== draftUserId) return current;
        if (courses.some(course => course.course_id === current.goalCourseId)) return current;
        return { ...current, goalCourseId: courses[0]?.course_id ?? "", goalTargets: [], goalScope: "course", handoffId: undefined };
      });
      if (courses.length === 0) setEnrollmentError("No enrolled courses were found. Go back to Courses and retry your selection.");
    }).catch(() => { if (!cancelled) setEnrollmentError("We couldn't confirm your courses. Your profile is saved; retry to continue setup."); });
    return () => { cancelled = true; };
  }, [draftUserId, requiredSaved, enrollmentRetry]);

  const needsConcepts = step >= 4;
  useEffect(() => {
    if (!draftUserId || !requiredSaved || !needsConcepts) return;
    let cancelled = false;
    setConceptLoading(true);
    setConceptError("");
    void getGraph(draftUserId).then(response => {
      if (cancelled) return;
      const next: Concept[] = response.nodes.flatMap(node =>
        typeof node.id === "string" && typeof node.course_id === "string" && !node.is_subject_root && node.mastery_tier !== "subject_root" && typeof node.concept_name === "string"
          ? [{ id: node.id, name: node.concept_name, courseId: node.course_id }] : []);
      setConcepts(next);
      setDraft(current => {
        if (!current || current.userId !== draftUserId) return current;
        const valid = new Set(next.filter(node => node.courseId === current.goalCourseId).map(node => node.id));
        const targets = current.goalTargets.filter(id => valid.has(id));
        return targets.length === current.goalTargets.length ? current : { ...current, goalTargets: targets, step: 4, handoffId: undefined };
      });
    }).catch(() => { if (!cancelled) setConceptError("We couldn't load this course's concepts. Your objective is kept."); })
      .finally(() => { if (!cancelled) setConceptLoading(false); });
    return () => { cancelled = true; };
  }, [draftUserId, requiredSaved, needsConcepts, conceptRetry]);

  const update = useCallback((patch: Partial<OnboardingDraft>, requiredChange = false) => {
    setError("");
    setDraft(current => current ? { ...current, ...patch, handoffId: undefined, ...(requiredChange ? { requiredSaved: false } : {}) } : current);
  }, []);
  const go = (next: OnboardingStep) => update({ step: next });

  const saveProfile = async () => {
    if (!draft || submitLock.current) return;
    if (requiredSaved) { go(3); return; }
    submitLock.current = true;
    setBusy(true);
    setError("");
    const savingUser = draft.userId;
    let profileWritten = false;
    try {
      const response = await submitOnboardingProfile({ user_id: savingUser, first_name: draft.firstName.trim(), last_name: draft.lastName.trim(), year: draft.year, majors: academicChoices(draft.majorsText), minors: academicChoices(draft.minorsText), course_ids: draft.courseIds });
      profileWritten = true;
      const [coursesResponse, me] = await Promise.all([getCourses(savingUser), getMe()]);
      if (identityRef.current !== savingUser) return;
      if (response.user_id !== savingUser || me.user_id !== savingUser) throw new Error("Your signed-in account changed. Refresh before continuing.");
      const courses = dedupeCourses(coursesResponse.courses);
      setEnrolled(courses);
      const confirmed = new Set(courses.map(course => course.course_id));
      const linked = new Set(response.courses_linked);
      const missing = draft.courseIds.filter(id => !confirmed.has(id) || !linked.has(id));
      if (missing.length > 0) {
        const names = missing.map(id => draft.courseCache.find(course => course.id === id)?.course_code ?? "a selected course");
        setError(`Your profile was saved, but ${names.join(", ")} could not be confirmed as enrolled. Retry or change your selection; your choices are kept.`);
        return;
      }
      if (!me.onboarding_completed) throw new Error("The server hasn't confirmed profile completion yet. Please retry.");
      await refreshProfile();
      if (identityRef.current !== savingUser) return;
      setDraft(current => current?.userId === savingUser ? { ...current, requiredSaved: true, step: 3, goalCourseId: courses.some(c => c.course_id === current.goalCourseId) ? current.goalCourseId : draft.courseIds[0], goalTargets: [], goalScope: "course" } : current);
    } catch (err) {
      if (identityRef.current === savingUser) setError(`${profileWritten ? "Your profile may already be saved. We couldn't confirm all courses. " : ""}${err instanceof Error ? err.message : "Couldn't save setup. Please retry."} Your choices are kept.`);
    } finally {
      submitLock.current = false;
      if (identityRef.current === savingUser) setBusy(false);
    }
  };

  const onUploadComplete = (items: UploadItem[]) => {
    const uploadOwner = draft?.userId;
    if (!uploadOwner || identityRef.current !== uploadOwner) return;
    const saved = items.filter(item => item.status === "processed" && item.docId).map(item => ({ id: item.docId!, name: item.file.name, courseId: item.courseId, size: item.file.size }));
    setDraft(current => current?.userId === uploadOwner ? { ...current, materials: [...new Map([...current.materials, ...saved].map(item => [item.id, item])).values()] } : current);
    setConceptRetry(value => value + 1);
    setEnrollmentRetry(value => value + 1);
  };

  const begin = () => {
    if (!draft || busy || submitLock.current) return;
    if (!enrolled.some(course => course.course_id === draft.goalCourseId)) { setError("Confirm an enrolled course before starting your check-in."); return; }
    if (draft.goalScope === "concepts" && (conceptLoading || conceptError || draft.goalTargets.some(id => !concepts.some(node => node.id === id && node.courseId === draft.goalCourseId)))) { setError("Reload and confirm your target concepts before starting."); return; }
    const goal = draft.goalScope === "course" ? null : { text: draft.objective.trim(), target_node_ids: draft.goalTargets };
    if (!writeOnboardingIntent({ userId: draft.userId, courseId: draft.goalCourseId, goal })) { setError("Your browser couldn't keep this learning handoff. Allow session storage and try again; your setup is saved."); return; }
    const intent = readOnboardingIntent(draft.userId, draft.goalCourseId);
    if (intent) writeOnboardingDraft({ ...draft, handoffId: intent.id });
    submitLock.current = true;
    setBusy(true);
    // Keep the scoped checkpoint for stale-goal correction and failed starts.
    // The learning controller clears it only after applying this intent.
    router.push(hrefOnboardingLearning(draft.goalCourseId));
  };

  const continueStep = () => {
    if (!draft || !canContinueOnboarding(draft) || busy) return;
    if (step === 2) void saveProfile();
    else if (step === 5) begin();
    else go((step + 1) as OnboardingStep);
  };
  const exit = async () => {
    if (requiredSaved) { router.push("/dashboard"); return; }
    await signOut();
    router.replace("/");
  };

  const course = enrolled.find(value => value.course_id === draft?.goalCourseId);
  const courseConcepts = useMemo(() => concepts.filter(node => node.courseId === draft?.goalCourseId), [concepts, draft?.goalCourseId]);
  const targetNames = courseConcepts.filter(node => draft?.goalTargets.includes(node.id)).map(node => node.name);
  const validGoal = step !== 4 || (enrolled.some(c => c.course_id === draft?.goalCourseId) && !enrollmentError && (draft?.goalScope === "course" || (!conceptLoading && !conceptError && targetNames.length === draft?.goalTargets.length)));

  if (!draft || draft.userId !== userId) return (
    <main className={`sapling-surface ${styles.canvas}`} data-testid="onboarding-gate">
      <header className={styles.header}><SaplingWordmark width={130} /></header>
      <div className={styles.loading} role={identityError ? "alert" : "status"}>
        <h1>{identityError ? "Let's reconnect." : "Opening your learning space…"}</h1>
        {identityError && <><p>{identityError}</p><button data-testid="onboarding-identity-retry" className={styles.primary} onClick={() => setIdentityRetry(value => value + 1)}>Retry</button></>}
      </div>
    </main>
  );

  return (
    <main className={`sapling-surface ${styles.canvas}`} data-testid="onboarding-gate" data-step={step + 1} onKeyDown={event => {
      if (event.key === "Escape" && !uploadOpen && !exitOpen && !busy) { event.preventDefault(); setExitOpen(true); }
    }}>
      <header className={styles.header}><SaplingWordmark width={130} /><button className={styles.finishLater} data-testid="onboarding-close" onClick={() => setExitOpen(true)} disabled={busy}>Finish later</button></header>
      <div className={styles.progressArea}>
        <div role="progressbar" aria-label="Onboarding progress" aria-valuemin={1} aria-valuemax={6} aria-valuenow={step + 1} className={styles.track}><span style={{ width: `${(step + 1) / 6 * 100}%` }} /></div>
        <p className={styles.stepLabel} data-testid="onboarding-step">{String(step + 1).padStart(2, "0")} / 06 · {STEPS[step]}</p>
      </div>
      <div className={styles.intro}><h1 ref={headingRef} tabIndex={-1}>{HEADINGS[step]}</h1><p>{SUBTITLES[step]}</p></div>
      <form className={`${styles.form} ${styles[`step${step}`]}`} onSubmit={event => { event.preventDefault(); continueStep(); }}>
        <fieldset className={styles.fields} disabled={busy}>
          {step === 0 && <>
            <div className={styles.names}>
              <Field label="First name" htmlFor="onboarding-first-name"><input id="onboarding-first-name" data-testid="onboarding-first-name" autoComplete="given-name" value={draft.firstName} onChange={event => update({ firstName: event.target.value }, true)} required maxLength={100} /></Field>
              <Field label="Last name" htmlFor="onboarding-last-name"><input id="onboarding-last-name" data-testid="onboarding-last-name" autoComplete="family-name" value={draft.lastName} onChange={event => update({ lastName: event.target.value }, true)} required maxLength={100} /></Field>
            </div>
            <div className={styles.benefits}><Benefit icon="learn" title="A clear next step" detail="Connect your courses." /><Benefit icon="library" title="Your materials, together" detail="Keep the useful things close." /><Benefit icon="tutor" title="A starting point that adapts" detail="Learn from your answers, not a label." /></div>
          </>}
          {step === 1 && <div className={styles.academics}>
            <Field label="School" htmlFor="onboarding-school"><div className={styles.inputWrap}><input id="onboarding-school" data-testid="onboarding-school" value="Boston University" readOnly className={styles.readOnly} /><LockKeyhole size={18} aria-hidden="true" /></div></Field>
            <Field label="Class year" htmlFor="onboarding-year"><Select id="onboarding-year" testid="onboarding-year" value={draft.year} onChange={value => update({ year: value }, true)}><option value="" disabled>Select your year</option>{YEARS.map(year => <option key={year} value={year}>{year.charAt(0).toUpperCase() + year.slice(1)}</option>)}</Select></Field>
            <Field label="Major · choose at least one" htmlFor="onboarding-major"><div className={styles.inputWrap}><input id="onboarding-major" list="onboarding-academic-examples" data-testid="onboarding-chip-input-majors" value={draft.majorsText} placeholder="Add a major" onChange={event => update({ majorsText: event.target.value }, true)} required maxLength={500} /><ChevronDown size={18} aria-hidden="true" /></div></Field>
            <Field label="Minor · optional" htmlFor="onboarding-minor"><div className={styles.inputWrap}><input id="onboarding-minor" list="onboarding-academic-examples" data-testid="onboarding-chip-input-minors" value={draft.minorsText} placeholder="Add a minor" onChange={event => update({ minorsText: event.target.value }, true)} maxLength={500} /><ChevronDown size={18} aria-hidden="true" /></div></Field>
            <datalist id="onboarding-academic-examples"><option value="Computer Science" /><option value="Mathematics" /><option value="Philosophy" /><option value="Linguistics" /></datalist>
            <p className={styles.academicHint}>You can update these in Settings.<span>Separate multiple majors or minors with commas.</span></p>
          </div>}
          {step === 2 && <CoursePicker selectedIds={draft.courseIds} selectedCache={draft.courseCache} onSelect={(courseIds, courseCache) => update({ courseIds, courseCache }, true)} />}
          {step === 3 && <>
            <div className={styles.uploadCard}><BotanicalIcon name="paper" size={56} /><h2>Add your first course file</h2><p>PDF, DOCX or PPTX · up to 5 files<br />100 MB per file</p><button type="button" data-testid="onboarding-choose-files" className={styles.primary} onClick={() => setUploadOpen(true)} disabled={enrolled.length === 0 || Boolean(enrollmentError)}>Choose files</button></div>
            {enrollmentError && <Recovery error={enrollmentError} onRetry={() => setEnrollmentRetry(value => value + 1)} />}
            <MaterialList draft={draft} enrolled={enrolled} onRefresh={materials => {
              const owner = draft.userId;
              setDraft(current => current?.userId === owner ? { ...current, materials, handoffId: undefined } : current);
            }} />
            <button type="button" className={styles.skip} onClick={() => go(4)} data-testid="onboarding-skip-materials">Skip for now →</button>
          </>}
          {step === 4 && <div className={styles.goal}>
            <Field label="Course" htmlFor="onboarding-goal-course"><Select id="onboarding-goal-course" testid="onboarding-goal-course" value={draft.goalCourseId} onChange={goalCourseId => { update({ goalCourseId, goalTargets: [], goalScope: "course" }); setEditingConcepts(false); }}><option value="" disabled>Choose a course</option>{enrolled.map(value => <option key={value.course_id} value={value.course_id}>{value.course_code} · {value.course_name}</option>)}</Select></Field>
            {enrollmentError && <Recovery error={enrollmentError} onRetry={() => setEnrollmentRetry(value => value + 1)} />}
            <fieldset className={styles.scope}><legend className={styles.srOnly}>Learning scope</legend><label className={styles.choice} data-selected={draft.goalScope === "course"}><input type="radio" name="goal-scope" data-testid="onboarding-goal-course-scope" checked={draft.goalScope === "course"} onChange={() => update({ goalScope: "course" })} />Explore the course</label><label className={styles.choice} data-selected={draft.goalScope === "concepts"}><input type="radio" name="goal-scope" data-testid="onboarding-goal-concept-scope" checked={draft.goalScope === "concepts"} onChange={() => { update({ goalScope: "concepts" }); setEditingConcepts(draft.goalTargets.length === 0); }} />Focus on selected concepts</label></fieldset>
            {draft.goalScope === "concepts" && <>
              <div className={styles.conceptHeading}><span role="status">{draft.goalTargets.length} concept{draft.goalTargets.length === 1 ? "" : "s"} selected</span><button type="button" data-testid="onboarding-edit-concepts" aria-expanded={editingConcepts} onClick={() => setEditingConcepts(value => !value)}>Edit concepts →</button></div>
              <div className={styles.chips}>{courseConcepts.filter(node => draft.goalTargets.includes(node.id)).map(node => <span key={node.id} className={styles.chip}>{node.name}<button type="button" data-testid={`onboarding-remove-target-${node.id}`} aria-label={`Remove ${node.name}`} onClick={() => update({ goalTargets: draft.goalTargets.filter(id => id !== node.id) })}><X size={16} /></button></span>)}</div>
              {conceptLoading && <p role="status" className={styles.hint}>Loading course concepts…</p>}
              {conceptError && <Recovery error={conceptError} onRetry={() => setConceptRetry(value => value + 1)} />}
              {!conceptLoading && !conceptError && courseConcepts.length === 0 && <p role="status" className={styles.hint}>No concepts are available yet. Explore the course, or go Back to add course materials. Uploading alone does not assess your knowledge.</p>}
              {editingConcepts && !conceptLoading && !conceptError && courseConcepts.length > 0 && <fieldset className={styles.conceptList}><legend>Confirm 1–12 course concepts</legend><p>Your objective does not select concepts automatically.</p>{courseConcepts.map(node => <label key={node.id} className={styles.choice} data-selected={draft.goalTargets.includes(node.id)}><input type="checkbox" data-testid={`onboarding-target-${node.id}`} checked={draft.goalTargets.includes(node.id)} disabled={!draft.goalTargets.includes(node.id) && draft.goalTargets.length >= 12} onChange={event => update({ goalTargets: event.target.checked ? [...draft.goalTargets, node.id] : draft.goalTargets.filter(id => id !== node.id) })} />{node.name}</label>)}</fieldset>}
            </>}
            <div className={styles.objective}><Field label="Your objective · optional" htmlFor="onboarding-objective"><textarea id="onboarding-objective" data-testid="onboarding-objective" value={draft.objective} maxLength={500} rows={3} disabled={draft.goalScope === "course"} onChange={event => update({ objective: event.target.value })} placeholder="What would you like to understand?" /><span className={styles.counter}>{draft.objective.length} / 500</span></Field>{draft.goalScope === "course" && <p className={styles.hint}>Choose selected concepts to add a focused objective.</p>}</div>
          </div>}
          {step === 5 && <div className={styles.review}>
            <ReviewRow label="COURSE">{course ? `${course.course_code} · ${course.course_name}` : "Confirm your course"}</ReviewRow><ReviewRow label="YOUR GOAL" prominent>{draft.goalScope === "course" ? "Explore the course." : draft.objective.trim() || "Focus on selected concepts."}</ReviewRow><ReviewRow label="FOCUS">{draft.goalScope === "course" ? "Whole course · the check-in will find a starting point" : targetNames.join(" · ")}</ReviewRow><ReviewRow label="MATERIAL">{draft.materials.filter(material => material.courseId === draft.goalCourseId).map(material => material.name).join(", ") || "You can add materials later in Library."}</ReviewRow>
            <div className={styles.reassurance}><BotanicalIcon name="clov" size={28} /><div><strong>“I don’t know yet” is a useful answer.</strong><p>We’ll build your plan after the check-in.</p></div></div>
          </div>}
        </fieldset>
        {error && <div className={styles.error} role="alert" data-testid="onboarding-save-error">{error}</div>}
        <footer className={styles.footer}>{step > 0 && <button type="button" className={styles.back} data-testid="onboarding-back" onClick={() => go((step - 1) as OnboardingStep)} disabled={busy}><ArrowLeft size={17} />Back</button>}<button type="submit" className={styles.primary} data-testid="onboarding-continue" disabled={!canContinueOnboarding(draft) || !validGoal || busy}>{busy ? "Saving…" : step === 5 ? "Start check-in" : step === 4 ? "Confirm goal & continue" : "Continue"}</button><p className={styles.saved} role="status">{requiredSaved ? savedLocally ? "Profile saved. Optional setup stays on this device." : "Profile saved. This browser couldn't save your setup draft; keep this tab open to finish." : savedLocally ? "Draft saved on this device." : "Keep this page open; this browser couldn't save your draft."}</p></footer>
      </form>
      <DocumentUploadModal key={draft.userId} open={uploadOpen} userId={draft.userId} courses={enrolled} onClose={() => setUploadOpen(false)} onComplete={onUploadComplete} />
      <Dialog open={exitOpen} onClose={() => setExitOpen(false)} title={requiredSaved ? "Finish setup later?" : "Sign out and finish later?"}><p>{requiredSaved ? "Your profile and courses are saved. You can return to materials and learning from your workspace." : savedLocally ? "Your draft is kept on this device for this account. Finishing later signs you out. Required setup may still be incomplete; we'll confirm your courses when you return." : "Your browser couldn't keep a local draft. Finishing later signs you out, and you may need to enter these choices again."}</p><div className={styles.dialogActions}><button data-testid="onboarding-exit-cancel" className={styles.quiet} onClick={() => setExitOpen(false)}>Keep going</button><button data-testid="onboarding-exit-confirm" className={styles.primary} onClick={() => void exit()}>{requiredSaved ? "Go to my workspace" : "Sign out"}</button></div></Dialog>
    </main>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) { return <div className={styles.field}><label htmlFor={htmlFor}>{label}</label>{children}</div>; }
function Select({ id, testid, value, onChange, children }: { id: string; testid: string; value: string; onChange: (value: string) => void; children: React.ReactNode }) { return <div className={styles.inputWrap}><select id={id} data-testid={testid} value={value} onChange={event => onChange(event.target.value)}>{children}</select><ChevronDown size={18} aria-hidden="true" /></div>; }
function Benefit({ icon, title, detail }: { icon: "learn" | "library" | "tutor"; title: string; detail: string }) { return <div className={styles.benefit}><BotanicalIcon name={icon} size={24} /><div><strong>{title}</strong><p>{detail}</p></div></div>; }
function ReviewRow({ label, prominent, children }: { label: string; prominent?: boolean; children: React.ReactNode }) { return <div className={styles.reviewRow}><p>{label}</p><div className={prominent ? styles.prominent : undefined}>{children}</div></div>; }
function Recovery({ error, onRetry }: { error: string; onRetry: () => void }) { return <div className={styles.error} role="alert"><p>{error}</p><button type="button" data-testid="onboarding-recovery-retry" className={styles.quiet} onClick={onRetry}>Retry</button></div>; }
function dedupeCourses(courses: EnrolledCourse[]) { return [...new Map(courses.map(course => [course.course_id, course])).values()]; }

function CoursePicker({ selectedIds, selectedCache, onSelect }: { selectedIds: string[]; selectedCache: OnboardingCourse[]; onSelect: (ids: string[], cache: OnboardingCourse[]) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<OnboardingCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      void onboardingCoursesSearch(query).then(response => { if (!cancelled) setResults(response.courses ?? []); })
        .catch(() => { if (!cancelled) setError(navigator.onLine === false ? "You're offline. Reconnect and retry; selected courses are kept." : "We couldn't search the catalog. Your selected courses are kept."); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, retry]);
  const toggle = (course: OnboardingCourse) => selectedIds.includes(course.id) ? onSelect(selectedIds.filter(id => id !== course.id), selectedCache.filter(item => item.id !== course.id)) : onSelect([...selectedIds, course.id], [...selectedCache.filter(item => item.id !== course.id), course]);
  return <div className={styles.courses}>
    <div className={styles.search}><Search size={20} aria-hidden="true" /><input aria-label="Search by course code or title" data-testid="onboarding-course-search" value={query} onChange={event => { setLoading(true); setError(""); setQuery(event.target.value); }} placeholder="Search by course code or title" /></div>
    <p className={styles.selectedLabel}>SELECTED · {selectedIds.length} COURSE{selectedIds.length === 1 ? "" : "S"}</p><div className={styles.chips}>{selectedCache.filter(item => selectedIds.includes(item.id)).map(course => <span key={course.id} className={styles.chip}>{course.course_code}<button type="button" data-testid={`onboarding-course-remove-${course.course_code}`} aria-label={`Remove ${course.course_code}`} onClick={() => toggle(course)}><X size={16} /></button></span>)}</div>
    <div className={styles.courseResults} aria-busy={loading}>{loading && <p className={styles.hint} role="status">Searching courses…</p>}{!loading && error && <Recovery error={error} onRetry={() => { setLoading(true); setError(""); setRetry(value => value + 1); }} />}{!loading && !error && results.length === 0 && <p className={styles.hint} role="status">No courses match. Try a course code or another title.</p>}{!loading && !error && results.map(course => <label key={course.id} className={styles.courseRow} data-selected={selectedIds.includes(course.id)}><input type="checkbox" className={styles.srOnly} data-testid={`onboarding-course-result-${course.id}`} checked={selectedIds.includes(course.id)} onChange={() => toggle(course)} /><BotanicalIcon name="learn" size={24} /><span><strong>{course.course_name}</strong><small>{course.course_code}</small></span>{selectedIds.includes(course.id) && <Check size={20} aria-hidden="true" />}</label>)}</div><p className={styles.courseCount} role="status">{selectedIds.length} course{selectedIds.length === 1 ? "" : "s"} selected</p>
  </div>;
}

function MaterialList({ draft, enrolled, onRefresh }: { draft: OnboardingDraft; enrolled: EnrolledCourse[]; onRefresh: (materials: OnboardingDraft["materials"]) => void }) {
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [removing, setRemoving] = useState("");
  const [removeError, setRemoveError] = useState("");
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;
  const materialsRef = useRef(draft.materials);
  materialsRef.current = draft.materials;
  const ownerRef = useRef(draft.userId);
  ownerRef.current = draft.userId;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let cancelled = false;
    setError(false);
    void getDocuments(draft.userId).then(response => {
      if (cancelled) return;
      const saved = response.documents.flatMap(document => typeof document.id === "string" && typeof document.file_name === "string" && enrolled.some(course => course.course_id === document.course_id) ? [{ id: document.id, name: document.file_name, courseId: document.course_id as string, size: materialsRef.current.find(material => material.id === document.id)?.size }] : []);
      refreshRef.current(saved);
    }).catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [draft.userId, enrolled, retry]);
  const remove = async (id: string, name: string) => {
    if (removing || !window.confirm(`Delete ${name} from your Library? This removes the saved material, not just this setup.`)) return;
    const owner = draft.userId;
    setRemoving(id);
    setRemoveError("");
    try {
      await deleteDocument(id, owner);
      if (mounted.current && ownerRef.current === owner) refreshRef.current(materialsRef.current.filter(material => material.id !== id));
    } catch {
      if (mounted.current && ownerRef.current === owner) setRemoveError("The material wasn't deleted. Your saved file is kept; use its remove button to retry.");
    } finally { if (mounted.current && ownerRef.current === owner) setRemoving(""); }
  };
  return <div className={styles.materials}>
    {error && <Recovery error="We couldn't refresh saved materials. Your completed uploads are kept; retry or continue without adding files." onRetry={() => setRetry(value => value + 1)} />}
    {removeError && <p className={styles.error} role="alert">{removeError}</p>}
    {draft.materials.map(material => <div key={material.id} className={styles.materialRow}>
      <div className={styles.materialHeading}><BotanicalIcon name="paper" size={28} /><div><strong>{material.name}</strong><p>Saved to Library{typeof material.size === "number" ? ` · ${Math.max(1, Math.round(material.size / 1024))} KB` : ""}</p></div><button type="button" data-testid={`onboarding-delete-material-${material.id}`} className={styles.removeMaterial} aria-label={`Delete ${material.name} from Library`} disabled={Boolean(removing)} onClick={() => void remove(material.id, material.name)}><X size={18} /></button></div>
      <div className={styles.materialCourse}><span>Course</span><div>{enrolled.find(course => course.course_id === material.courseId)?.course_code ?? "Course"}<LockKeyhole size={14} aria-label="Saved course" /></div></div>
    </div>)}
  </div>;
}
