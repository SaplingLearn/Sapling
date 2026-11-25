"use client";
// The question screen's chrome (moved out of QuizQuestion.tsx): the session
// top bar and its Exam Twin countdown, the meta row, the prerequisite banner,
// the pager, the action bar and the generating status.
import React, { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Columns2, Gauge, GitCompareArrows, Hash, Highlighter, Layers, ListChecks, ListOrdered, MessagesSquare, PenLine, Puzzle, Sigma, Tag, TextAlignStart, Calculator, ArrowDownWideNarrow, X } from "lucide-react";
import { Badge, Button, Chip, ProgressDots } from "@/components/ui";
import { ConceptNode } from "@/components/graph/ConceptNode";
import { AIDisclaimerChip } from "@/components/chat/AIDisclaimerChip";
import { useFlag } from "@/context/FlagsContext";
import { learnHrefForNode } from "@/lib/data";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import { buildQuizHref } from "@/lib/quiz/source";
import { examDistanceFilled, examDistancePips, isReturningConcept } from "@/lib/quiz/metaChips";
import { skillChipLabel } from "@/lib/quiz/skillChip";
import { formatExamClock } from "@/lib/quiz/examTimer";
import type { Phase, QuestionType, QuizPrereqBanner, QuizSession } from "@/lib/quiz/types";
import { isUnanswered } from "@/lib/quiz/machine";
import {
  canGoTo,
  canNavigate,
  generatingDetail,
  hintSlotState,
  skipSlotState,
  type Primary,
} from "./questionView";

/** Mastery tier labels already on `QuizConceptSummary` — the meta chip source
 *  until a skill field exists on the summary. */
const TIER_CHIP: Record<string, string> = {
  mastered: "Mastered",
  learning: "Learning",
  struggling: "Struggling",
  unexplored: "Unexplored",
};

export interface QuizConceptSummary {
  id: string;
  name: string;
  courseCode: string;
  color: string;
  tier: string;
  mastery: number;
  /** Graph study history — feeds Returning + exam-distance (w7-meta-chips.md). */
  timesStudied?: number;
  lastStudiedAt?: string | null;
}

/** The header mark, at the size §3 pins for a `dot`. */
const HEADER_DOT = 15;
/** What each format is called on screen — the same names the Format setting
 *  uses, so "Algebra" in the settings is "Algebra" on the question. Sort /
 *  Sequence / Label / Build / Compare / Dialogue are kit-only (W7.2): still a
 *  short_answer on the wire. */
const FORMAT_TAG: Record<string, { label: string; Icon: typeof ListChecks }> = {
  multiple_choice: { label: "Multiple choice", Icon: ListChecks },
  short_answer: { label: "Short answer", Icon: PenLine },
  numeric: { label: "Numeric", Icon: Hash },
  symbolic: { label: "Algebra", Icon: Sigma },
  sort: { label: "Sort", Icon: Layers },
  sequence: { label: "Sequence", Icon: ListOrdered },
  label: { label: "Label", Icon: Tag },
  build: { label: "Build", Icon: Puzzle },
  compare: { label: "Compare", Icon: Columns2 },
  dialogue: { label: "Dialogue", Icon: MessagesSquare },
  explain: { label: "Explain", Icon: TextAlignStart },
  highlight: { label: "Highlight", Icon: Highlighter },
  calculate: { label: "Calculate", Icon: Calculator },
  position: { label: "Position", Icon: Gauge },
  rank: { label: "Rank", Icon: ArrowDownWideNarrow },
  connect: { label: "Connect", Icon: GitCompareArrows },
};


/** The countdown ticks once a second. */
const MS_PER_SECOND = 1000;

/** Exam Twin's soft countdown (W7.8): seconds left, from the budget, counted
 *  from when the attempt's budget is set; null when there is no budget. Display
 *  only, it never auto-submits. A new budget or attempt starts it again. */
export function useExamCountdown(budget: number | null, attemptId: string | null | undefined): number | null {
  const key = JSON.stringify([budget, attemptId ?? null]);
  const [elapsed, setElapsed] = useState({ key, sec: 0 });
  useEffect(() => {
    if (budget == null) return;
    const started = Date.now();
    const id = window.setInterval(() => {
      setElapsed({ key, sec: Math.floor((Date.now() - started) / MS_PER_SECOND) });
    }, MS_PER_SECOND);
    return () => window.clearInterval(id);
  }, [budget, key]);
  if (budget == null) return null;
  return elapsed.key === key ? Math.max(0, budget - elapsed.sec) : budget;
}

// ── Pieces shared by the generating and the live render ────────────────

