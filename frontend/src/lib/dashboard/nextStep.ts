/**
 * The Dashboard's ONE primary learning action, chosen from authoritative
 * learner state (redesign prompt 07, docs/07 §4). Pure: no fetching, no
 * React. The discovery hook (components/dashboard/useLearningDiscovery)
 * gathers the state read-only; this maps it to copy and a destination.
 *
 * Every destination is a NAVIGATION into the existing Learn controller,
 * which owns sessions, goals, plans and grading. Nothing here creates a
 * session, writes a goal, approves a plan or poses a check — a resume link
 * (`/learn?resume=<id>`) only READS there (GET /status restores the pose),
 * and a new check-in starts only when the student clicks the action and the
 * controller creates it.
 *
 * Copy rule: every sentence below states something the state proves. No
 * durations (the API has none), no motivational filler, no "why next" that
 * the server did not supply.
 */
import type { LoopDiagnosis, LoopGoal, LoopGoalProgress, LoopPhase } from "@/lib/api";

/** The phases a resumable loop session can report (GET /status, mapped the
 *  way LoopLearn's `statusPhase` maps them: teach is refined into
 *  teach | check | feedback). */
export type ResumePhase = LoopPhase;

export interface OpenLoopSession {
  sessionId: string;
  courseId: string;
  topic: string;
  phase: ResumePhase;
  goal: LoopGoal | null;
  goalVersion: number | null;
  diagnosis: LoopDiagnosis | null;
  goalProgress: LoopGoalProgress | null;
  /** False when GET /status failed but the session list proved the session
   *  exists: the action still resumes it, the goal detail is just missing. */
  statusLoaded: boolean;
}

/** What discovery established. Exactly one of these at a time. */
export type LearnerState =
  | { kind: "pending" }
  | { kind: "error" }
  | { kind: "no-course" }
  | { kind: "no-concepts"; courseId: string }
  | { kind: "loop-open"; session: OpenLoopSession }
  /** No open loop session. `lastClosed` is the newest ended session, if any
   *  (a persisted, read-only wrap-up/transcript lives behind it). */
  | { kind: "loop-none"; courseId: string; lastClosed: { id: string; topic: string } | null }
  /** The learning loop is off for this student (kill switch): the legacy tutor. */
  | { kind: "legacy-open"; sessionId: string; topic: string; courseId: string | null }
  | { kind: "legacy-none" };

export interface NextStepLink {
  label: string;
  href: string;
  testid: string;
}

export interface NextStep {
  /** Small label above the activity ("Up next · Check-in"). */
  eyebrow: string;
  /** The specific next activity, in plain words. */
  title: string;
  /** A short reason grounded in the server state (or an honest limitation). */
  reason: string | null;
  /** Further truthful detail lines (evidence coverage, goal progress). */
  details: string[];
  /** The single primary action. Null while discovery is pending. */
  action: { label: string; href: string } | null;
  /** Quieter, subordinate destinations. */
  links: NextStepLink[];
}

export const PHASE_LABEL: Record<ResumePhase, string> = {
  probe: "Check-in",
  plan: "Plan",
  teach: "Learn",
  check: "Knowledge check",
  feedback: "Feedback",
  close: "Wrap-up",
};

/** /learn deep link that resumes ONE session by id (cross-course safe: the
 *  controller switches to the session's own course, LoopLearn.loadSessions). */
export const resumeHref = (sessionId: string) => `/learn?resume=${encodeURIComponent(sessionId)}`;
/** /learn scoped to a course. With an open session there the controller
 *  resumes it; with none, the student's click starts a check-in there. */
export const courseLearnHref = (courseId: string) => `/learn?course=${encodeURIComponent(courseId)}`;
export const libraryHref = (courseId?: string | null) =>
  courseId ? `/library?course=${encodeURIComponent(courseId)}` : "/library";

const DIAGNOSIS_COPY: Record<LoopDiagnosis["status"], string> = {
  in_progress: "Your check-in is still in progress.",
  bracketed: "Your check-in set a starting estimate. It is not proof of mastery.",
  limited: "Your check-in couldn't place every concept; untested concepts stay unassessed.",
  not_assessed: "These concepts haven't been assessed yet.",
};

/** Untested / inconsistent / partial skills are NOT known edges: say so. */
function diagnosisGaps(d: LoopDiagnosis | null): string | null {
  if (!d) return null;
  const open = d.skills.filter((s) => s.status === "untested" || s.status === "inconsistent" || s.status === "partial");
  if (open.length === 0) return null;
  return `${open.length} ${open.length === 1 ? "concept is" : "concepts are"} not yet placed (untested, partial or mixed evidence).`;
}

function goalProgressLine(p: LoopGoalProgress | null, names: (id: string) => string | null): string | null {
  if (!p || p.target_node_ids.length === 0) return null;
  const total = p.target_node_ids.length;
  const remaining = p.remaining_target_node_ids.length;
  if (p.status === "session_plan_finished") return "This session's plan is finished.";
  if (remaining === 0) return null;
  const first = names(p.remaining_target_node_ids[0]);
  const lead = `${remaining} of ${total} goal ${total === 1 ? "concept" : "concepts"} still ${remaining === 1 ? "needs" : "need"} practice`;
  return first ? `${lead}, starting with ${first}.` : `${lead}.`;
}

export interface NextStepContext {
  /** Concept id → name, for goal/plan ids (only real graph nodes resolve). */
  conceptName: (id: string) => string | null;
  /** Course id → short label. */
  courseLabel: (id: string | null | undefined) => string | null;
}

