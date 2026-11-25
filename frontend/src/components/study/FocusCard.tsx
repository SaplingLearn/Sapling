"use client";
/**
 * The Up Next block beside the readiness figure: the concept to work on (the
 * clicked one, else the head of the selected exam's study queue), what it
 * rests on, and the ways straight into it. With nothing to work on it says
 * why instead.
 *
 * It follows the CLICKED concept, never the hovered one: it is in flow above
 * the roadmap and changes height with the concept, so previewing the hovered
 * tile here pushed the whole roadmap up or down under the pointer.
 *
 * On a change of exam the block stays where it is and its content is
 * crossfaded by the hub's useFlip (the `data-flip` parts; the body's key
 * carries the concept, so a new concept is a new body).
 */
import React from "react";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { HANDOFF_COPY } from "@/lib/learningHandoffs";
import { FOCUS_ARC, chipsThatFit, focusCardsLabel } from "./hubModel";
import { Glyph, StatusDot, WarnIcon, shownTools, type GlyphName } from "./hubUi";
import f from "./FocusCard.module.css";
import s from "./StudyHub.module.css";
import { ST_LABEL, ring, type Concept } from "./studyModel";
import { leaveOnClick, type ToolKey, type ToolNav } from "./useToolNav";

/* Every word on the block is --sidenav-fg (white, 4.85:1 on the olive), its
   chips a dark --sidenav-wash under it (globals.css, spec §13 A135). A paler
   tint for secondary text (the micro label was --sap-100, the notes 86% white)
   missed AA at these sizes, so the hierarchy is size, weight and case. */
/** The gap mark's own chip: the icon, its padding, and the line's gap after
 *  it. Derived, so it cannot drift from what the mark actually renders. */
const GAP_MARK_ICON = 13;
const GAP_MARK_PAD = 6;
const PREREQ_GAP = 6;
const GAP_MARK_W = GAP_MARK_ICON + GAP_MARK_PAD * 2 + PREREQ_GAP;
/** The same two numbers, handed to the stylesheet (FocusCard.module.css). */
const LINE_VARS = { "--prereq-gap": `${PREREQ_GAP}px`, "--gap-mark-pad": `${GAP_MARK_PAD}px` } as React.CSSProperties;
/** The mastery ring's geometry (SVG user units: its 72px box). */
const RING = { box: 72, r: 31, stroke: 6.5 } as const;

function MasteryRing({ concept }: { concept: Concept }) {
  return (
    <span className={f.ringBox}>
      <svg width={RING.box} height={RING.box} viewBox={`0 0 ${RING.box} ${RING.box}`} aria-hidden="true" className={f.ringSvg}>
        <circle cx={RING.box / 2} cy={RING.box / 2} r={RING.r} fill="none" className={f.ringTrack} strokeWidth={RING.stroke} />
        <circle cx={RING.box / 2} cy={RING.box / 2} r={RING.r} fill="none" stroke={FOCUS_ARC[concept.st]} strokeWidth={RING.stroke} strokeLinecap="round" strokeDasharray={ring(concept.m, RING.r)} className={s.ring} />
      </svg>
      <span className={f.ringPct}>{concept.m}%</span>
    </span>
  );
}

/** "+N more": the prerequisites that did not fit the line, listed on hover or focus. */
function MorePrereqs({ rest }: { rest: Concept[] }) {
  const [open, setOpen] = React.useState(false);
  return (
    <span onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} className={f.hoverAnchor}>
      <span tabIndex={0} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} className={`${f.chip} ${f.chipMore}`}>+{rest.length} more</span>
      {open && (
        <span className={f.popAnchor}>
          <span className={`${s.pop} ${s.popover} ${f.moreList}`}>
            {rest.map(t => (
              <span key={t.id} className={f.moreRow}>
                <StatusDot st={t.st} size={8} />{t.name}
              </span>
            ))}
          </span>
        </span>
      )}
    </span>
  );
}

/**
 * The focused concept's unmet prerequisite: an amber mark at the head of the
 * prerequisite line, opening the reason on hover or focus.
 *
 * A POP-UP rather than the banner this was beside the readiness figure. The
 * block is deliberately the same height whichever concept is in it, and the
 * figure beside it is centred; a warning in flow came and went with the
 * selection and moved the roadmap (or the percentage) each time. An overlay
 * costs no layout, and it sits on the line it is about — the one naming the
 * prerequisites it says are not mastered yet.
 */
function GapWarning({ concept }: { concept: Concept }) {
  const [open, setOpen] = React.useState(false);
  return (
    <span onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} className={`${f.hoverAnchor} ${f.hoverAnchorFlex}`}>
      {/* A button, not a focusable span: a span may not carry a name of its
          own (axe aria-prohibited-attr), and this one has no text to read. */}
      <button type="button" aria-label={`${concept.name} · ${concept.gap}`} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        className={`${f.chip} ${f.chipGap}`}>
        <WarnIcon size={GAP_MARK_ICON} />
      </button>
      {open && (
        <span className={`${f.popAnchor} ${f.popAnchorNudge}`}>
          <span role="tooltip" data-testid="focus-gap-warning" className={`${s.pop} ${f.gapTip}`}>
            <WarnIcon size={14} />
            <span><strong className={f.gapTipName}>{concept.name}</strong> · {concept.gap}</span>
          </span>
        </span>
      )}
    </span>
  );
}

