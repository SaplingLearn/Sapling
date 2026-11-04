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

const MONO: React.CSSProperties = { fontFamily: "var(--font-plex-mono), 'IBM Plex Mono', ui-monospace, monospace" };

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
      className="ld-faq"
      style={{
        position: 'relative', padding: '120px 24px', zIndex: 1,
        background: 'linear-gradient(180deg, rgba(234,241,228,0) 0%, rgba(234,241,228,0.55) 18%, rgba(234,241,228,0.55) 82%, rgba(234,241,228,0) 100%)',
      }}
    >
      <DragField section="faq" />

      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 0 }}>
        {MOTES.map((m, i) => (
          <span key={i} data-depth={m.d} style={{ position: 'absolute', borderRadius: 99, ...m.s }} />
        ))}
      </div>

      <div className="ld-faq-grid" style={{ maxWidth: 1150, margin: '0 auto', display: 'grid', gridTemplateColumns: '4fr 7fr', gap: 72, alignItems: 'start' }}>
        {/*
          Sticky, so it holds while the accordion scrolls past — and named,
          because `DragField`'s `TRACKS` welds CS 112 and PH 150 to this
          column. If it stops being sticky, drop the entry there too.
        */}
        <FadeIn data-drag-anchor="faq" className="ld-faq-intro" style={{ position: 'sticky', top: 110 }}>
          <h2 style={{ margin: 0, fontFamily: "var(--font-aleo), 'Aleo', Georgia, serif", fontSize: 'clamp(2.2rem, 4vw, 3.4rem)', fontWeight: 600, lineHeight: 1.06, letterSpacing: '-0.02em', color: '#191F13' }}>
            Honest answers about <em style={{ color: '#445D22' }}>AI.</em>
          </h2>
          <p style={{ margin: '20px 0 0', color: '#3B4233', fontSize: 15, lineHeight: 1.75, maxWidth: '38ch' }}>
            The question we hear most: isn&rsquo;t AI just going to do the work for me? Sapling
            exists because we think AI should deepen your understanding, not replace it. Here&rsquo;s
            where we stand.
          </p>
          <div style={{ marginTop: 28, display: 'flex', alignItems: 'center' }}>
            <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.3em', color: '#697062', textTransform: 'uppercase' }}>
              Still curious?{' '}
              <Link href="/faq" style={{ color: '#445D22', textDecoration: 'underline' }}>Read the full FAQ</Link>
            </span>
          </div>
        </FadeIn>

        <FadeIn style={{ borderTop: '1px solid rgba(25,31,19,0.12)' }}>
          {FAQS.map((q, i) => {
            const open = openFaq === i;
            return (
              <div key={q.q} style={{ borderBottom: '1px solid rgba(25,31,19,0.12)' }}>
                <button
                  onClick={() => onToggle(open ? -1 : i)}
                  aria-expanded={open}
                  style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', padding: '22px 4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, textAlign: 'left' }}
                >
                  <span style={{ fontFamily: "var(--font-aleo), 'Aleo', Georgia, serif", fontSize: 19, fontWeight: 600, letterSpacing: '-0.01em', color: open ? '#445D22' : '#191F13', transition: 'color 300ms' }}>
                    {q.q}
                  </span>
                  <span
                    style={{
                      flexShrink: 0, width: 28, height: 28, borderRadius: 99,
                      border: '1px solid rgba(25,31,19,0.18)', display: 'flex',
                      alignItems: 'center', justifyContent: 'center',
                      background: open ? '#EAF1E4' : 'transparent',
                      // the plus rotates into a cross rather than swapping glyphs
                      transform: open ? 'rotate(45deg)' : 'rotate(0deg)',
                      transition: 'transform 300ms cubic-bezier(0.22,1,0.36,1), background 300ms',
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#445D22" strokeWidth="2" strokeLinecap="round">
                      <path d="M12 5v14M5 12h14" />
                    </svg>
                  </span>
                </button>
                <div
                  style={{
                    // a shared ceiling, not a measured height — keeps the
                    // transition interruptible without a layout read
                    maxHeight: open ? 300 : 0,
                    opacity: open ? 1 : 0,
                    overflow: 'hidden',
                    transition: 'max-height 450ms cubic-bezier(0.22,1,0.36,1), opacity 350ms ease',
                  }}
                >
                  <p className="ld-faq-a" style={{ margin: 0, padding: '0 44px 24px 4px', color: '#3B4233', fontSize: 14.5, lineHeight: 1.8 }}>
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
