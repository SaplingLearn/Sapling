"use client";

/**
 * The quiz route's one component: reads the entry off the URL, owns the session,
 * and switches the three screens on `phase`.
 *
 * It replaces the `screens/Quiz.tsx` → `QuizPanel.tsx` chain, whose whole
 * concept-picking job now lives in `QuizHome`. The AI-disclaimer gate is carried
 * over unchanged (it self-gates on `localStorage["sapling_disclaimer_ack"]`, and
 * the chip in the TopBar / session top reopens it on demand).
 *
 * `--quiz-accent` is bound here from the active concept's course colour. That
 * inline custom property is the ONE inline style anywhere under
 * `components/quiz/**` (R-1); everything else is a class over tokens.
 *
 * W7.1 focus session: while `QUESTION_PHASES` is live the app TopBar is swapped
 * for the question screen's session chrome, and `data-quiz-session` lets
 * `quiz.css` hide SideNav / TopNav. Home and results keep the ordinary shell.
 */

import React, { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useSearchParams } from "next/navigation";
import { BackLink } from "../BackLink";
import { TopBar } from "../TopBar";
import { FullHeightScreen } from "../FullHeightScreen";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { DisclaimerModal } from "../DisclaimerModal";
import { useUser } from "@/context/UserContext";
import { useLoopStatus } from "../learn/useLoopStatus";
import { useActiveSemester } from "@/lib/useActiveSemester";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { siblingsFor } from "@/lib/graph/neighbourhood";
import { apiToGraphNode } from "@/lib/data";
import { backLink } from "@/lib/quiz/exits";
import { useIsNavHidden } from "@/lib/useNavHidden";
import { parseEntry } from "@/lib/quiz/source";
import { colorFor, entrySelection, nextConceptInQueue } from "@/lib/quiz/proposals";
import { useQuizHome } from "@/lib/quiz/useQuizHome";
import { useQuizSession } from "@/lib/quiz/useQuizSession";
import { QuizHome } from "./home/QuizHome";
import { QuizQuestion, type QuizConceptSummary } from "./question/QuizQuestion";
import { QuizResults } from "./results/QuizResults";
import "./quiz.css";

/** Phases the question screen owns — every state between "we asked for a quiz"
 *  and "we have a score". */
const QUESTION_PHASES = new Set(["generating", "active", "answered", "confirm-leave", "submitting"]);

