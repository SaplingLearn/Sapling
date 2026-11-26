'use client';

/**
 * Careers — the open-roles list.
 *
 * Moved onto CompanionShell, which owns the header, the footer and the
 * content box. The page used to ship its own 52px sticky bar carrying a lone
 * link home, plus a hand-rolled five-entry link row at the bottom that had
 * drifted from the shared one; both are gone. Palette converted from the
 * app-shell `var(--*)` tokens to the warm paper hexes, because inside the
 * shell those variables resolve against a different layer and fight the
 * paper ground.
 *
 * Rows run the full width of the shell box rather than sitting in the old
 * 760px column: a narrow list inside a wide frame is the "one right edge"
 * failure. The one genuinely long block — a role's description — gets a
 * two-column expansion so the prose lands near a 65-character measure with
 * the tags and the apply button beside it, instead of a 150-character line.
 */

import { useState } from 'react';
import Link from 'next/link';
import { JOBS, DEPT_COLORS } from './jobs';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { MUTED } from '@/lib/landing/companionType';
import { cn } from "@/lib/cn";

/**
 * Chip colours for a department `jobs.ts` has no entry for. The old fallback
 * read `DEPT_COLORS.Engineering`, a key that no longer exists in the map, so
 * the first job in a new department would have crashed on `dept.bg` rather
 * than degrading to a neutral chip.
 */
const DEPT_FALLBACK = { bg: 'rgba(42,39,31,0.05)', text: MUTED, border: 'rgba(42,39,31,0.14)' };

