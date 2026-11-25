"use client";

/**
 * W7.5 study-guide drawer scaffold — a Sheet over the quiz that opens guide
 * links and a concept Ask WITHOUT the quiz answer key.
 *
 * Leak rules (Bastani / same as Tutor):
 *  - Never seed the tutor with the quiz stem, options, chosen answer, or key.
 *  - Never fetch `getGuide` detail into this panel (check keys live there even
 *    when withheld until answered — cards + deep links are enough for scaffold).
 *  - Ask uses `guide_ask` origin (AskPanel / askTurn patterns), not `quiz_ask`.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Sheet } from "@/components/ui";
import { newTurnId, type GuideAskOrigin } from "@/lib/api";
import { listGuides } from "@/lib/studyGuide/api";
import type { GuideCard } from "@/lib/studyGuide/types";
import { tutorStepLabel } from "@/components/chat/ChatPanel";
import { BudgetPausedBanner, tutorPauseMessage } from "@/components/learn/BudgetPausedBanner";
import { CrisisSupportCard } from "@/components/safety/CrisisSupportCard";
import type { CrisisSupport } from "@/lib/crisisSupport";
import type { LoopBudgetPause } from "@/lib/api";
import {
  ABORTED,
  askErrorCopy,
  chatWithFallback,
  openTutorSession,
  turnPauseOf,
  type TurnProgress,
} from "./askTurn";

const MarkdownChat = dynamic(
  () => import("@/components/chat/MarkdownChat").then(m => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

const GUIDE_ASK: GuideAskOrigin = { guide: true };

export interface StudyGuideDrawerProps {
  open: boolean;
  onClose: () => void;
  userId: string;
  conceptName: string;
  courseId: string | null;
  courseLabel?: string;
  returnFocusTo?: React.RefObject<HTMLElement | null>;
  testid?: string;
}

interface AskTurn {
  id: number;
  role: "user" | "assistant";
  text: string;
  crisisSupport?: CrisisSupport;
  interrupted?: boolean;
}

/** Concept-only seed — never includes quiz answers (leak-safe contract). */
export function composeGuideAskMessage(conceptName: string, question: string): string {
  return [
    `I'm mid-quiz on ${conceptName} and want help with the concept — not the answer to the current question.`,
    "",
    question.trim(),
  ].join("\n");
}

/** Cards for this course only; never guide detail / answers. */
export function guidesForCourse(guides: GuideCard[], courseId: string | null): GuideCard[] {
  if (!courseId) return [];
  return guides.filter(g => g.course_id === courseId);
}

