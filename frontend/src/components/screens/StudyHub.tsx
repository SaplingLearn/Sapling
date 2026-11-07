"use client";

/**
 * The Study landing page: one card per study tool (Study Guide, Flashcards,
 * Quiz), each with a live status line and one action, so a student picks HOW
 * to study before landing inside a tool. `/study` renders this; the tools live
 * at `/study?mode=guide`, `/study?mode=cards` and `/quiz`.
 *
 * Reads only cheap, already-existing endpoints. In particular it does NOT use
 * `useQuizHome`, whose "Ready for you" card fetches an AI one-liner: a landing
 * page must not spend an LLM call per visit. The quiz card instead reuses the
 * pure ranking helpers quiz home is built on (`rankCandidates`/`primaryOf`/
 * `dueSet`), so it names the same concept quiz home will open on.
 */

import React from "react";
import Link from "next/link";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { useUser } from "@/context/UserContext";
import { useFlagMap } from "@/context/FlagsContext";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import {
  getCachedStudyGuides,
  getCourses,
  getFlashcards,
  getGraph,
  type StudyGuideCacheEntry,
} from "@/lib/api";
import { listAttempts } from "@/lib/quiz/api";
import { dueSet, primaryOf, rankCandidates, type Candidate } from "@/lib/quiz/proposals";
import type { GraphNode } from "@/lib/types";
import type { AttemptSummary } from "@/lib/quiz/types";

type Load<T> = { status: "loading" } | { status: "ready"; value: T } | { status: "error" };

type QuizSummary = { primary: Candidate | null; dueCount: number; dueCourses: number };

export function StudyHub() {
  const { userId, userReady } = useUser();
  const { flags, ready: flagsReady } = useFlagMap();
  const [semester, , semesterReady] = useActiveSemester();

  const [guides, setGuides] = React.useState<Load<StudyGuideCacheEntry[]>>({ status: "loading" });
  const [cards, setCards] = React.useState<Load<{ count: number; topics: number }>>({ status: "loading" });
  const [quiz, setQuiz] = React.useState<Load<QuizSummary>>({ status: "loading" });

  const showQuiz = flagsReady && flags.hide_quiz !== "on";

  React.useEffect(() => {
    if (!userReady || !userId || !semesterReady) return;
    let cancelled = false;
    const sem = semester || undefined;

    getCachedStudyGuides(userId)
      .then(r => { if (!cancelled) setGuides({ status: "ready", value: r.guides || [] }); })
      .catch(() => { if (!cancelled) setGuides({ status: "error" }); });

    getFlashcards(userId, undefined, sem)
      .then(r => {
        if (cancelled) return;
        const list = (r.flashcards || []) as Array<{ topic?: string }>;
        const topics = new Set(list.map(c => c.topic).filter(Boolean));
        setCards({ status: "ready", value: { count: list.length, topics: topics.size } });
      })
      .catch(() => { if (!cancelled) setCards({ status: "error" }); });

    Promise.all([
      getCourses(userId),
      getGraph(userId, sem),
      // History only sharpens the rationale; never let it cost the card.
      listAttempts(userId, { limit: 50 }).catch(() => ({ attempts: [] as AttemptSummary[] })),
    ])
      .then(([courseRes, graphRes, attemptRes]) => {
        if (cancelled) return;
        const courses = courseRes.courses || [];
        const scopedCourses = semester ? courses.filter(c => courseInTerm(c, semester)) : courses;
        const allowed = new Set(scopedCourses.map(c => c.course_id));
        const nodes = ((graphRes.nodes || []) as GraphNode[]).filter(
          n => !semester || !n.course_id || allowed.has(n.course_id),
        );
        const candidates = rankCandidates(nodes, scopedCourses, attemptRes.attempts || []);
        const due = dueSet(nodes);
        setQuiz({
          status: "ready",
          value: { primary: primaryOf(candidates), dueCount: due.count, dueCourses: due.courseCount },
        });
      })
      .catch(() => { if (!cancelled) setQuiz({ status: "error" }); });

    return () => { cancelled = true; };
  }, [userReady, userId, semester, semesterReady]);

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <TopBar title="Study" subtitle="Pick a way to study." />
      <div
        data-testid="study-hub"
        style={{
          padding: "28px 32px 40px",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 16,
          alignItems: "stretch",
        }}
      >
        <HubCard
          id="guide"
          href="/study?mode=guide"
          icon="file"
          title="Study Guide"
          blurb="Exam-ready guides built from the documents in your library."
          cta="Open study guides"
          status={<GuideStatus load={guides} />}
        />
        <HubCard
          id="cards"
          href="/study?mode=cards"
          icon="bulb"
          title="Flashcards"
          blurb="Spaced review: flip, rate how well you knew it, repeat."
          cta="Review flashcards"
          status={<CardsStatus load={cards} />}
        />
        {showQuiz && (
          <HubCard
            id="quiz"
            href="/quiz"
            icon="check"
            title="Quiz"
            blurb="Test what you know, starting with what needs work."
            cta="Start a quiz"
            status={<QuizStatus load={quiz} />}
          />
        )}
      </div>
    </div>
  );
}

