"use client";
// A milestone's page (Tutor redesign, behind `milestones`; design:
// learn/__fixtures__/milestone.design.html, the Claude Design board): the
// exam and its countdown, ONE primary step (a session that prepares for it),
// how many of its concepts are ready, what it covers (each concept's level
// and Learn), the sessions that prepared for it and the study guides saved
// for it. The board's practice exam has nothing behind it and is not built;
// neither is its line about reviews coming up more often (not what the
// scheduler does today).
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useFlag } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import type { EnrolledCourse, LoopGoal } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { LEARNING_COPY, plural } from "@/lib/learningCopy";
import { LEVEL_WORDS, type SkillLevel } from "@/lib/levels";
import { listGuides } from "@/lib/studyGuide/api";
import type { GuideCard } from "@/lib/studyGuide/types";
import { masteryTone } from "./TutorPages";
import { coveredConcepts, milestoneHeadline, prepareGoal, readinessOf, type Milestone } from "./milestones";
import { listSaved, type SavedItem } from "./saved";
import { sessionTitle, shortWhen, type TutorSessionRow } from "./sessions";
import tutorStyles from "./tutor.module.css";
import styles from "./CourseV2.module.css";
import own from "./MilestonePage.module.css";

export const MILESTONE_COPY = {
  prepare: "Prepare in a session",
  covers: "What it covers",
  noneLinked: (title: string) => `No topics are linked to ${title} yet.`,
  allReady: "Every concept it covers is Proficient.",
  sessions: (title: string) => `Sessions for ${title}`,
  saved: (title: string) => `Saved for ${title}`,
  noSessions: "None yet.",
  ready: (n: number, total: number) => `${n} of ${plural(total, "concept")} ${total === 1 ? "is" : "are"} exam-ready`,
} as const;

const LEVEL_ORDER: SkillLevel[] = ["profic", "develop", "novice", "not_started"];

/** "3 Proficient, 3 Developing, 2 Getting started": the levels present, high to low. */
export function levelBreakdown(counts: Record<SkillLevel, number>): string {
  return LEVEL_ORDER.filter((l) => counts[l] > 0).map((l) => `${counts[l]} ${LEVEL_WORDS[l]}`).join(", ");
}

/** `saved_items`: what was saved in the sessions that prepared for it. */
function usePreparedSaved(userId: string, courseId: string, sessionIds: readonly string[], enabled: boolean) {
  const [items, setItems] = useState<SavedItem[]>([]);
  const key = sessionIds.join(",");
  useEffect(() => {
    if (!enabled || !userId || !key) return;
    let live = true;
    const ids = new Set(key.split(","));
    listSaved(userId, { courseId })
      .then((r) => { if (live) setItems((r.items ?? []).filter((i) => ids.has(i.session_id))); })
      .catch(() => { if (live) setItems([]); });
    return () => { live = false; };
  }, [enabled, userId, courseId, key]);
  return enabled && key ? items : [];
}

/** The study guides saved for this exam (a guide names the exam it is for). */
function useExamGuides(courseId: string, title: string, enabled: boolean) {
  const { userId } = useUser();
  const [guides, setGuides] = useState<GuideCard[]>([]);
  useEffect(() => {
    if (!enabled || !userId) return;
    let live = true;
    listGuides(userId)
      .then((r) => { if (live) setGuides((r.guides ?? []).filter((g) => g.course_id === courseId && g.scope_kind === "exam" && g.scope_label === title)); })
      .catch(() => { if (live) setGuides([]); });
    return () => { live = false; };
  }, [enabled, userId, courseId, title]);
  return guides;
}

