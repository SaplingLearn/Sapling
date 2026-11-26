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
import { FOCUS_ARC, chipsThatFit, focusCardsLabel } from "./hubModel";
import { Glyph, StatusDot, WarnIcon, shownTools, type GlyphName } from "./hubUi";
import s from "./StudyHub.module.css";
import { ST_LABEL, ring, type Concept } from "./studyModel";
import { leaveOnClick, type ToolKey, type ToolNav } from "./useToolNav";
import { cn } from "@/lib/cn";

/** The gap mark's own chip: the icon, its padding, and the line's gap after
 *  it. Derived, so it cannot drift from what the mark actually renders. */
const GAP_MARK_ICON = 13;
const GAP_MARK_PAD = 6;
const PREREQ_GAP = 6;
const GAP_MARK_W = GAP_MARK_ICON + GAP_MARK_PAD * 2 + PREREQ_GAP;

function MasteryRing({ concept }: { concept: Concept }) {
  return (
    <span className="relative w-18 h-18 shrink-0">
      <svg width="72" height="72" viewBox="0 0 72 72" aria-hidden="true" className="block [transform:rotate(-90deg)]">
        <circle cx="36" cy="36" r="31" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="6.5" />
        <circle cx="36" cy="36" r="31" fill="none" stroke={FOCUS_ARC[concept.st]} strokeWidth="6.5" strokeLinecap="round" strokeDasharray={ring(concept.m, 31)} />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[24px] font-semibold tracking-[-0.02em]">{concept.m}%</span>
    </span>
  );
}

