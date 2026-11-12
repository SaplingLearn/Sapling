"use client";
/**
 * The Up Next block beside the readiness figure: the concept to work on (the
 * clicked one, else the head of the study queue), what it rests on, and the
 * ways straight into it. With nothing to work on it says why instead.
 *
 * It follows the CLICKED concept, never the hovered one: it is in flow above
 * the roadmap and changes height with the concept, so previewing the hovered
 * tile here pushed the whole roadmap up or down under the pointer.
 */
import React from "react";
import Link from "next/link";
import { FOCUS_ARC, chipsThatFit, focusCardsLabel } from "./hubModel";
import { DISPLAY, Glyph, MONO, POPOVER, StatusDot, shownTools, type GlyphName } from "./hubUi";
import s from "./StudyHub.module.css";
import { ST_LABEL, ring, type Concept } from "./studyModel";
import { leaveOnClick, type ToolKey, type ToolNav } from "./useToolNav";

/* `.label-micro`, for the one place it sits on the dark block. */
const MICRO_ON_DARK: React.CSSProperties = { fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--sap-100)" };
const BLOCK: React.CSSProperties = { borderRadius: "var(--r-lg)", background: "var(--sidenav-bg)", color: "#FFFFFF", padding: "16px 18px" };
const CHIP: React.CSSProperties = { display: "inline-flex", alignItems: "center", height: 22, padding: "0 8px", borderRadius: 11, color: "#FFFFFF", fontSize: "var(--fs-xs)", fontWeight: 600, whiteSpace: "nowrap" };

function MasteryRing({ concept }: { concept: Concept }) {
  return (
    <span style={{ position: "relative", width: 54, height: 54, flexShrink: 0 }}>
      <svg width="54" height="54" viewBox="0 0 54 54" aria-hidden="true" style={{ display: "block", transform: "rotate(-90deg)" }}>
        <circle cx="27" cy="27" r="23" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="5" />
        <circle cx="27" cy="27" r="23" fill="none" stroke={FOCUS_ARC[concept.st]} strokeWidth="5" strokeLinecap="round" strokeDasharray={ring(concept.m, 23)} />
      </svg>
      <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "var(--fs-base)", fontWeight: 600 }}>{concept.m}%</span>
    </span>
  );
}

/** "+N more": the prerequisites that did not fit the line, listed on hover or focus. */
function MorePrereqs({ rest }: { rest: Concept[] }) {
  const [open, setOpen] = React.useState(false);
  return (
    <span onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} style={{ position: "relative", flexShrink: 0 }}>
      <span tabIndex={0} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} style={{ ...CHIP, background: "rgba(255,255,255,0.22)", cursor: "default" }}>+{rest.length} more</span>
      {open && (
        <span style={{ position: "absolute", left: 0, top: "100%", paddingTop: 6, zIndex: 25 }}>
          <span className={s.pop} style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 180, padding: "8px 10px", ...POPOVER, borderRadius: "var(--r-md)" }}>
            {rest.map(t => (
              <span key={t.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "var(--fs-md)", fontWeight: 600, color: "var(--text)", whiteSpace: "nowrap" }}>
                <StatusDot st={t.st} size={8} />{t.name}
              </span>
            ))}
          </span>
        </span>
      )}
    </span>
  );
}

/** One fixed-height line: the chips that fit, then "+N more". */
function Prereqs({ prereqs }: { prereqs: Concept[] }) {
  const fit = chipsThatFit(prereqs.map(t => t.name));
  const rest = prereqs.slice(fit);
  return (
    <div style={{ display: "flex", flexWrap: "nowrap", alignItems: "center", gap: 6, height: 22, fontSize: "var(--fs-sm)", color: "rgba(255,255,255,0.86)" }}>
      {prereqs.length === 0 && <span style={{ flexShrink: 0, whiteSpace: "nowrap" }}>No prerequisites</span>}
      {prereqs.slice(0, fit).map(t => (
        <span key={t.id} title={`${t.name} · ${ST_LABEL[t.st]}`} style={{ ...CHIP, gap: 5, background: "rgba(255,255,255,0.12)" }}>
          <StatusDot st={t.st} size={7} />{t.name}
        </span>
      ))}
      {rest.length > 0 && <MorePrereqs rest={rest} />}
    </div>
  );
}

export function FocusCard({ concept, upNext, prereqs, cardCount, quizShown, nav }: {
  concept: Concept;
  /** It is the head of the study queue (rather than a concept the student clicked off it). */
  upNext: boolean;
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
    <div data-testid="focus-card" className={s.focus} style={{ position: "relative", ...BLOCK, minWidth: 0 }}>
      {/* One row, like the Dashboard's lead plan row: the concept on the
          left, the ways straight into it on the right. Stacked once the
          block is too narrow for that (StudyHub.module.css). */}
      <div className={s.focusBody}>
        <div className={s.focusMain}>
          <span style={MICRO_ON_DARK}>{upNext ? "Up Next" : concept.group}</span>
          <div className={s.focusConcept}>
            <MasteryRing concept={concept} />
            <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
              <span className={s.focusName} title={concept.name} style={{ fontFamily: DISPLAY, fontSize: 22, fontWeight: 600, lineHeight: 1.2, letterSpacing: "-0.01em" }}>{concept.name}</span>
              <Prereqs prereqs={prereqs} />
            </div>
          </div>
        </div>
        {/* Straight into this concept. The header's tool buttons open the
            tools themselves; these start the quiz / deck on what is up next. */}
        <nav aria-label={`Study ${concept.name}`} className={s.focusActions}>
          {shownTools(actions, quizShown).map((ac, i) => (
            <Link key={ac.key} href={ac.href} className={i === 0 ? `${s.focusAct} ${s.focusActPrimary}` : s.focusAct}
              onClick={leaveOnClick(nav.leaveTo, ac.href)}>
              <span aria-hidden="true" style={{ display: "grid" }}><Glyph name={ac.icon} size={14} /></span>
              {ac.label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}

/** The block with nothing to work on: every concept mastered, or none yet. */
export function FocusEmpty({ hasConcepts }: { hasConcepts: boolean }) {
  const [title, body] = hasConcepts
    ? ["Every concept is mastered", "Keep them fresh with a mixed quiz before the exam."]
    : ["No concepts yet", "Upload course material in the Library to build this course's roadmap."];
  return (
    <div className={s.focusEmpty} style={{ ...BLOCK, display: "flex", flexDirection: "column", justifyContent: "center", gap: 6 }}>
      <span style={{ fontFamily: DISPLAY, fontSize: "var(--fs-xl)", fontWeight: 600 }}>{title}</span>
      <span style={{ fontSize: "var(--fs-md)", color: "rgba(255,255,255,0.86)" }}>{body}</span>
    </div>
  );
}