/** One fixed-height line: the gap mark, the chips that fit, then "+N more". */
function Prereqs({ prereqs, gapOn }: { prereqs: Concept[]; gapOn: Concept | null }) {
  const fit = chipsThatFit(prereqs.map(t => t.name), gapOn ? GAP_MARK_W : 0);
  const rest = prereqs.slice(fit);
  return (
    <div className={f.prereqs} style={LINE_VARS}>
      {gapOn && <GapWarning concept={gapOn} />}
      {/* Only the chips clip. The gap mark and "+N more" open their pop-ups
          below the line, and a line that clipped hid both. */}
      <span className={f.prereqChips}>
        {prereqs.length === 0 && <span className={f.noPrereqs}>No prerequisites</span>}
        {/* minWidth 0 + ellipsis on each chip: two are shown whether or not they
            fit (chipsThatFit), so one that does not must truncate visibly — the
            row clips, and a hard cut mid-word reads as a rendering bug. The
            title carries the full name either way. */}
        {prereqs.slice(0, fit).map(t => (
          <span key={t.id} title={`${t.name} · ${ST_LABEL[t.st]}`} className={`${f.chip} ${f.chipPrereq}`}>
            <StatusDot st={t.st} size={7} />
            <span className={f.clipText}>{t.name}</span>
          </span>
        ))}
      </span>
      {rest.length > 0 && <MorePrereqs rest={rest} />}
    </div>
  );
}

export function FocusCard({ concept, upNext, masteredExam, prereqs, cardCount, quizShown, tutorShown = true, nav }: {
  concept: Concept;
  /** It is the head of the study queue (rather than a concept the student clicked off it). */
  upNext: boolean;
  /** The selected exam, once all it covers is mastered: the queue is then the rest of the course's. */
  masteredExam: string | null;
  /** The concepts it rests on, as the graph has them. */
  prereqs: Concept[];
  /** Flashcards the student already has on it. */
  cardCount: number;
  quizShown: boolean;
  /** False while `hide_tutor` hides Tutor (W3.4). */
  tutorShown?: boolean;
  nav: ToolNav;
}) {
  type FocusAction = { key: ToolKey | "learn"; icon: GlyphName | "clover"; label: string; href: string; testId: string };
  const actions: FocusAction[] = [
    // Primary stays "Start quiz" (W7.D2); Guide uses "Quiz this concept".
    { key: "quiz", icon: "bulb", label: "Start quiz", href: nav.quizHref(concept.id), testId: "focus-quiz" },
    { key: "cards", icon: "cards", label: focusCardsLabel(cardCount), href: nav.cardsHref([concept.name]), testId: "focus-cards" },
  ];
  if (tutorShown) {
    actions.push({
      key: "learn",
      icon: "clover",
      label: HANDOFF_COPY.continueInTutor,
      href: nav.learnHref(concept.id, concept.name),
      testId: "focus-learn",
    });
  }
  const visible = shownTools(actions, quizShown);
  return (
    <div data-testid="focus-card" data-flip="focus" data-flip-how="fade" className={`${s.focus} ${f.block}`}>
      {/* The line stays while a clicked concept is shown (only its second half
          is about the queue), so picking one does not change the block's height. */}
      {masteredExam && (
        <p key={`${masteredExam}:${upNext}`} data-testid="focus-fallback-note" data-flip={`focus-note:${masteredExam}:${upNext}`} data-flip-how="fade" className={f.fallbackNote}>
          Everything on {masteredExam} is mastered.{upNext && " From the rest of the course:"}
        </p>
      )}
      {/* One row, like the Dashboard's lead plan row: the concept on the
          left, the ways straight into it on the right. Stacked once the
          block is too narrow for that (StudyHub.module.css). */}
      <div key={`${concept.id}:${upNext}`} className={s.focusBody} data-flip={`focus-body:${concept.id}:${upNext}`} data-flip-how="fade">
        <div className={s.focusMain}>
          <span className={f.micro}>{upNext ? "Up Next" : concept.group}</span>
          <div className={s.focusConcept}>
            <MasteryRing concept={concept} />
            <div className={f.nameCol}>
              <span className={`${s.focusName} ${f.name}`} title={concept.name}>{concept.name}</span>
              <Prereqs prereqs={prereqs} gapOn={concept.gap ? concept : null} />
            </div>
          </div>
        </div>
        {/* Straight into this concept. The header's tool buttons open the
            tools themselves; these start the quiz / deck / tutor on what is up next. */}
        <nav aria-label={`Study ${concept.name}`} className={s.focusActions}>
          {visible.map((ac, i) => (
            <Link key={ac.key} href={ac.href} data-testid={ac.testId}
              className={i === 0 ? `${s.focusAct} ${s.focusActPrimary}` : s.focusAct}
              onClick={leaveOnClick(nav.leaveTo, ac.href)}>
              <span aria-hidden="true" className={f.actIcon}>
                {ac.icon === "clover"
                  ? <Icon name="clover" size={14} />
                  : <Glyph name={ac.icon} size={14} />}
              </span>
              {ac.label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}

/**
 * The block with nothing to work on: every concept mastered, or none yet.
 * `pending` while what the selected exam covers is still being read: the
 * block keeps its place and says nothing, as the roadmap under it does.
 */
export function FocusEmpty({ hasConcepts, pending = false }: { hasConcepts: boolean; pending?: boolean }) {
  if (pending) {
    return <div key="pending" data-testid="focus-pending" aria-busy="true" data-flip="focus-empty:pending" data-flip-how="fade" className={`${s.focusEmpty} ${f.block}`} />;
  }
  const [title, body] = hasConcepts
    ? ["Every concept is mastered", "Keep them fresh with a mixed quiz before the exam."]
    : ["No concepts yet", "Upload course material in the Library to build this course's roadmap."];
  return (
    <div key={String(hasConcepts)} className={`${s.focusEmpty} ${f.block} ${f.emptyBlock}`} data-flip={`focus-empty:${hasConcepts}`} data-flip-how="fade">
      <span className={f.emptyTitle}>{title}</span>
      <span className={f.emptyBody}>{body}</span>
    </div>
  );
}