/** The way off the screen, per phase: Cancel while generating (#760: a
 *  generation that never answers must not be a dead end) and while scoring
 *  (#760: Leave is refused mid-score, since the attempt is live, so this is
 *  the way off "Scoring…" — back onto the final verdict, from where See
 *  results and Leave both work again); Leave everywhere else. */
function exitButtonFor(phase: Phase): { testid: string; label: string; leaves: boolean } {
  if (phase === "generating") return { testid: "quiz-cancel-generate", label: "Cancel", leaves: false };
  if (phase === "submitting") return { testid: "quiz-cancel-submit", label: "Cancel", leaves: false };
  return { testid: "quiz-leave", label: "Leave", leaves: true };
}

/**
 * 64px focus-session top bar (W7.1): leave / cancel on the left, course +
 * topic, centred "Question N of M" with a forest progress fill, disclaimer
 * on the right. XP and streak stay on results — never in this bar (W7.D1).
 * Exam Twin shows a soft countdown (W7.8) — never auto-submits.
 */
export function SessionTop({
  phase,
  actions,
  concept,
  position,
  quizLength,
  examRemainingSec,
}: {
  phase: Phase;
  actions: QuizActions;
  concept: QuizConceptSummary;
  position: number;
  quizLength: number;
  examRemainingSec?: number | null;
}) {
  const exit = exitButtonFor(phase);
  const pct = quizLength > 0 ? Math.min(100, Math.max(0, (position / quizLength) * 100)) : 0;
  const examUrgent = examRemainingSec != null && examRemainingSec <= 60;
  return (
    <header className="quiz-session-top" data-testid="quiz-session-top">
      <div className="quiz-session-top__start">
        <button
          type="button"
          className="quiz-session-top__leave"
          data-testid={exit.testid}
          aria-label={exit.leaves ? "Leave session" : exit.label}
          onClick={() => (exit.leaves ? actions.requestLeave() : actions.cancel())}
        >
          <X size={14} strokeWidth={2} aria-hidden="true" />
        </button>
        {concept.courseCode && (
          <span className="quiz-session-top__course">{concept.courseCode}</span>
        )}
        <span className="quiz-session-top__topic">{concept.name}</span>
      </div>
      <div className="quiz-session-top__progress" data-testid="quiz-session-progress">
        {/* Visible count names the progressbar (W7.2): no second group label
            that duplicates the pager's "Question N of M". */}
        <span className="quiz-session-top__count" id="quiz-session-count">
          Question {position} of {quizLength}
        </span>
        <div
          className="quiz-session-top__bar"
          role="progressbar"
          aria-labelledby="quiz-session-count"
          aria-valuemin={0}
          aria-valuenow={position}
          aria-valuemax={quizLength}
        >
          <span className="quiz-session-top__fill" style={{ "--quiz-progress": `${pct}%` } as React.CSSProperties} />
        </div>
      </div>
      <div className="quiz-session-top__end">
        {examRemainingSec != null && (
          <span
            className={`quiz-session-top__timer${examUrgent ? " quiz-session-top__timer--urgent" : ""}`}
            data-testid="quiz-exam-timer"
            data-urgent={examUrgent ? "true" : "false"}
            title="Exam Twin soft timer — finish when you can; it does not auto-submit"
            aria-label={`Time remaining ${formatExamClock(examRemainingSec)}`}
          >
            {formatExamClock(examRemainingSec)}
          </span>
        )}
        <AIDisclaimerChip />
      </div>
    </header>
  );
}

