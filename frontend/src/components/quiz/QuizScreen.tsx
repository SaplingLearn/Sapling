"use client";

/**
 * The quiz route's one component: reads the entry off the URL, owns the session,
 * and switches the three screens on `phase`.
 *
 * It replaces the `screens/Quiz.tsx` → `QuizPanel.tsx` chain, whose whole
 * concept-picking job now lives in `QuizHome`. The AI-disclaimer gate is carried
 * over unchanged (it self-gates on `localStorage["sapling_disclaimer_ack"]`, and
 * the chip in the TopBar reopens it on demand).
 *
 * `--quiz-accent` is bound here from the active concept's course colour. That
 * inline custom property is the ONE inline style anywhere under
 * `components/quiz/**` (R-1); everything else is a class over tokens.
 */

import React, { useMemo } from "react";
import type { CSSProperties } from "react";
import { useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { FullHeightScreen } from "../FullHeightScreen";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { DisclaimerModal } from "../DisclaimerModal";
import { useUser } from "@/context/UserContext";
import { useActiveSemester } from "@/lib/useActiveSemester";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { siblingsFor } from "@/lib/graph/neighbourhood";
import { apiToGraphNode } from "@/lib/data";
import { parseEntry } from "@/lib/quiz/source";
import { loadPrefs } from "@/lib/quiz/prefs";
import { colorFor } from "@/lib/quiz/proposals";
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

  const home = useQuizHome(userId ?? "", semesterHydrated ? activeSemester : null);
  const { session, config, actions } = useQuizSession(userId ?? "", entry);

  // The concept the screens are about: whatever the session is running, falling
  // back to the proposal on offer.
  const activeNode = useMemo(() => {
    const byId = session.conceptId
      ? home.nodes.find(n => n.id === session.conceptId)
      : undefined;
    return byId ?? home.primary?.node ?? null;
  }, [home.nodes, home.primary, session.conceptId]);

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

  const prefersReducedMotion = usePrefersReducedMotion();
  const prefs = useMemo(() => loadPrefs(config), [config]);

  // The accent is the one runtime-bound value; an unset one falls through to
  // `var(--accent)` wherever it is read.
  const rootStyle = accent ? ({ "--quiz-accent": accent } as CSSProperties) : undefined;

  const body = () => {
    if (!userReady) return null;
    if (!userId) return <p className="quiz-stub__phase">Sign in to take a quiz.</p>;

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
        />
      );
    }

    return (
      <QuizHome
        userId={userId}
        home={home}
        config={config}
        prefs={prefs}
        entry={entry}
        session={session}
        actions={actions}
      />
    );
  };

  const layout = session.phase === "results"
    ? "results"
    : QUESTION_PHASES.has(session.phase) || session.phase === "error"
      ? "question"
      : "home";

  return (
    <FullHeightScreen className="quiz-root" style={rootStyle}>
      <DisclaimerModal />
      <TopBar title="Quiz" subtitle="Test what you know." actions={<AIDisclaimerChip />} />
      <div className={`quiz-body quiz-body--${layout}`}>
        <div className={`quiz-col quiz-col--${layout}`}>{body()}</div>
      </div>
    </FullHeightScreen>
  );
}
