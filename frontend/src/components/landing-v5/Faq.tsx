'use client';

/**
 * FAQ — a sticky question on the left, an accordion on the right.
 *
 * Ported from `Sapling Landing v5.dc.html`. The answer panels animate on
 * `max-height` rather than `height:auto`, which is what the source does and
 * why every answer shares one 300px ceiling: it keeps the transition
 * interruptible without measuring.
 */

import { FAQS } from '@/lib/landing/content';
import { DragField } from './DragField';

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.25, s: { left: '7.4%', top: '8.0%', width: 6.1, height: 6.1, background: '#2E7D52', opacity: 0.39, animation: 'nodeFloatB 13s ease-in-out -4s infinite' } },
  { d: 0.45, s: { right: '9.3%', top: '45.1%', width: 9.2, height: 9.2, background: '#6FBF8F', opacity: 0.46, boxShadow: '0 0 22px #6FBF8F66', animation: 'nodeFloatA 17s ease-in-out -9s infinite' } },
  { d: 0.34, s: { right: '2.8%', top: '11.1%', width: 7.9, height: 7.9, background: '#2E7D52', opacity: 0.47, boxShadow: '0 0 19px #2E7D5266', animation: 'nodeFloatB 15s ease-in-out -6s infinite' } },
  { d: 0.41, s: { right: '15.4%', top: '43.2%', width: 6.1, height: 6.1, background: '#8FD9A8', opacity: 0.59, animation: 'nodeFloatA 12s ease-in-out -2s infinite' } },
  { d: 0.34, s: { right: '11.7%', top: '45.7%', width: 5, height: 5, background: '#0E9E5A', opacity: 0.49, animation: 'nodeFloatB 14s ease-in-out -8s infinite' } },
  { d: 0.14, s: { right: '5.2%', top: '65.9%', width: 10.2, height: 10.2, background: '#2E7D52', opacity: 0.35, boxShadow: '0 0 24px #2E7D5266', animation: 'nodeFloatA 19s ease-in-out -11s infinite' } },
  { d: 0.23, s: { left: '3.0%', top: '88.1%', width: 7.2, height: 7.2, background: '#4FA574', opacity: 0.54, animation: 'nodeFloatA 16s ease-in-out -13s infinite' } },
  { d: 0.23, s: { right: '8.7%', top: '82.6%', width: 9, height: 9, background: '#6FBF8F', opacity: 0.59, boxShadow: '0 0 22px #6FBF8F66', animation: 'nodeFloatB 18s ease-in-out -5s infinite' } },
  { d: 0.44, s: { right: '6.2%', top: '33.6%', width: 7.9, height: 7.9, background: '#0E9E5A', opacity: 0.52, boxShadow: '0 0 19px #0E9E5A66', animation: 'nodeFloatA 14s ease-in-out -10s infinite' } },
  { d: 0.25, s: { left: '12.5%', top: '94.9%', width: 5.8, height: 5.8, background: '#4FA574', opacity: 0.42, animation: 'nodeFloatA 11s ease-in-out -3s infinite' } },
  { d: 0.23, s: { left: '11.1%', top: '77.0%', width: 5.9, height: 5.9, background: '#8FD9A8', opacity: 0.46, animation: 'nodeFloatA 15s ease-in-out -7s infinite' } },
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
      style={{
        position: 'relative', padding: '120px 24px', zIndex: 1,
        background: 'linear-gradient(180deg, rgba(230,242,232,0) 0%, rgba(230,242,232,0.55) 18%, rgba(230,242,232,0.55) 82%, rgba(230,242,232,0) 100%)',
      }}
    >
      <DragField section="faq" />

      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 0 }}>
        {MOTES.map((m, i) => (
          <span key={i} data-depth={m.d} style={{ position: 'absolute', borderRadius: 99, ...m.s }} />
        ))}
      </div>

      <div style={{ maxWidth: 1150, margin: '0 auto', display: 'grid', gridTemplateColumns: '4fr 7fr', gap: 72, alignItems: 'start' }}>
        <div data-reveal="1" style={{ position: 'sticky', top: 110 }}>
          <span style={{ ...MONO, fontSize: 11, letterSpacing: '0.32em', color: '#0C5638', textTransform: 'uppercase', fontWeight: 500 }}>
            Honest answers
          </span>
          <h2 style={{ margin: '20px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 'clamp(2.2rem, 4vw, 3.4rem)', fontWeight: 600, lineHeight: 1.06, letterSpacing: '-0.02em', color: '#12201A' }}>
            &ldquo;Isn&rsquo;t AI just going to do it <em style={{ color: '#12201A' }}>for</em> me?&rdquo;
          </h2>
          <p style={{ margin: '20px 0 0', color: '#33443B', fontSize: 15, lineHeight: 1.75, maxWidth: '38ch' }}>
            Fair question, and the one we get most. Sapling exists because we think AI should
            deepen understanding, not replace it. Here&rsquo;s where we stand.
          </p>
          <div style={{ marginTop: 28, display: 'flex', alignItems: 'center' }}>
            <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.3em', color: '#61726A', textTransform: 'uppercase' }}>
              Still curious?{' '}
              <a href="#faq" style={{ color: '#0C5638', textDecoration: 'underline' }}>Read the full FAQ</a>
            </span>
          </div>
        </div>

        <div data-reveal="1" style={{ borderTop: '1px solid rgba(18,32,26,0.12)' }}>
          {FAQS.map((q, i) => {
            const open = openFaq === i;
            return (
              <div key={q.q} style={{ borderBottom: '1px solid rgba(18,32,26,0.12)' }}>
                <button
                  onClick={() => onToggle(open ? -1 : i)}
                  aria-expanded={open}
                  style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', padding: '22px 4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, textAlign: 'left' }}
                >
                  <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 19, fontWeight: 600, letterSpacing: '-0.01em', color: open ? '#0C5638' : '#12201A', transition: 'color 300ms' }}>
                    {q.q}
                  </span>
                  <span
                    style={{
                      flexShrink: 0, width: 28, height: 28, borderRadius: 99,
                      border: '1px solid rgba(18,32,26,0.18)', display: 'flex',
                      alignItems: 'center', justifyContent: 'center',
                      background: open ? '#E6F2E8' : 'transparent',
                      // the plus rotates into a cross rather than swapping glyphs
                      transform: open ? 'rotate(45deg)' : 'rotate(0deg)',
                      transition: 'transform 300ms cubic-bezier(0.22,1,0.36,1), background 300ms',
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#0C5638" strokeWidth="2" strokeLinecap="round">
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
                  <p style={{ margin: 0, padding: '0 44px 24px 4px', color: '#33443B', fontSize: 14.5, lineHeight: 1.8 }}>
                    {q.a}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