export function nextStepFor(state: LearnerState, ctx: NextStepContext): NextStep {
  switch (state.kind) {
    case "pending":
      return { eyebrow: "Up next", title: "Checking where you left off…", reason: null, details: [], action: null, links: [] };
    case "error":
      return {
        eyebrow: "Up next",
        title: "We couldn't check your learning sessions",
        reason: "Nothing was started or changed. Try again to find where you left off.",
        details: [],
        action: null,
        links: [],
      };
    case "no-course":
      return {
        eyebrow: "Get started",
        title: "Add a course to start learning",
        reason: "Sapling plans check-ins and practice course by course, so it needs a course first.",
        details: [],
        action: null,
        links: [{ label: "Open Library", href: libraryHref(), testid: "dashboard-next-library" }],
      };
    case "no-concepts": {
      const course = ctx.courseLabel(state.courseId) ?? "this course";
      return {
        eyebrow: "Get started",
        title: `Add material to ${course}`,
        reason: "There are no concepts on your map for it yet. Upload notes or a syllabus in Library so a check-in has something to cover.",
        details: [],
        action: { label: "Open course Library", href: libraryHref(state.courseId) },
        links: [],
      };
    }
    case "loop-open": {
      const s = state.session;
      const course = ctx.courseLabel(s.courseId);
      const href = resumeHref(s.sessionId);
      const planLink: NextStepLink = { label: "View your learning plan", href, testid: "dashboard-next-plan" };
      const details: string[] = [];
      const gaps = diagnosisGaps(s.diagnosis);
      const progress = goalProgressLine(s.goalProgress, ctx.conceptName);
      if (!s.statusLoaded) details.push("Your goal details couldn't load; the session itself is safe and resumes as you left it.");
      switch (s.phase) {
        case "probe":
          return {
            eyebrow: `Up next · ${PHASE_LABEL.probe}`,
            title: "Finish your check-in",
            reason: s.diagnosis ? DIAGNOSIS_COPY[s.diagnosis.status] : "Your check-in helps Sapling find where to start.",
            details: [...details, ...(gaps ? [gaps] : [])],
            action: { label: "Resume check-in", href },
            links: [],
          };
        case "plan":
          return {
            eyebrow: `Up next · ${PHASE_LABEL.plan}`,
            title: "Review your learning plan",
            reason: "Your plan is ready. Teaching starts only after you approve it.",
            details: [...details, ...(s.diagnosis ? [DIAGNOSIS_COPY[s.diagnosis.status]] : []), ...(gaps ? [gaps] : [])],
            action: { label: "Review plan", href },
            links: [],
          };
        case "check":
          return {
            eyebrow: `Up next · ${PHASE_LABEL.check}`,
            title: "Answer your open knowledge check",
            reason: "A question is waiting for your answer. It reopens exactly as you left it.",
            details: [...details, ...(progress ? [progress] : [])],
            action: { label: "Resume check", href },
            links: [planLink],
          };
        case "feedback":
          return {
            eyebrow: `Up next · ${PHASE_LABEL.feedback}`,
            title: "Read your feedback",
            reason: "Your last answer has been graded. Review the feedback, then continue.",
            details: [...details, ...(progress ? [progress] : [])],
            action: { label: "Review feedback", href },
            links: [planLink],
          };
        case "close":
          return {
            eyebrow: `Up next · ${PHASE_LABEL.close}`,
            title: "Finish your session wrap-up",
            reason: "Your session is wrapping up. Completing practice isn't the same as mastering the goal.",
            details,
            action: { label: "See wrap-up", href },
            links: [],
          };
        case "teach":
        default:
          return {
            eyebrow: `Up next · ${PHASE_LABEL.teach}`,
            title: s.topic ? `Keep going: ${s.topic}` : `Keep going in ${course ?? "your course"}`,
            reason: progress ?? "You're working through your approved plan.",
            details,
            action: { label: "Continue learning", href },
            links: [planLink],
          };
      }
    }
    case "loop-none": {
      const course = ctx.courseLabel(state.courseId) ?? "your course";
      return {
        eyebrow: "Up next · Check-in",
        title: `Start a check-in in ${course}`,
        reason: "You have no open learning session. A short check-in finds where to start; you confirm your goal before any teaching.",
        details: [],
        action: { label: "Start a check-in", href: courseLearnHref(state.courseId) },
        links: state.lastClosed
          ? [{ label: "Review your last session", href: resumeHref(state.lastClosed.id), testid: "dashboard-next-last-session" }]
          : [],
      };
    }
    case "legacy-open":
      return {
        eyebrow: "Up next",
        title: state.topic ? `Continue: ${state.topic}` : "Continue your session",
        reason: state.courseId && ctx.courseLabel(state.courseId) ? `Your open session in ${ctx.courseLabel(state.courseId)}.` : "Your most recent open session.",
        details: [],
        action: { label: "Continue session", href: resumeHref(state.sessionId) },
        links: [],
      };
    case "legacy-none":
      return {
        eyebrow: "Up next",
        title: "Start a learning session",
        reason: "You have no open session.",
        details: [],
        action: { label: "Start learning", href: "/learn" },
        links: [],
      };
  }
}

/** The saved goal, in words — only what the session confirmed. */
export function goalText(s: OpenLoopSession, ctx: NextStepContext): { text: string; scope: string } {
  const course = ctx.courseLabel(s.courseId) ?? "your course";
  if (s.goal && s.goal.target_node_ids.length > 0) {
    const names = s.goal.target_node_ids.map((id) => ctx.conceptName(id)).filter((n): n is string => !!n);
    const text = s.goal.text.trim() || (names.length ? names.join(", ") : `Concepts in ${course}`);
    return { text, scope: names.length ? names.join(" · ") : `${s.goal.target_node_ids.length} confirmed concepts` };
  }
  if (s.goal?.text.trim()) return { text: s.goal.text.trim(), scope: `Whole course · ${course}` };
  return { text: `Explore ${course}`, scope: "Whole course" };
}