export function QuestionHeader({
  concept,
  format,
  formatTagKey,
  showFormat,
  difficulty,
  interactionKind,
}: {
  concept: QuizConceptSummary;
  format: QuestionType;
  /** Kit display key when it differs from the wire format (Sort → short_answer). */
  formatTagKey: string;
  showFormat: boolean;
  difficulty: string;
  interactionKind?: string | null;
}) {
  const formatTag = FORMAT_TAG[formatTagKey] ?? FORMAT_TAG[format] ?? FORMAT_TAG.multiple_choice;
  // A blank accent would reach `shadeFor` as an unparseable colour and pass
  // straight through; the CSS variable degrades to the app accent instead.
  const accent = concept.color || "var(--quiz-accent, var(--accent))";
  const tierLabel = TIER_CHIP[concept.tier];
  const skill = skillChipLabel({
    type: format,
    difficulty: difficulty.toLowerCase(),
    interactionKind,
  });
  const returning = isReturningConcept(concept.timesStudied, concept.lastStudiedAt);
  const dist = examDistancePips(concept.tier, concept.mastery);
  const filled = examDistanceFilled(dist);
  return (
    <div className="quiz-question__header" data-testid="quiz-question-meta">
      <span className="quiz-question__concept-pill">
        <ConceptNode
          size={HEADER_DOT}
          mastery={concept.mastery}
          tier={concept.tier}
          courseColor={accent}
          nodeId={concept.id || concept.name}
        />
        <span className="quiz-question__concept">
          {concept.name}
        </span>
      </span>
      {skill && (
        <Chip data-testid="quiz-skill-chip">{skill}</Chip>
      )}
      {tierLabel && (
        <Chip data-testid="quiz-tier-chip">{tierLabel}</Chip>
      )}
      {returning && (
        <Chip data-testid="quiz-returning-chip">Returning</Chip>
      )}
      <span
        className="quiz-question__exam-distance"
        data-testid="quiz-exam-distance"
        data-pips={dist}
        // role="img": an aria-label on a bare span is prohibited (axe
        // aria-prohibited-attr); the pips are its picture, not content.
        role="img"
        title={`Exam distance ${dist} of 5`}
        aria-label={`Exam distance ${dist} of 5`}
      >
        {Array.from({ length: 5 }, (_, i) => (
          <span
            key={i}
            className={
              i < filled
                ? "quiz-question__exam-distance-pip quiz-question__exam-distance-pip--filled"
                : "quiz-question__exam-distance-pip"
            }
          />
        ))}
      </span>
      <span className="quiz-question__header-gap" />
      {showFormat && (
        <span className="quiz-question__format" data-testid="quiz-format-tag" data-format={formatTagKey}>
          <formatTag.Icon size={13} strokeWidth={2} aria-hidden="true" />
          {formatTag.label}
        </span>
      )}
      {difficulty && <Badge bg="var(--bg-soft)">{difficulty}</Badge>}
    </div>
  );
}

/**
 * W7.6: when generate preferred a weak prerequisite (fringe readiness), say
 * so and offer Learn / Quiz on that parent. Hide links a nav flag would only
 * bounce. Twin of Study's gap sentence, not a second planner.
 */