export function MilestonePage({ course, milestone, conceptIds, nodes, sessions, onBack, onOpen, onLearn, onStartGoal }: {
  course: EnrolledCourse;
  milestone: Milestone;
  /** The concepts it covers (the topic checklist's links); null while loading. */
  conceptIds: string[] | null;
  nodes: GraphNode[];
  sessions: TutorSessionRow[];
  onBack: () => void;
  onOpen: (row: TutorSessionRow) => void;
  onLearn: (concept: { id: string; name: string }) => void;
  onStartGoal: (topic: string, goal: LoopGoal) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
    heading.current?.focus({ preventScroll: true });
  }, []);
  const studyShown = useFlag("hide_study") !== "on";
  const guides = useExamGuides(course.course_id, milestone.title, studyShown);
  const concepts = conceptIds ? coveredConcepts(conceptIds, nodes) : [];
  const ladder = nodes.some((n) => Object.prototype.hasOwnProperty.call(n, "skill"));
  const { ready, total, counts } = readinessOf(concepts);
  const plan = prepareGoal(milestone, concepts);
  const prepared = sessions.filter((s) => s.topic === `Prepare for ${milestone.title}`);
  const { userId } = useUser();
  const savedItems = usePreparedSaved(userId, course.course_id, prepared.map((s) => s.id), useFlag("saved_items") === "on");
  const courseName = course.course_code || course.course_name;
  return (
    <div className={styles.page} data-testid="tutor-milestone" data-milestone-id={milestone.id}>
      <div className={styles.col}>
        <div className={own.head}>
          <button type="button" className={own.back} onClick={onBack} data-testid="tutor-milestone-back">{courseName}</button>
          <div className={own.titleRow}>
            <h2 ref={heading} tabIndex={-1} className={`h-serif ${own.title}`}>{milestoneHeadline(milestone)}</h2>
            <button type="button" className="btn btn--primary" data-testid="tutor-milestone-prepare" disabled={!plan}
              onClick={() => { if (plan) onStartGoal(plan.topic, plan.goal); }}>
              {MILESTONE_COPY.prepare}
            </button>
          </div>
        </div>

        {conceptIds !== null && (total > 0 ? (
          <section aria-labelledby="tutor-milestone-ready" className={styles.section}>
            <h3 id="tutor-milestone-ready" className={`h-serif ${styles.h2}`}>{MILESTONE_COPY.ready(ready, total)}</h3>
            <p className={styles.sub} data-testid="tutor-milestone-levels">{levelBreakdown(counts)}</p>
          </section>
        ) : (
          <p className={styles.sub} data-testid="tutor-milestone-unlinked">{MILESTONE_COPY.noneLinked(milestone.title)}</p>
        ))}

        <div className={styles.grid}>
          <div className={styles.stack}>
            {total > 0 && (
              <section aria-labelledby="tutor-milestone-covers" className={styles.section}>
                <h3 id="tutor-milestone-covers" className={`h-serif ${styles.h2}`}>{MILESTONE_COPY.covers}</h3>
                {!plan && <p className={styles.sub}>{MILESTONE_COPY.allReady}</p>}
                <ul className={styles.box}>
                  {concepts.map((c) => {
                    const word = LEVEL_WORDS[c.level];
                    const pct = c.score == null ? 0 : Math.round(Math.max(0, Math.min(1, c.score)) * 100);
                    return (
                      <li key={c.id} className={styles.readyRow} data-testid={`tutor-milestone-concept-${c.id}`} data-level={c.level}>
                        <span className={styles.name}>{c.name}</span>
                        <span className={tutorStyles.bar} role="meter" aria-label={`${c.name} skill`} aria-valuetext={word}
                          aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                          {c.score != null && <i style={{ "--fill": `${pct}%`, "--tone": masteryTone(c.score, ladder) } as React.CSSProperties} />}
                        </span>
                        <span className={styles.dim}>{word}</span>
                        <button type="button" className={styles.rowLink} aria-label={`${LEARNING_COPY.learn} ${c.name}`}
                          onClick={() => onLearn({ id: c.id, name: c.name })}>{LEARNING_COPY.learn}</button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
          </div>
          <div className={styles.stack}>
            <section aria-labelledby="tutor-milestone-sessions" className={styles.section}>
              <h3 id="tutor-milestone-sessions" className={`h-serif ${styles.h2}`}>{MILESTONE_COPY.sessions(milestone.title)}</h3>
              {prepared.length > 0 ? (
                <ul className={styles.box}>
                  {prepared.slice(0, 4).map((s) => (
                    <li key={s.id}>
                      <button type="button" className={styles.sessionRow} onClick={() => onOpen(s)}>
                        <span className={`${tutorStyles.sdot} ${s.open ? tutorStyles.sdotOn : ""}`} aria-hidden />
                        <span className={styles.name}>{sessionTitle(s, course)}</span>
                        <span className={styles.dim}>{shortWhen(s.startedAt)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : <p className={styles.sub}>{MILESTONE_COPY.noSessions}</p>}
            </section>
            {(guides.length > 0 || savedItems.length > 0) && (
              <section aria-labelledby="tutor-milestone-saved" className={styles.section}>
                <h3 id="tutor-milestone-saved" className={`h-serif ${styles.h2}`}>{MILESTONE_COPY.saved(milestone.title)}</h3>
                <ul className={styles.box}>
                  {guides.map((g) => (
                    <li key={g.id} className={styles.dueRow}>
                      <Link href={`/study/guide/${g.id}`} className={styles.name} data-testid={`tutor-milestone-guide-${g.id}`}>{g.title}</Link>
                      <span className={styles.dim}>Study guide</span>
                    </li>
                  ))}
                  {savedItems.map((i) => (
                    <li key={i.id} className={styles.dueRow} data-testid={`tutor-milestone-saved-${i.id}`}>
                      <details className={styles.name}>
                        <summary>{i.title}</summary>
                        <p className={own.savedText}>{i.content}</p>
                      </details>
                      <span className={styles.dim}>Saved</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
