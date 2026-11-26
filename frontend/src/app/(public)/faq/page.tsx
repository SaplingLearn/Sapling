'use client';

/**
 * FAQ.
 *
 * Ported from `FAQ.dc.html`. Three labelled groups of questions over a
 * two-button call-out.
 *
 * Distinct from the landing page's FAQ section, which is one flat list. Only
 * one question is open at a time and the index spans all three groups, so the
 * counter is resolved up front — the source increments it inside its render
 * loop, which in React mutates during render.
 */

import { useState } from 'react';
import Link from 'next/link';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { FAQ_GROUPS } from '@/lib/landing/companionContent';
import { cn } from "@/lib/cn";

/** Groups paired with a running index across ALL groups, computed once. */
const INDEXED = (() => {
  let n = -1;
  return FAQ_GROUPS.map((g) => ({
    label: g.label,
    items: g.items.map((item) => ({ ...item, i: (n += 1) })),
  }));
})();

export default function FaqPage() {
  const [open, setOpen] = useState(0);

  return (
    <CompanionShell current="/faq">
      <div>
        <span className="block font-sans text-sm text-text-muted [animation:fadeUp_600ms_ease_both]">
          Straight answers
        </span>
        <h1 className="mt-3.5 mx-0 mb-0 font-display font-medium text-[48px] leading-[1.15] tracking-[-0.015em] [animation:fadeUp_700ms_ease_60ms_both]">
          Questions we get
        </h1>
        <p className="mt-6 mx-0 mb-0 font-serif text-lg leading-[1.6] text-ink-600 max-w-[62ch] [animation:fadeUp_700ms_ease_140ms_both]">
          The honest version, including the ones that are uncomfortable for us. If your question is
          not here, it is worth asking us directly.
        </p>

        <div className="mt-11 flex flex-col gap-8.5">
          {INDEXED.map((g) => (
            <section key={g.label}>
              <span className="block font-sans text-sm text-brand-forest-bright mb-1.5">
                {g.label}
              </span>
              {g.items.map((item) => {
                const isOpen = open === item.i;
                return (
                  <div key={item.q} className="border-b border-b-[rgba(42,39,31,0.10)]">
                    <button
                      data-faq={item.i}
                      onClick={() => setOpen(isOpen ? -1 : item.i)}
                      aria-expanded={isOpen}
                      type="button"
                      className="w-full text-left [background:none] border-0 cursor-pointer py-5 px-0 flex items-start justify-between gap-5.5"
                    >
                      <span className="text-lg font-semibold leading-[1.45] text-ink-800 tracking-[-0.01em]">{item.q}</span>
                      <span
                        className={cn(cn("flex-[0_0_auto] w-5.5 h-5.5 mt-px rounded-[99px] flex items-center justify-center [transition:all_260ms_cubic-bezier(0.22,1,0.36,1)]", isOpen ? "[transform:rotate(45deg)]" : "[transform:rotate(0deg)]", isOpen ? "bg-brand-forest" : "bg-transparent", isOpen ? "text-ink-0" : "text-text-muted"), isOpen ? "border border-brand-forest" : "border border-[rgba(42,39,31,0.16)]")}
                      >
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                          <path d="M12 5v14M5 12h14" />
                        </svg>
                      </span>
                    </button>
                    <div className={cn("overflow-hidden [transition:max-height_380ms_cubic-bezier(0.22,1,0.36,1),_opacity_300ms_ease]", isOpen ? "max-h-105" : "max-h-0", isOpen ? "opacity-100" : "opacity-0")}>
                      <p className="mt-0 mx-0 mb-5 pr-11 font-serif text-[15.5px] leading-[1.7] text-ink-600 max-w-[80ch]">
                        {item.a}
                      </p>
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </div>

        <div className="mt-13 rounded-[18px] bg-ink-0 border border-[rgba(42,39,31,0.10)] p-[clamp(26px,4vw,40px)] flex items-center justify-between gap-6 flex-wrap">
          <div className="max-w-[44ch]">
            <span className="block font-sans text-sm text-brand-forest-bright">
              Still curious
            </span>
            <p className="mt-2.5 mx-0 mb-0 font-serif text-[15.5px] leading-[1.65] text-ink-600">
              Definitions for the terms above live in the Wiki. Everything else, ask us in the beta
              and one of the four of us will answer.
            </p>
          </div>
          <div className="flex gap-3 flex-wrap">
            <Link href="/wiki" className="border border-[rgba(42,39,31,0.16)] rounded-[8px] py-[13px] px-5 text-[14.5px] font-semibold text-ink-800 bg-ink-0 whitespace-nowrap">
              Read the Wiki
            </Link>
            <Link href="/#newsletter" className="cp-cta [background:var(--brand-forest)] text-accent-fg rounded-[8px] py-[13px] px-5.5 text-[14.5px] font-semibold whitespace-nowrap">
              Join the beta
            </Link>
          </div>
        </div>
      </div>
    </CompanionShell>
  );
}