export function PrereqBanner({ banner }: { banner: QuizPrereqBanner }) {
  const tutorShown = useFlag("hide_tutor") !== "on";
  const quizShown = useFlag("hide_quiz") !== "on";
  const learnHref = tutorShown
    ? learnHrefForNode({
      id: banner.prereq_id,
      name: banner.prereq_name,
      course_id: banner.course_id ?? "",
      is_subject_root: false,
    })
    : null;
  // Quiz the prereq when we did NOT already redirect onto it (otherwise the
  // student is already in that quiz). When redirected, offer the dependent
  // only as Learn — re-quizzing the blocked concept mid-session fights the
  // fringe preference.
  const quizHref = !banner.redirected && quizShown
    ? buildQuizHref(
      { concept: banner.prereq_id },
      { kind: "quiz" },
      { start: true },
    )
    : null;
  const copy = banner.redirected
    ? `Starting with ${banner.prereq_name} — ${banner.dependent_name} needs it first.`
    : `${banner.prereq_name} isn't solid yet — ${banner.dependent_name} builds on it.`;
  return (
    <div
      className="quiz-prereq-banner"
      role="status"
      data-testid="quiz-prereq-banner"
      data-redirected={banner.redirected ? "true" : "false"}
      data-prereq={banner.prereq_id}
      data-dependent={banner.dependent_id}
    >
      <p className="quiz-prereq-banner__copy">{copy}</p>
      {(learnHref || quizHref) && (
        <div className="quiz-prereq-banner__actions">
          {learnHref && (
            <a className="btn btn--primary" href={learnHref} data-testid="quiz-prereq-learn">
              Learn {banner.prereq_name}
            </a>
          )}
          {quizHref && (
            <a className="btn" href={quizHref} data-testid="quiz-prereq-quiz">
              Quiz {banner.prereq_name}
            </a>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Where the student is in the quiz, and the way round it: a numbered button
 * per question (green / red once marked, in as-you-go mode) between back and
 * forward arrows, beside the footer's primary button. Any question can be
 * opened — one already answered shows what was recorded (answers lock once
 * the server has them), one ahead can be answered out of order.
 */
export function QuestionPager({
  session,
  actions,
  busy,
  quizLength,
}: {
  session: QuizSession;
  actions: QuizActions;
  busy: boolean;
  quizLength: number;
}) {
  const { phase, cursor, items } = session;
  const total = items.length;
  const position = Math.min(cursor + 1, quizLength);
  const navigable = canNavigate(phase, busy, total);
  const goTo = (index: number) => {
    if (canGoTo(index, cursor, total, navigable)) actions.goTo?.(index);
  };
  return (
    <nav className="quiz-question__progress" aria-label="Questions">
      <button
        type="button"
        className="quiz-question__step"
        data-testid="quiz-prev-question"
        aria-label="Previous question"
        disabled={!navigable || cursor <= 0}
        onClick={() => goTo(cursor - 1)}
      >
        <ChevronLeft size={16} aria-hidden="true" />
      </button>
      <ProgressDots
        total={quizLength}
        // Nothing is "here" yet while the quiz is still being written.
        current={total === 0 ? -1 : cursor}
        answered={total === 0 ? 0 : items.filter(i => i.verdict !== null).length}
        // Out of order once questions can be skipped: answered isn't a prefix.
        done={items.map(i => !isUnanswered(i))}
        // As-you-go shows each verdict, so the pager keeps the tally too.
        // At-end holds every verdict back, and the pager must not leak them.
        outcomes={session.config.feedback === "as-you-go"
          ? items.map(i => (i.verdict ? i.verdict.isCorrect : null))
          : undefined}
        orientation="row"
        onSelect={goTo}
        disabled={!navigable}
        ariaLabel={`Question ${position} of ${quizLength}`}
        testid="quiz-progress"
      />
      <button
        type="button"
        className="quiz-question__step"
        data-testid="quiz-next-question"
        aria-label="Next question"
        disabled={!navigable || cursor >= total - 1}
        onClick={() => goTo(cursor + 1)}
      >
        <ChevronRight size={16} aria-hidden="true" />
      </button>
    </nav>
  );
}

/**
 * Action bar (W7.1 + W7.5): Hint (client scaffolding) · Study guide ·
 * pager · Skip (GO_TO ahead, no mastery) · Check. No wager.
 */
export function QuestionFooter({
  pager,
  primary,
  hint,
  hintOpen,
  onToggleHint,
  hintRef,
  skip,
  onSkip,
  onOpenGuide,
  guideRef,
}: {
  pager: React.ReactNode;
  primary?: Primary;
  hint: ReturnType<typeof hintSlotState>;
  hintOpen: boolean;
  onToggleHint: () => void;
  hintRef: React.RefObject<HTMLButtonElement | null>;
  skip: ReturnType<typeof skipSlotState>;
  onSkip: () => void;
  onOpenGuide: () => void;
  guideRef: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <div className="quiz-question__footer" data-testid="quiz-action-bar">
      <div className="quiz-question__actions-start">
        <button
          type="button"
          ref={hintRef}
          className="quiz-question__action-btn"
          data-testid="quiz-hint-slot"
          title={hint.title}
          aria-label="Hint"
          aria-expanded={hintOpen}
          aria-controls="quiz-hint-panel"
          aria-disabled={!hint.enabled}
          disabled={!hint.enabled}
          onClick={onToggleHint}
        >
          Hint
        </button>
        <button
          type="button"
          ref={guideRef}
          className="quiz-question__action-btn"
          data-testid="quiz-guide-slot"
          title="Open study guide (answers stay hidden)"
          aria-label="Study guide"
          onClick={onOpenGuide}
        >
          Study guide
        </button>
      </div>
      {pager}
      <div className="quiz-question__actions-end">
        <button
          type="button"
          className="quiz-question__action-btn"
          data-testid="quiz-skip-slot"
          title={skip.title}
          aria-label="Skip"
          aria-disabled={!skip.enabled}
          disabled={!skip.enabled}
          onClick={onSkip}
        >
          Skip
        </button>
        {primary && (
          <Button
            variant="primary"
            data-testid={primary.testid}
            aria-disabled={!primary.enabled}
            disabled={!primary.enabled}
            onClick={primary.activate}
          >
            {primary.label}
          </Button>
        )}
      </div>
    </div>
  );
}

// ── generating ─────────────────────────────────────────────────────────

/** A status, not a skeleton: the questions don't exist yet, so a ghost of
 *  their layout promised a shape that the real quiz then replaced. The bar is
 *  paced to a typical generation (one model call, ~5–10 s) and never claims to
 *  be done until the quiz is — /generate answers in one piece, so there is no
 *  finer signal. */
export function GeneratingStatus({ quizLength, conceptName, difficulty }: { quizLength: number; conceptName: string; difficulty: string }) {
  return (
    <div className="quiz-generating" role="status">
      <p className="quiz-generating__title h-serif">Writing your quiz</p>
      <p className="quiz-generating__detail">
        {generatingDetail(quizLength, conceptName, difficulty)}
      </p>
      <div className="quiz-generating__bar" aria-hidden="true">
        <span className="quiz-generating__fill" />
      </div>
      <p className="quiz-generating__slow">Still writing. Longer quizzes take a little more time.</p>
    </div>
  );
}