/** "+N more": the prerequisites that did not fit the line, listed on hover or focus. */
function MorePrereqs({ rest }: { rest: Concept[] }) {
  const [open, setOpen] = React.useState(false);
  return (
    <span onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} className="relative shrink-0">
      <span tabIndex={0} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} className="inline-flex items-center h-5.5 py-0 px-2 rounded-[11px] text-accent-fg text-xs font-semibold whitespace-nowrap bg-[rgba(255,255,255,0.22)] cursor-default">+{rest.length} more</span>
      {open && (
        <span className="absolute left-0 top-full pt-1.5 z-25">
          <span className={cn(s.pop, "flex flex-col gap-1.5 min-w-45 py-2 px-2.5 [background:var(--bg-panel)] border border-border shadow-lg rounded-md")}>
            {rest.map(t => (
              <span key={t.id} className="flex items-center gap-2 text-md font-semibold text-text whitespace-nowrap">
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
    <span onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} className="relative shrink-0 flex">
      <span tabIndex={0} aria-label={`${concept.name} · ${concept.gap}`} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        className="inline-flex items-center h-5.5 py-0 px-2 rounded-[11px] text-accent-fg text-xs font-semibold whitespace-nowrap bg-warn-soft cursor-default" style={{ padding: `0 ${GAP_MARK_PAD}px` }}>
        <WarnIcon size={GAP_MARK_ICON} />
      </span>
      {open && (
        <span className="absolute -left-1 top-full pt-1.5 z-25">
          <span role="tooltip" data-testid="focus-gap-warning" className={cn(s.pop, "flex items-start gap-2 w-65 py-2.5 px-3 border rounded-md shadow-lg [background:var(--warn-soft)] border-transparent text-warn text-sm leading-[1.45] text-pretty")}>
            <WarnIcon size={14} />
            <span><strong className="font-bold">{concept.name}</strong> · {concept.gap}</span>
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
    <div className="flex flex-nowrap items-center h-5.5 min-w-0 text-sm text-[rgba(255,255,255,0.86)]" style={{ gap: PREREQ_GAP }}>
      {gapOn && <GapWarning concept={gapOn} />}
      {/* Only the chips clip. The gap mark and "+N more" open their pop-ups
          below the line, and a line that clipped hid both. */}
      <span className="flex items-center min-w-0 overflow-hidden" style={{ gap: PREREQ_GAP }}>
        {prereqs.length === 0 && <span className="shrink-0 whitespace-nowrap">No prerequisites</span>}
        {/* minWidth 0 + ellipsis on each chip: two are shown whether or not they
            fit (chipsThatFit), so one that does not must truncate visibly — the
            row clips, and a hard cut mid-word reads as a rendering bug. The
            title carries the full name either way. */}
        {prereqs.slice(0, fit).map(t => (
          <span key={t.id} title={`${t.name} · ${ST_LABEL[t.st]}`} className="inline-flex items-center h-5.5 py-0 px-2 rounded-[11px] text-accent-fg text-xs font-semibold whitespace-nowrap gap-[5px] min-w-0 bg-[rgba(255,255,255,0.12)]">
            <StatusDot st={t.st} size={7} />
            <span className="min-w-0 overflow-hidden text-ellipsis">{t.name}</span>
          </span>
        ))}
      </span>
      {rest.length > 0 && <MorePrereqs rest={rest} />}
    </div>
  );
}

export function FocusCard({ concept, upNext, masteredExam, prereqs, cardCount, quizShown, nav }: {
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
  nav: ToolNav;
}) {
  const actions: { key: ToolKey; icon: GlyphName; label: string; href: string }[] = [
    { key: "quiz", icon: "bulb", label: "Start quiz", href: nav.quizHref(concept.id) },
    { key: "cards", icon: "cards", label: focusCardsLabel(cardCount), href: nav.cardsHref([concept.name]) },
  ];
  return (
    <div data-testid="focus-card" data-flip="focus" data-flip-how="fade" className={cn(s.focus, "relative rounded-lg [background:var(--sidenav-bg)] text-accent-fg py-4 px-4.5 min-w-0")}>
      {/* The line stays while a clicked concept is shown (only its second half
          is about the queue), so picking one does not change the block's height. */}
      {masteredExam && (
        <p key={`${masteredExam}:${upNext}`} data-testid="focus-fallback-note" data-flip={`focus-note:${masteredExam}:${upNext}`} data-flip-how="fade" className="mt-0 mx-0 mb-2.5 text-sm leading-[1.3] text-[rgba(255,255,255,0.86)]">
          Everything on {masteredExam} is mastered.{upNext && " From the rest of the course:"}
        </p>
      )}
      {/* One row, like the Dashboard's lead plan row: the concept on the
          left, the ways straight into it on the right. Stacked once the
          block is too narrow for that (StudyHub.module.css). */}
      <div key={`${concept.id}:${upNext}`} className={s.focusBody} data-flip={`focus-body:${concept.id}:${upNext}`} data-flip-how="fade">
        <div className={s.focusMain}>
          <span className="font-sans text-sm text-sap-100">{upNext ? "Up Next" : concept.group}</span>
          <div className={s.focusConcept}>
            <MasteryRing concept={concept} />
            <div className="min-w-0 flex flex-col gap-1">
              <span className={cn(s.focusName, "font-display text-2xl font-semibold leading-[1.2] tracking-[-0.01em]")} title={concept.name}>{concept.name}</span>
              <Prereqs prereqs={prereqs} gapOn={concept.gap ? concept : null} />
            </div>
          </div>
        </div>
        {/* Straight into this concept. The header's tool buttons open the
            tools themselves; these start the quiz / deck on what is up next. */}
        <nav aria-label={`Study ${concept.name}`} className={s.focusActions}>
          {shownTools(actions, quizShown).map((ac, i) => (
            <Link key={ac.key} href={ac.href} className={i === 0 ? `${s.focusAct} ${s.focusActPrimary}` : s.focusAct}
              onClick={leaveOnClick(nav.leaveTo, ac.href)}>
              <span aria-hidden="true" className="grid"><Glyph name={ac.icon} size={14} /></span>
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
    return <div key="pending" className={cn(s.focusEmpty, "rounded-lg [background:var(--sidenav-bg)] text-accent-fg py-4 px-4.5")} data-testid="focus-pending" aria-busy="true" data-flip="focus-empty:pending" data-flip-how="fade" />;
  }
  const [title, body] = hasConcepts
    ? ["Every concept is mastered", "Keep them fresh with a mixed quiz before the exam."]
    : ["No concepts yet", "Upload course material in the Library to build this course's roadmap."];
  return (
    <div key={String(hasConcepts)} className={cn(s.focusEmpty, "rounded-lg [background:var(--sidenav-bg)] text-accent-fg py-4 px-4.5 flex flex-col justify-center gap-1.5")} data-flip={`focus-empty:${hasConcepts}`} data-flip-how="fade">
      <span className="font-display text-xl font-semibold">{title}</span>
      <span className="text-md text-[rgba(255,255,255,0.86)]">{body}</span>
    </div>
  );
}