export function StudyGuideDrawer({
  open,
  onClose,
  userId,
  conceptName,
  courseId,
  courseLabel,
  returnFocusTo,
  testid = "quiz-guide-drawer",
}: StudyGuideDrawerProps) {
  const [guides, setGuides] = useState<GuideCard[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pause, setPause] = useState<LoopBudgetPause | null>(null);
  const [draft, setDraft] = useState("");

  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);
  const runRef = useRef(0);
  const idRef = useRef(0);
  const lastMessageRef = useRef("");
  const lastTurnIdRef = useRef("");
  const partialRef = useRef("");

  const nextId = () => ++idRef.current;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  // List cards only when opened — never guide detail (answer keys).
  useEffect(() => {
    if (!open || !userId) return;
    let cancelled = false;
    setListError(null);
    listGuides(userId)
      .then(res => {
        if (!cancelled) setGuides(guidesForCourse(res.guides, courseId));
      })
      .catch(() => {
        if (!cancelled) {
          setGuides([]);
          setListError("Couldn't load study guides.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, userId, courseId]);

  useEffect(() => {
    if (open) return;
    abortRef.current?.abort();
    if (inFlightRef.current && partialRef.current) {
      const text = partialRef.current;
      setTurns(t => [...t, { id: nextId(), role: "assistant", text, interrupted: true }]);
    }
    setStreaming(null);
    setStatus(null);
    setBusy(false);
    inFlightRef.current = false;
    partialRef.current = "";
  }, [open]);

  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      return;
    }
    if (!wasOpenRef.current) return;
    wasOpenRef.current = false;
    returnFocusTo?.current?.focus();
  }, [open, returnFocusTo]);

  const runTurn = useCallback(
    async (message: string, turnId?: string) => {
      if (!message.trim() || inFlightRef.current) return;
      const run = ++runRef.current;
      const { signal } = (abortRef.current = new AbortController());
      inFlightRef.current = true;
      setBusy(true);
      setError(null);
      setPause(null);
      setStreaming("");
      setStatus(null);
      partialRef.current = "";
      lastMessageRef.current = message;
      lastTurnIdRef.current = turnId ?? newTurnId();

      const progress: TurnProgress = { sawToken: false, partial: "" };
      try {
        let sid = sessionIdRef.current;
        if (!sid) {
          const opened = await openTutorSession(userId, conceptName, courseId, signal, GUIDE_ASK);
          if (run !== runRef.current) return;
          if (opened === ABORTED) return;
          if (typeof opened === "object" && opened !== null) {
            setTurns(t => [...t, { id: nextId(), role: "assistant", text: "", crisisSupport: opened.crisis }]);
            setStreaming(null);
            return;
          }
          if (!opened) throw new Error("The tutor did not start a session.");
          sessionIdRef.current = sid = opened;
        }

        const reply = await chatWithFallback(
          { sid, userId, message, turnId: lastTurnIdRef.current, signal, progress },
          {
            onToken: token => {
              if (run !== runRef.current) return;
              progress.sawToken = true;
              progress.partial += token;
              partialRef.current = progress.partial;
              setStreaming(progress.partial);
              setStatus(null);
            },
            onProgress: step => {
              if (run !== runRef.current || progress.sawToken) return;
              setStatus(tutorStepLabel(step) ?? "Thinking…");
            },
          },
          () => {},
        );
        if (run !== runRef.current) return;
        if (reply === ABORTED) return;
        if (typeof reply === "object") {
          setTurns(t => [
            ...t,
            {
              id: nextId(),
              role: "assistant",
              text: reply.reply ?? "",
              crisisSupport: reply.crisis,
            },
          ]);
        } else {
          setTurns(t => [...t, { id: nextId(), role: "assistant", text: reply || progress.partial }]);
        }
        setStreaming(null);
      } catch (err) {
        if (signal.aborted || run !== runRef.current) return;
        const paused = turnPauseOf(err);
        if (paused) {
          setPause(paused);
          setStreaming(null);
        } else {
          if (progress.partial) {
            setTurns(t => [...t, { id: nextId(), role: "assistant", text: progress.partial, interrupted: true }]);
            setStreaming(null);
          }
          setError(askErrorCopy(err));
        }
      } finally {
        if (run === runRef.current && mountedRef.current) {
          inFlightRef.current = false;
          setBusy(false);
          partialRef.current = "";
        }
      }
    },
    [userId, conceptName, courseId],
  );

  const retry = () => {
    setTurns(t => (t.length > 0 && t[t.length - 1].interrupted ? t.slice(0, -1) : t));
    void runTurn(lastMessageRef.current, lastTurnIdRef.current);
  };

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    const message = composeGuideAskMessage(conceptName, text);
    setTurns(t => [...t, { id: nextId(), role: "user", text }]);
    void runTurn(message);
  };

  const subtitle = courseLabel ? `${conceptName} · ${courseLabel}` : conceptName;
  const homeHref = "/study/guide";

  return (
    <Sheet open={open} onClose={onClose} title="Study guide" testid={testid}>
      <div className="quiz-guide-drawer" data-leak-safe="true">
        <p className="quiz-guide-drawer__lead body-serif">
          Notes for <strong>{subtitle}</strong>. Answer keys stay hidden while you&apos;re mid-quiz.
        </p>

        <section className="quiz-guide-drawer__guides" aria-label="Your study guides">
          <div className="quiz-guide-drawer__row">
            <h3 className="quiz-guide-drawer__h">Your guides</h3>
            <Link href={homeHref} className="quiz-guide-drawer__link" data-testid="quiz-guide-open-home">
              Open study guides
            </Link>
          </div>
          {listError && (
            <p className="quiz-guide-drawer__muted" role="status">
              {listError}
            </p>
          )}
          {guides === null && !listError && (
            <p className="quiz-guide-drawer__muted" role="status">
              Loading guides…
            </p>
          )}
          {guides && guides.length === 0 && !listError && (
            <p className="quiz-guide-drawer__muted" data-testid="quiz-guide-empty">
              No guides for this class yet. Open study guides to make one.
            </p>
          )}
          {guides && guides.length > 0 && (
            <ul className="quiz-guide-drawer__list" data-testid="quiz-guide-list">
              {guides.map(g => (
                <li key={g.id}>
                  <Link
                    href={`/study/guide/${encodeURIComponent(g.id)}`}
                    className="quiz-guide-drawer__card"
                    data-testid={`quiz-guide-card-${g.id}`}
                  >
                    <span className="quiz-guide-drawer__card-title">{g.title}</span>
                    <span className="quiz-guide-drawer__card-meta">{g.scope_label}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="quiz-guide-drawer__ask" aria-label="Ask about this concept">
          <h3 className="quiz-guide-drawer__h">Ask about {conceptName}</h3>
          <p className="quiz-guide-drawer__muted">
            Questions about the concept only — the tutor is not told this quiz&apos;s answers.
          </p>

          <div className="quiz-ask__thread" aria-live="polite">
            {turns.map(turn =>
              turn.crisisSupport ? (
                <React.Fragment key={turn.id}>
                  <CrisisSupportCard support={turn.crisisSupport} />
                  {turn.text && (
                    <div className="quiz-ask__turn--assistant">
                      <MarkdownChat>{turn.text}</MarkdownChat>
                    </div>
                  )}
                </React.Fragment>
              ) : turn.role === "user" ? (
                <p key={turn.id} className="quiz-ask__turn--user">
                  {turn.text}
                </p>
              ) : (
                <div key={turn.id} className="quiz-ask__turn--assistant">
                  <MarkdownChat>{turn.text}</MarkdownChat>
                  {turn.interrupted && (
                    <p className="quiz-ask__interrupted">Interrupted — the tutor didn&apos;t finish.</p>
                  )}
                </div>
              ),
            )}
            {streaming !== null && (
              <div className="quiz-ask__turn--assistant">
                {streaming ? (
                  <MarkdownChat>{streaming}</MarkdownChat>
                ) : (
                  <p className="quiz-ask__pending">{status ?? "Thinking…"}</p>
                )}
              </div>
            )}
            {pause && (
              <BudgetPausedBanner
                testId="quiz-guide-ask-budget-paused"
                resetAt={pause.resetAt}
                sessionCapped={pause.sessionCapped}
                message={tutorPauseMessage(pause.resetAt, pause.sessionCapped)}
              />
            )}
            {error && (
              <div className="quiz-ask__error" role="alert">
                <span>{error}</span>
                <button type="button" className="btn btn--sm" data-testid="quiz-guide-ask-retry" onClick={retry}>
                  Try again
                </button>
              </div>
            )}
          </div>

          <form className="quiz-ask__composer" onSubmit={send}>
            <input
              className="quiz-ask__input"
              type="text"
              value={draft}
              onChange={e => setDraft(e.target.value)}
              placeholder="Ask about the concept…"
              aria-label="Ask about the concept"
              data-testid="quiz-guide-ask-input"
            />
            <button
              type="submit"
              className="btn btn--primary"
              data-testid="quiz-guide-ask-send"
              disabled={!draft.trim() || busy}
              aria-disabled={!draft.trim() || busy}
            >
              Send
            </button>
          </form>
        </section>
      </div>
    </Sheet>
  );
}
