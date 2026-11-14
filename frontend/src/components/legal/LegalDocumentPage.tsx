import type { CSSProperties } from "react";
import { ACCENT, BODY, DISPLAY, INK, MONO, MUTED, SERIF } from "@/lib/landing/companionType";
import { legalDateLabel, type LegalDocument, type LegalSection } from "@/lib/legal/documents";

/**
 * A legal document as the public /terms and /privacy pages show it, on the
 * shared companion chrome (the pages wrap it in CompanionShell, which supplies
 * the header, the footer and the page box). The text, the version and its
 * date come from lib/legal/documents.ts, the same objects onboarding renders,
 * so the published document and the one a student agrees to are one.
 *
 * The layout is the interesting half. The box is 1116px wide and these pages
 * used to set 15px prose in an 880px box of their own; dropped in as-is the
 * line ran past 145 characters. Capping the prose instead — a narrow column
 * pinned inside a frame everything else fills — is the failure /about
 * shipped: the h1 and the rules run the full width while every paragraph
 * hugs the left, and the page reads as broken rather than as narrow.
 *
 * So the document is built as columns rather than capped inside one, the way
 * /wiki was (#604). Each clause is a row: its heading in a fixed column, its
 * text in the rest. That leaves the prose 812px, and the type comes up to meet
 * it: 21px Spectral, measured in a browser at 1440px off real line boxes,
 * reads at a median 86-88 characters a line. Nothing is capped, so the row
 * rules, the masthead and every clause share one right edge.
 *
 * The Privacy Policy carries four section shapes the Terms does not —
 * labelled sub-lists, bolded highlight rows, a trailing paragraph after a
 * list, and a sentence that resumes after an inline mail link. All four
 * render inside the one text cell, so they share the clause measure and the
 * clause left edge.
 */

const RULE = "1px solid rgba(42,39,31,0.08)";
/** Sized off the longest clause titles ("6. Study Rooms and Social Features",
 * "4. How We Share Your Information"). */
const TITLE_COL = 220;
const COL_GAP = 32;

/**
 * A clause row.
 *
 * Wrapping flex rather than a grid so the two columns collapse to one on a
 * narrow screen: inline styles cannot carry a media query and these pages
 * have no stylesheet of their own. The text cell's 460px basis is what
 * triggers it — below ~764px of content width there is no room for both.
 */
const ROW: CSSProperties = {
  display: "flex", flexWrap: "wrap", alignItems: "flex-start",
  gap: COL_GAP, padding: "22px 0", borderTop: RULE,
};
/**
 * Both cells grow, but the text cell grows a thousand times harder. Side by
 * side that is invisible — the heading takes 264.35px of the 1116 rather than
 * 264 — and once the row wraps it is the whole point: each cell is alone on
 * its line and stretches to fill it, so the stacked heading keeps the same
 * right edge as the text under it instead of stopping 60px short.
 */
const TITLE_CELL: CSSProperties = { flex: `1 1 ${TITLE_COL}px`, maxWidth: "100%", minWidth: 0 };
const TEXT_CELL: CSSProperties = { flex: "999 1 330px", minWidth: 0 };

const H2: CSSProperties = {
  margin: 0, fontSize: 14.5, fontWeight: 600, lineHeight: 1.45,
  letterSpacing: "-0.01em", color: INK,
};
const PROSE: CSSProperties = {
  margin: 0, fontFamily: SERIF, fontSize: 16, lineHeight: 1.62, color: BODY,
};
const LIST: CSSProperties = {
  margin: "14px 0 0", padding: 0, listStyle: "none",
  display: "flex", flexDirection: "column", gap: 10,
};
const ITEM: CSSProperties = { ...PROSE, display: "flex", gap: 12 };
const BULLET: CSSProperties = { color: MUTED, flex: "0 0 auto" };
/** The sans label that introduces a sub-list, held off the serif around it. */
const SUBLABEL: CSSProperties = {
  margin: 0, fontSize: 14, fontWeight: 600, letterSpacing: "-0.005em", color: INK,
};
const META: CSSProperties = {
  display: "block", fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.04em", color: MUTED,
};
const LINK: CSSProperties = { color: ACCENT };

/** Rows fade in down the page; the cap keeps the last clause from waiting. */
function enter(i: number): CSSProperties {
  return { animation: "fadeUp 700ms ease both", animationDelay: `${Math.min(120 + i * 40, 640)}ms` };
}

function Bulleted({ items, style }: { items: React.ReactNode[]; style?: CSSProperties }) {
  return (
    <ul style={{ ...LIST, ...style }}>
      {items.map((item, i) => (
        <li key={i} style={ITEM}>
          <span style={BULLET}>&bull;</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function SectionText({ section }: { section: LegalSection }) {
  return (
    <>
      {section.body && (
        <p style={PROSE}>
          {section.body}
          {section.link && <a href={section.link.href} style={LINK}>{section.link.label}</a>}
          {section.bodySuffix}
        </p>
      )}

      {section.list && <Bulleted items={section.list} />}

      {section.subsections && (
        <div style={{ marginTop: section.body ? 16 : 0, display: "flex", flexDirection: "column", gap: 22 }}>
          {section.subsections.map((sub) => (
            <div key={sub.label}>
              <p style={SUBLABEL}>{sub.label}</p>
              <Bulleted items={sub.list} style={{ marginTop: 10 }} />
            </div>
          ))}
        </div>
      )}

      {section.highlights && (
        <Bulleted
          items={section.highlights.map((h) => (
            <>
              <strong style={{ color: INK, fontWeight: 600 }}>{h.label}</strong> {h.text}
            </>
          ))}
        />
      )}

      {section.bodyAfter && <p style={{ ...PROSE, marginTop: 16 }}>{section.bodyAfter}</p>}
    </>
  );
}

export function LegalDocumentPage({ doc }: { doc: LegalDocument }) {
  return (
    <div>
      {/* No rule of its own: the first clause row below carries a
          `borderTop`, so a masthead border drew a second line 48px above
          it — two hairlines stacked between the title and the date. The
          row rule is the structural one (every clause has one), so the
          masthead defers to it and only keeps the space. */}
      <header style={{ paddingBottom: 30 }}>
        <span
          style={{
            display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em",
            textTransform: "uppercase", color: MUTED, animation: "fadeUp 600ms ease both",
          }}
        >
          Legal
        </span>
        <h1
          style={{
            margin: "14px 0 0", fontFamily: DISPLAY, fontWeight: 500, fontSize: 34,
            lineHeight: 1.15, letterSpacing: "-0.015em", color: INK,
            animation: "fadeUp 700ms ease 60ms both",
          }}
        >
          {doc.title}
        </h1>
      </header>

      <div>
        {/* The date is metadata about the document, so it takes the heading
            column and the preamble takes the text column. That puts the
            opening paragraph on the same measure and the same left edge as
            every clause under it, instead of running the full width alone. */}
        <div style={{ ...ROW, ...enter(0) }}>
          <div style={TITLE_CELL}>
            <span style={META} data-testid="legal-updated">Last updated: {legalDateLabel(doc.version)}</span>
          </div>
          <div style={TEXT_CELL}>
            <p style={PROSE}>{doc.preamble}</p>
          </div>
        </div>

        {doc.sections.map((section, i) => (
          <div key={section.title} style={{ ...ROW, ...enter(i + 1) }}>
            <div style={TITLE_CELL}>
              <h2 style={H2}>{section.title}</h2>
            </div>
            <div style={TEXT_CELL}>
              <SectionText section={section} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