function HubCard({
  id, href, icon, title, blurb, cta, status,
}: {
  id: string;
  href: string;
  icon: string;
  title: string;
  blurb: string;
  cta: string;
  status: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      data-testid={`study-hub-card-${id}`}
      className="card study-hub-card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
        padding: "var(--pad-lg)",
        minHeight: 260,
        textDecoration: "none",
        color: "var(--text)",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 40, height: 40, borderRadius: "var(--r-sm)",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          background: "var(--accent-soft)", color: "var(--accent)",
        }}
      >
        <Icon name={icon} size={20} />
      </span>
      <div>
        <h2 className="h-serif" style={{ margin: 0, fontSize: 22, fontWeight: 500 }}>{title}</h2>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--text-dim)", lineHeight: 1.5 }}>{blurb}</p>
      </div>
      <div style={{ flex: 1, fontSize: 13 }}>{status}</div>
      <span
        className="study-hub-card__cta"
        style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600, color: "var(--accent)" }}
      >
        {cta} <span aria-hidden>→</span>
      </span>
    </Link>
  );
}

const Muted = ({ children }: { children: React.ReactNode }) => (
  <span style={{ color: "var(--text-muted)" }}>{children}</span>
);

function Label({ children }: { children: React.ReactNode }) {
  return <div className="label-micro" style={{ marginBottom: 6 }}>{children}</div>;
}

function GuideStatus({ load }: { load: Load<StudyGuideCacheEntry[]> }) {
  if (load.status === "loading") return <Muted>Loading…</Muted>;
  if (load.status === "error") return <Muted>Couldn&apos;t load your guides.</Muted>;
  if (load.value.length === 0) return <Muted>No guides yet. Pick a course and an exam to build one.</Muted>;
  return (
    <>
      <Label>Recent</Label>
      {load.value.slice(0, 2).map(g => (
        <div key={g.id} style={{ marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <span style={{ fontWeight: 500 }}>{g.exam_title}</span>
          <Muted> · {g.course_name}</Muted>
        </div>
      ))}
    </>
  );
}

function CardsStatus({ load }: { load: Load<{ count: number; topics: number }> }) {
  if (load.status === "loading") return <Muted>Loading…</Muted>;
  if (load.status === "error") return <Muted>Couldn&apos;t load your cards.</Muted>;
  const { count, topics } = load.value;
  if (count === 0) return <Muted>No cards yet. Generate a deck from any course.</Muted>;
  return (
    <>
      <Label>Your deck</Label>
      <div>
        <span style={{ fontWeight: 500 }}>{count} card{count === 1 ? "" : "s"}</span>
        <Muted> · {topics} topic{topics === 1 ? "" : "s"}</Muted>
      </div>
    </>
  );
}

function QuizStatus({ load }: { load: Load<QuizSummary> }) {
  if (load.status === "loading") return <Muted>Loading…</Muted>;
  if (load.status === "error") return <Muted>Couldn&apos;t load your progress.</Muted>;
  const { primary, dueCount, dueCourses } = load.value;
  if (!primary) return <Muted>Nothing needs review right now.</Muted>;
  return (
    <>
      <Label>Ready for you</Label>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
        <span aria-hidden style={{ width: 8, height: 8, borderRadius: "50%", background: primary.color, flexShrink: 0 }} />
        <span style={{ fontWeight: 500 }}>{primary.node.concept_name}</span>
        {primary.course?.course_code && <Muted>· {primary.course.course_code}</Muted>}
      </div>
      <Muted>
        {dueCount} concept{dueCount === 1 ? "" : "s"} to review across {dueCourses} course{dueCourses === 1 ? "" : "s"}
      </Muted>
    </>
  );
}