export function QuizScreen() {
  const searchParams = useSearchParams();
  const { userId, userReady } = useUser();
  const [activeSemester, , semesterHydrated] = useActiveSemester();

  // `searchParams` is a fresh object every render; the entry only changes when
  // the query string does.
  const query = searchParams.toString();
  const entry = useMemo(() => parseEntry(new URLSearchParams(query)), [query]);
  // The header's back link avoids a page this student's flags hide (exits.ts).
  const isNavHidden = useIsNavHidden();

  // `entry` rides along so the home hook can describe the concept the CARD will
  // show, which a deep link overrides (§5 B1.2).
  // A concept picked off the home's topic list. QuizHome owns the choice; it
  // is mirrored here so the hook describes it and the accent follows it.
  const [pickedConceptId, setPickedConceptId] = useState<string | null>(null);
  const home = useQuizHome(
    userId ?? "",
    semesterHydrated ? activeSemester : null,
    entry,
    pickedConceptId,
  );
  const { session, pending, config, actions } = useQuizSession(userId ?? "", entry);
  // Learning-loop spec §13 A132: the question screen asks "How sure are you?"
  // only while the loop is on for the student (#866 K46): the learning_loop flag
  // AND the loop status probe, so the kill switch's pre-loop quiz asks none.
  // A recent answer (Learn's or Study's probe) is reused: no second probe, and
  // the control is there from the first question.
  const { status: loopActive } = useLoopStatus(userId ?? "", userReady, { reuse: true });

  // `?concept=<id>` / `?topic=<name>` resolved against the SCOPED graph, so a
  // link into a term the student isn't looking at reads as unresolved rather
  // than quietly quizzing something off-screen (§6).
  const selection = useMemo(
    () => entrySelection(entry, home.nodes, home.courses),
    [entry, home.nodes, home.courses],
  );

  // The concept the screens are about: whatever the session is running, else the
  // deep link, else the proposal on offer.
  const activeNode = useMemo(() => {
    const wanted = session.conceptId || pickedConceptId || selection.conceptId;
    const byId = wanted ? home.nodes.find(n => n.id === wanted) : undefined;
    return byId ?? home.primary?.node ?? null;
  }, [home.nodes, home.primary, session.conceptId, pickedConceptId, selection.conceptId]);

  const activeCourse = useMemo(
    () => home.courses.find(c => c.course_id === activeNode?.course_id) ?? null,
    [home.courses, activeNode],
  );

  const accent = activeNode ? colorFor(activeNode, activeCourse) : null;

  const concept: QuizConceptSummary = useMemo(
    () => ({
      id: activeNode?.id ?? session.conceptId,
      name: activeNode?.concept_name ?? "This concept",
      courseCode: activeCourse?.course_code ?? "",
      color: accent ?? "",
      tier: activeNode?.mastery_tier ?? "unexplored",
      mastery: activeNode?.mastery_score ?? 0,
    }),
    [activeNode, activeCourse, accent, session.conceptId],
  );

  // `siblingsFor` works on the adapted `lib/data` node shape (colour resolved,
  // `name` rather than `concept_name`) — the same one Tree/Learn/Dashboard feed
  // the graph. `apiToGraphNode` is the one sanctioned adapter, so it is used
  // here rather than re-deriving the join.
  const siblings = useMemo(() => {
    if (!activeNode) return [];
    const adapted = home.nodes.map(n => apiToGraphNode(n, home.courses));
    return siblingsFor(activeNode.id, adapted, home.edges);
  }, [activeNode, home.nodes, home.courses, home.edges]);

  // The queue holds ids; only the loaded graph can turn the next one into a name
  // for the results screen's "Next: {concept}" exit.
  const nextConcept = useMemo(
    () => nextConceptInQueue(session, home.nodes),
    [session, home.nodes],
  );

  const prefersReducedMotion = usePrefersReducedMotion();

  // The accent is the one runtime-bound value; an unset one falls through to
  // `var(--accent)` wherever it is read.
  const rootStyle = accent ? ({ "--quiz-accent": accent } as CSSProperties) : undefined;

  const body = () => {
    if (!userReady) return null;
    if (!userId) return <p className="quiz-signin-note">Sign in to take a quiz.</p>;

    if (session.phase === "error" && session.error) {
      return (
        <div className="quiz-error" role="alert" data-testid="quiz-error">
          <h2 className="h-serif quiz-error__title">That didn&apos;t work</h2>
          <p className="quiz-error__body">{session.error.message}</p>
          <div className="quiz-error__actions">
            {session.error.retryable && (
              <button
                type="button"
                className="btn btn--primary"
                data-testid="quiz-error-retry"
                onClick={() => actions.retry()}
              >
                Try again
              </button>
            )}
            <button
              type="button"
              className="btn"
              data-testid="quiz-error-back"
              onClick={() => actions.dismissError()}
            >
              Back
            </button>
          </div>
          {session.error.requestId && (
            <span className="quiz-error__request-id">
              Reference {session.error.requestId}
            </span>
          )}
        </div>
      );
    }

    if (QUESTION_PHASES.has(session.phase)) {
      return (
        <QuizQuestion
          session={session}
          actions={actions}
          config={config}
          concept={concept}
          userId={userId}
          courseId={activeNode?.course_id ?? null}
          pending={pending}
          askConfidence={loopActive === true}
        />
      );
    }

    if (session.phase === "results") {
      return (
        <QuizResults
          session={session}
          actions={actions}
          concept={concept}
          neighbourhood={{ siblings }}
          prefersReducedMotion={prefersReducedMotion}
          nextConcept={nextConcept}
        />
      );
    }

    return (
      <QuizHome
        userId={userId}
        home={home}
        config={config}
        entry={entry}
        session={session}
        actions={actions}
        onPickedChange={setPickedConceptId}
      />
    );
  };

  const layout = session.phase === "results"
    ? "results"
    : QUESTION_PHASES.has(session.phase) || session.phase === "error"
      ? "question"
      : "home";
  // Mid-attempt only — error/home/results keep the ordinary TopBar + nav.
  const focusSession = QUESTION_PHASES.has(session.phase);

  return (
    <FullHeightScreen className={`quiz-root${focusSession ? " quiz-root--session" : ""}`} style={rootStyle}>
      <DisclaimerModal />
      {/* Focus session owns its chrome inside QuizQuestion; everywhere else
          the page still names itself and offers the way back to Study. */}
      {!focusSession && (
        <TopBar title="Quiz" subtitle="Test what you know." actions={<><AIDisclaimerChip /><BackLink {...backLink(entry.source, isNavHidden)} /></>} />
      )}
      {/* `study-mode-enter`: the Study tools' arrival fade (globals.css), so
          leaving the hub for a quiz reads as a move, not a cut.
          `data-quiz-session` is the hook `quiz.css` uses to hide SideNav /
          TopNav for the attempt (same `:has()` pattern as the guide print
          stylesheet). */}
      <div
        className={`quiz-body quiz-body--${layout}${focusSession ? " quiz-body--session" : ""} tool-enter`}
        {...(focusSession ? { "data-quiz-session": "" } : {})}
      >
        {/* Home is full-bleed: its resume strip has to reach both edges under
            the TopBar, so the screen wraps its own content (`.quiz-col--home`
            + `.quiz-inset--home`, see quiz.css). A focus session is also
            full-bleed so SessionTop can span the viewport; QuizQuestion owns
            the centred column. Results (and error) keep the centred wrap. */}
        {layout === "home" || focusSession
          ? body()
          : <div className={`quiz-col quiz-col--${layout}`}>{body()}</div>}
      </div>
    </FullHeightScreen>
  );
}