export default function CareersList() {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const hiring = JOBS.length > 0;

  return (
    <CompanionShell current="/careers">
      <div>
        {/* The dot is the live-role tell: forest green while something is
            open, neutral once nothing is. An accent dot over "not hiring"
            reads as a broken state rather than a deliberate one. */}
        <span className="inline-flex items-center gap-2 font-sans text-sm text-text-muted [animation:fadeUp_600ms_ease_both]">
          <span aria-hidden="true" className={cn("w-1.5 h-1.5 rounded-[99px]", hiring ? "bg-brand-forest-bright" : "bg-[rgba(42,39,31,0.28)]")} />
          {hiring ? "We're hiring" : 'Not hiring right now'}
        </span>
        <h1 className="mt-3.5 mx-0 mb-0 font-display font-medium text-[48px] leading-[1.15] tracking-[-0.015em] text-ink-800 [animation:fadeUp_700ms_ease_60ms_both]">
          Opportunities
        </h1>
        <p className="mt-6 mx-0 mb-0 font-serif text-lg leading-[1.6] text-ink-600 max-w-[62ch] [animation:fadeUp_700ms_ease_140ms_both]">
          We&apos;re a small team building tools that help students learn better. If that sounds like
          work worth doing, we&apos;d love to meet you.
        </p>

        {/* The list reads as a table across the whole box, so it gets a header
            row and hairline rules rather than floating cards. With nothing
            open, the same rule carries the empty state — a header reading
            "0 positions" above blank space is how a page looks broken. */}
        <div className="mt-12 pb-3 border-b border-b-[rgba(42,39,31,0.10)] flex items-baseline justify-between gap-4 [animation:fadeUp_700ms_ease_200ms_both]">
          <span className="block font-sans text-sm text-brand-forest-bright">{hiring ? 'Open roles' : 'Openings'}</span>
          {hiring ? (
            <span className="font-sans text-[12.5px] text-text-muted">
              {JOBS.length} {JOBS.length === 1 ? 'position' : 'positions'}
            </span>
          ) : null}
        </div>

        {!hiring ? (
          <p className="my-11 mx-auto font-serif text-[17px] leading-[1.65] text-ink-600 max-w-[52ch] text-center [animation:fadeUp_700ms_ease_260ms_both]">
            No opportunities at the moment. We post roles here as they open — and the note below
            reaches us either way.
          </p>
        ) : null}

        {JOBS.map((job, i) => {
          const dept = DEPT_COLORS[job.department] ?? DEPT_FALLBACK;
          const isOpen = expandedId === job.id;

          return (
            <div
              key={job.id}
              className="border-b border-b-[rgba(42,39,31,0.08)] [animation:fadeUp_700ms_ease_both]" style={{ animationDelay: `${260 + i * 60}ms` }}
            >
              <button
                onClick={() => setExpandedId(isOpen ? null : job.id)}
                aria-expanded={isOpen}
                type="button"
                className="w-full text-left [background:none] border-0 cursor-pointer py-6 px-0 flex items-center justify-between gap-6"
              >
                <span className="flex flex-col gap-2 min-w-0">
                  <span className="flex items-center flex-wrap gap-2.5">
                    <span className="text-[19px] font-semibold text-ink-800 tracking-[-0.015em]">
                      {job.title}
                    </span>
                    <span
                      className="text-xs font-medium py-[3px] px-2.5 rounded-[99px]" style={{ background: dept.bg, color: dept.text, border: `1px solid ${dept.border}` }}
                    >
                      {job.department}
                    </span>
                  </span>
                  <span className="font-sans text-[12.5px] text-text-muted">
                    {job.location} · {job.type}
                  </span>
                </span>

                {/* Same affordance as the /faq accordion: a hairline circle that
                    fills forest green once the row is open. */}
                <span
                  className={cn(cn("flex-[0_0_auto] w-6.5 h-6.5 rounded-[99px] flex items-center justify-center [transition:all_260ms_cubic-bezier(0.22,1,0.36,1)]", isOpen ? "bg-brand-forest" : "bg-transparent", isOpen ? "text-ink-0" : "text-text-muted", isOpen ? "[transform:rotate(180deg)]" : "[transform:rotate(0deg)]"), isOpen ? "border border-brand-forest" : "border border-[rgba(42,39,31,0.16)]")}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M19 9l-7 7-7-7" />
                  </svg>
                </span>
              </button>

              <div
                className={cn("overflow-hidden", isOpen ? "max-h-275" : "max-h-0", isOpen ? "opacity-100" : "opacity-0", isOpen ? "visible" : "invisible", isOpen ? "[transition:max-height_620ms_cubic-bezier(0.22,1,0.36,1),_opacity_400ms_ease]" : "[transition:max-height_620ms_cubic-bezier(0.22,1,0.36,1),_opacity_400ms_ease,_visibility_0s_linear_620ms]")}
              >
                <div
                  className="pb-8 grid grid-cols-[repeat(auto-fit,_minmax(min(100%,320px),1fr))] gap-11 [align-items:start]"
                >
                  <p className="m-0 font-serif text-[17px] leading-[1.62] text-ink-600">
                    {job.description}
                  </p>

                  <div>
                    <span className="block font-sans text-sm text-brand-forest-bright">What you&apos;d touch</span>
                    <div className="mt-3.5 flex flex-wrap gap-[7px]">
                      {job.tags.map((tag) => (
                        <span
                          key={tag}
                          className="text-sm py-1 px-[11px] rounded-[7px] bg-ink-0 border border-[rgba(42,39,31,0.10)] text-ink-600"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                    <Link
                      href={`/careers/${job.slug}`}
                      className="cp-cta mt-6 inline-flex items-center gap-[9px] [background:var(--brand-forest)] text-accent-fg rounded-[8px] py-[13px] px-5.5 text-[14.5px] font-semibold"
                    >
                      Apply for this role
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12h14M12 5l7 7-7 7" />
                      </svg>
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        <div className="mt-13 rounded-[18px] bg-ink-0 border border-[rgba(42,39,31,0.10)] p-[clamp(26px,4vw,40px)] flex items-center justify-between gap-6 flex-wrap">
          <div className="max-w-[46ch]">
            <span className="block font-sans text-sm text-brand-forest-bright">Don&apos;t see your role?</span>
            <p className="mt-2.5 mx-0 mb-0 font-serif text-[15.5px] leading-[1.65] text-ink-600">
              We&apos;re always interested in meeting talented people. Send us a note and tell us what
              you&apos;d build.
            </p>
          </div>
          <a
            href="mailto:careers@saplinglearn.com"
            className="cp-cta [background:var(--brand-forest)] text-accent-fg rounded-[8px] py-[13px] px-5.5 text-[14.5px] font-semibold whitespace-nowrap"
          >
            Get in touch
          </a>
        </div>
      </div>
    </CompanionShell>
  );
}
