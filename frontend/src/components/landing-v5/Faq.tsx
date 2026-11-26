'use client';

/**
 * FAQ — a sticky title on the left, an accordion on the right.
 *
 * Ported from `Sapling Landing v5.dc.html`. The answer panels animate on
 * `max-height` rather than `height:auto`, which is what the source does and
 * why every answer shares one 300px ceiling: it keeps the transition
 * interruptible without measuring.
 */

import Link from 'next/link';
import { FAQS } from '@/lib/landing/content';
import { DragField } from './DragField';
import { FadeIn } from '@/components/landing/anim';
import { cn } from "@/lib/cn";

const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.25, s: { left: '7.4%', top: '8.0%', width: 6.1, height: 6.1, background: '#597731', opacity: 0.39, animation: 'nodeFloatB 13s ease-in-out -4s infinite' } },
  { d: 0.45, s: { right: '9.3%', top: '45.1%', width: 9.2, height: 9.2, background: '#96B86F', opacity: 0.46, boxShadow: '0 0 22px #96B86F66', animation: 'nodeFloatA 17s ease-in-out -9s infinite' } },
  { d: 0.34, s: { right: '2.8%', top: '11.1%', width: 7.9, height: 7.9, background: '#597731', opacity: 0.47, boxShadow: '0 0 19px #59773166', animation: 'nodeFloatB 15s ease-in-out -6s infinite' } },
  { d: 0.41, s: { right: '15.4%', top: '43.2%', width: 6.1, height: 6.1, background: '#B1D28B', opacity: 0.59, animation: 'nodeFloatA 12s ease-in-out -2s infinite' } },
  { d: 0.34, s: { right: '11.7%', top: '45.7%', width: 5, height: 5, background: '#68951F', opacity: 0.49, animation: 'nodeFloatB 14s ease-in-out -8s infinite' } },
  { d: 0.14, s: { right: '5.2%', top: '65.9%', width: 10.2, height: 10.2, background: '#597731', opacity: 0.35, boxShadow: '0 0 24px #59773166', animation: 'nodeFloatA 19s ease-in-out -11s infinite' } },
  { d: 0.23, s: { left: '3.0%', top: '88.1%', width: 7.2, height: 7.2, background: '#7B9E51', opacity: 0.54, animation: 'nodeFloatA 16s ease-in-out -13s infinite' } },
  { d: 0.23, s: { right: '8.7%', top: '82.6%', width: 9, height: 9, background: '#96B86F', opacity: 0.59, boxShadow: '0 0 22px #96B86F66', animation: 'nodeFloatB 18s ease-in-out -5s infinite' } },
  { d: 0.44, s: { right: '6.2%', top: '33.6%', width: 7.9, height: 7.9, background: '#68951F', opacity: 0.52, boxShadow: '0 0 19px #68951F66', animation: 'nodeFloatA 14s ease-in-out -10s infinite' } },
  { d: 0.25, s: { left: '12.5%', top: '94.9%', width: 5.8, height: 5.8, background: '#7B9E51', opacity: 0.42, animation: 'nodeFloatA 11s ease-in-out -3s infinite' } },
  { d: 0.23, s: { left: '11.1%', top: '77.0%', width: 5.9, height: 5.9, background: '#B1D28B', opacity: 0.46, animation: 'nodeFloatA 15s ease-in-out -7s infinite' } },
];

export function Faq({
  openFaq,
  onToggle,
}: {
  openFaq: number;
  onToggle: (i: number) => void;
}) {
  return (
    <section
      id="faq"
      className="ld-faq relative py-30 px-6 z-1 [background:linear-gradient(180deg,_rgba(234,241,228,0)_0%,_rgba(234,241,228,0.55)_18%,_rgba(234,241,228,0.55)_82%,_rgba(234,241,228,0)_100%)]"
    >
      <DragField section="faq" />

      <div aria-hidden="true" className="absolute inset-0 pointer-events-none overflow-hidden z-0">
        {MOTES.map((m, i) => (
          <span key={i} data-depth={m.d} className="absolute rounded-[99px]" style={{ ...m.s }} />
        ))}
      </div>

      <div className="ld-faq-grid max-w-287.5 my-0 mx-auto grid grid-cols-[4fr_7fr] gap-18 [align-items:start]">
        {/*
          Sticky, so it holds while the accordion scrolls past — and named,
          because `DragField`'s `Tracks` welds CS 112 and PH 150 to this
          column. If it stops being sticky, drop the entry there too.
        */}
        <FadeIn data-drag-anchor="faq" className="ld-faq-intro" style={{ position: 'sticky', top: 110 }}>
          <h2 className="m-0 font-display text-[length:clamp(2.2rem,_4vw,_3.4rem)] font-semibold leading-[1.06] tracking-[-0.02em] text-moss-900">
            Honest answers about <em className="text-brand-forest">AI.</em>
          </h2>
          <p className="mt-5 mx-0 mb-0 text-moss-700 text-[15px] leading-[1.75] max-w-[38ch]">
            The question we hear most: isn&rsquo;t AI just going to do the work for me? Sapling
            exists because we think AI should deepen your understanding, not replace it. Here&rsquo;s
            where we stand.
          </p>
          <div className="mt-7 flex items-center">
            <span className="font-sans text-sm text-moss-500">
              Still curious?{' '}
              <Link href="/faq" className="text-brand-forest underline">Read the full FAQ</Link>
            </span>
          </div>
        </FadeIn>

        <FadeIn style={{ borderTop: '1px solid rgba(25,31,19,0.12)' }}>
          {FAQS.map((q, i) => {
            const open = openFaq === i;
            return (
              <div key={q.q} className="border-b border-b-[rgba(25,31,19,0.12)]">
                <button
                  onClick={() => onToggle(open ? -1 : i)}
                  aria-expanded={open}
                  className="w-full [background:none] border-0 cursor-pointer py-5.5 px-1 flex items-center justify-between gap-5 text-left"
                >
                  <span className={cn("font-display text-[19px] font-semibold tracking-[-0.01em] [transition:color_300ms]", open ? "text-brand-forest" : "text-moss-900")}>
                    {q.q}
                  </span>
                  <span
                    className={cn("shrink-0 w-7 h-7 rounded-[99px] border border-[rgba(25,31,19,0.18)] flex items-center justify-center [transition:transform_300ms_cubic-bezier(0.22,1,0.36,1),_background_300ms]", open ? "bg-leaf-50" : "bg-transparent", open ? "[transform:rotate(45deg)]" : "[transform:rotate(0deg)]")}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#445D22" strokeWidth="2" strokeLinecap="round">
                      <path d="M12 5v14M5 12h14" />
                    </svg>
                  </span>
                </button>
                <div
                  className={cn("overflow-hidden [transition:max-height_450ms_cubic-bezier(0.22,1,0.36,1),_opacity_350ms_ease]", open ? "max-h-75" : "max-h-0", open ? "opacity-100" : "opacity-0")}
                >
                  <p className="ld-faq-a m-0 pt-0 pr-11 pb-6 pl-1 text-moss-700 text-[14.5px] leading-[1.8]">
                    {q.a}
                  </p>
                </div>
              </div>
            );
          })}
        </FadeIn>
      </div>
    </section>
  );
}
