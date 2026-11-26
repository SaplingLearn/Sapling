import type { CSSProperties } from "react";
import { legalDateLabel, type LegalDocument, type LegalSection } from "@/lib/legal/documents";
import { cn } from "@/lib/cn";

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

/** Rows fade in down the page; the cap keeps the last clause from waiting. */
function enter(i: number): CSSProperties {
  return { animation: "fadeUp 700ms ease both", animationDelay: `${Math.min(120 + i * 40, 640)}ms` };
}

function Bulleted({ items, style }: { items: React.ReactNode[]; style?: CSSProperties }) {
  return (
    <ul className="mt-3.5 mx-0 mb-0 p-0 list-none flex flex-col gap-2.5" style={{ ...style }}>
      {items.map((item, i) => (
        <li key={i} className="m-0 font-serif text-lg leading-[1.62] text-ink-600 flex gap-3">
          <span className="text-text-muted flex-[0_0_auto]">&bull;</span>
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
        <p className="m-0 font-serif text-lg leading-[1.62] text-ink-600">
          {section.body}
          {section.link && <a href={section.link.href} className="text-brand-forest-bright">{section.link.label}</a>}
          {section.bodySuffix}
        </p>
      )}

      {section.list && <Bulleted items={section.list} />}

      {section.subsections && (
        <div className={cn("flex flex-col gap-5.5", section.body ? "mt-4" : "mt-0")}>
          {section.subsections.map((sub) => (
            <div key={sub.label}>
              <p className="m-0 text-base font-semibold tracking-[-0.005em] text-ink-800">{sub.label}</p>
              <Bulleted items={sub.list} style={{ marginTop: 10 }} />
            </div>
          ))}
        </div>
      )}

      {section.highlights && (
        <Bulleted
          items={section.highlights.map((h) => (
            <>
              <strong className="text-ink-800 font-semibold">{h.label}</strong> {h.text}
            </>
          ))}
        />
      )}

      {section.bodyAfter && <p className="m-0 font-serif text-lg leading-[1.62] text-ink-600 mt-4">{section.bodyAfter}</p>}
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
      <header className="pb-7.5">
        <span
          className="block font-sans text-sm text-text-muted [animation:fadeUp_600ms_ease_both]"
        >
          Legal
        </span>
        <h1
          className="mt-3.5 mx-0 mb-0 font-display font-medium text-[34px] leading-[1.15] tracking-[-0.015em] text-ink-800 [animation:fadeUp_700ms_ease_60ms_both]"
        >
          {doc.title}
        </h1>
      </header>

      <div>
        {/* The date is metadata about the document, so it takes the heading
            column and the preamble takes the text column. That puts the
            opening paragraph on the same measure and the same left edge as
            every clause under it, instead of running the full width alone. */}
        <div className="flex flex-wrap items-start gap-8 py-5.5 px-0 border-t border-t-[rgba(42,39,31,0.08)]" style={{ ...enter(0) }}>
          <div className="flex-[1_1_220px] max-w-full min-w-0">
            <span className="block font-sans text-[10.5px] tracking-[0.04em] text-text-muted" data-testid="legal-updated">Last updated: {legalDateLabel(doc.version)}</span>
          </div>
          <div className="flex-[999_1_330px] min-w-0">
            <p className="m-0 font-serif text-lg leading-[1.62] text-ink-600">{doc.preamble}</p>
          </div>
        </div>

        {doc.sections.map((section, i) => (
          <div key={section.title} className="flex flex-wrap items-start gap-8 py-5.5 px-0 border-t border-t-[rgba(42,39,31,0.08)]" style={{ ...enter(i + 1) }}>
            <div className="flex-[1_1_220px] max-w-full min-w-0">
              <h2 className="m-0 text-[14.5px] font-semibold leading-[1.45] tracking-[-0.01em] text-ink-800">{section.title}</h2>
            </div>
            <div className="flex-[999_1_330px] min-w-0">
              <SectionText section={section} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
