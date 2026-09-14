'use client';

/**
 * Feature lab · spaced repetition.
 *
 * Ported from the `isCards` branch of `FeatureLab.dc.html`. Click the card
 * (or press space) to flip it, then rate 1/2/3 and the interval follows:
 * 10 minutes, 1 day, 4 days.
 *
 * The keyboard shortcuts are part of the demo, not an accessibility
 * afterthought — the real review surface is driven the same way, and the hint
 * line says so.
 */

import { useCallback, useEffect, useState } from 'react';
import { LAB_TIER, MONO } from './LabShell';
import { DECK, RATE_DUE, RATE_LABEL, RATE_TONE } from './labData';

type RateKey = '1' | '2' | '3';
const RATES: RateKey[] = ['1', '2', '3'];

export function CardsDemo() {
  const [idx, setIdx] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [log, setLog] = useState<{ q: string; key: RateKey }[]>([]);

  const done = idx >= DECK.length;
  const card = DECK[Math.min(idx, DECK.length - 1)];

  // Plain reads from the render closure, with the key listener re-bound on
  // the values it depends on. Deciding inside a state updater (and firing a
  // timeout from one) double-runs under StrictMode and drops the advance.
  const flip = useCallback(() => {
    if (idx < DECK.length) setFlipped((f) => !f);
  }, [idx]);

  const rate = useCallback((key: RateKey) => {
    if (idx >= DECK.length || !flipped) return;
    setLog((l) => [...l, { q: DECK[idx].q, key }]);
    setFlipped(false);
    // the card turns back before the next one arrives, so it reads as a deal
    const t = setTimeout(() => setIdx((i) => i + 1), 300);
    return () => clearTimeout(t);
  }, [idx, flipped]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === ' ') { e.preventDefault(); flip(); }
      else if (RATES.includes(e.key as RateKey)) rate(e.key as RateKey);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [flip, rate]);

  return (
    <div style={{ padding: '18px 26px 20px', display: 'flex', flexDirection: 'column', gap: 12, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span style={{ width: 8, height: 8, borderRadius: 99, background: LAB_TIER.struggling }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: '#12201A' }}>Eigenvalues</span>
          <span style={{ padding: '3px 8px', borderRadius: 6, background: '#F6F8F4', border: '1px solid #E3EBE5', ...MONO, fontSize: 9, letterSpacing: '0.1em', color: '#61726A' }}>MA 242</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.12em', color: '#8B9891' }}>
            DUE TODAY · {DECK.length - Math.min(idx, DECK.length)} LEFT
          </span>
          <span style={{ fontSize: 12.5, color: '#61726A' }}>
            Card {done ? DECK.length : idx + 1} of {DECK.length}
          </span>
        </div>
      </div>

      <span style={{ flex: '0 0 auto', height: 5, borderRadius: 99, background: '#E3EBE5', overflow: 'hidden' }}>
        <span style={{ display: 'block', height: '100%', borderRadius: 99, background: '#0E9E5A', transition: 'width 400ms cubic-bezier(0.22,1,0.36,1)', width: `${Math.round((Math.min(idx, DECK.length) / DECK.length) * 100)}%` }} />
      </span>

      {done ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14, animation: 'labIn 320ms ease both' }}>
          <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 30, fontWeight: 600 }}>Deck complete</span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: 'min(340px,100%)' }}>
            {log.map((l, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 13px', borderRadius: 9, background: '#F6F8F4', border: '1px solid #E3EBE5' }}>
                <span style={{ fontSize: 12.5, color: '#33443B', maxWidth: '60%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.q}</span>
                <span style={{ ...MONO, fontSize: 10.5, color: RATE_TONE[l.key] }}>
                  {RATE_LABEL[l.key].toUpperCase()} · {RATE_DUE[l.key]}
                </span>
              </div>
            ))}
          </div>
          <button
            onClick={() => { setIdx(0); setFlipped(false); setLog([]); }}
            type="button"
            style={{ marginTop: 4, padding: '10px 22px', borderRadius: 10, border: 'none', background: '#0C5638', color: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          >
            Study again
          </button>
        </div>
      ) : (
        <>
          <div onClick={flip} style={{ position: 'relative', flex: '1 1 auto', minHeight: 200, cursor: 'pointer' }}>
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', perspective: 1600 }}>
              <div style={{ position: 'relative', width: '100%', maxWidth: 600, aspectRatio: '16 / 9', maxHeight: '100%', transformStyle: 'preserve-3d', transition: 'transform 560ms cubic-bezier(0.4,0,0.2,1)', transform: `rotateY(${flipped ? 180 : 0}deg)` }}>
                <div style={{ position: 'absolute', inset: 0, backfaceVisibility: 'hidden', borderRadius: 18, background: '#FDFCF9', border: '1px solid #E3E0D5', boxShadow: '0 18px 40px -18px rgba(18,32,26,0.28)', padding: '30px 34px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', gap: 14 }}>
                  <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.26em', color: '#9AA5A0' }}>FRONT</span>
                  <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 'clamp(20px,2.3vw,27px)', fontWeight: 600, lineHeight: 1.3, color: '#12201A' }}>{card.q}</span>
                  <span style={{ position: 'absolute', bottom: 16, left: 0, right: 0, fontSize: 11.5, color: '#B4BEB8' }}>click to reveal</span>
                </div>
                <div style={{ position: 'absolute', inset: 0, backfaceVisibility: 'hidden', transform: 'rotateY(180deg)', borderRadius: 18, background: '#0C5638', border: '1px solid #0C5638', boxShadow: '0 18px 40px -18px rgba(12,86,56,0.5)', padding: '30px 34px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', gap: 14 }}>
                  <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.26em', color: '#8FD9A8' }}>BACK</span>
                  <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 'clamp(18px,2.1vw,24px)', fontWeight: 500, lineHeight: 1.4, color: '#F6F8F4' }}>{card.a}</span>
                  <span style={{ position: 'absolute', bottom: 16, left: 0, right: 0, ...MONO, fontSize: 9, letterSpacing: '0.14em', color: 'rgba(230,242,232,0.5)' }}>HOW DID THAT GO?</span>
                </div>
              </div>
            </div>
          </div>

          <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: 10, width: '100%', maxWidth: 560, transition: 'opacity 250ms', opacity: flipped ? 1 : 0.35, pointerEvents: flipped ? 'auto' : 'none' }}>
              {RATES.map((k) => (
                <button
                  key={k}
                  onClick={() => rate(k)}
                  type="button"
                  className="ld-labrate"
                  style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, padding: '11px 0', borderRadius: 11, fontFamily: "'DM Sans',sans-serif", cursor: 'pointer', transition: 'all 180ms', border: `1px solid ${RATE_TONE[k]}66`, background: `${RATE_TONE[k]}12` }}
                >
                  <span style={{ fontSize: 13.5, fontWeight: 600, color: RATE_TONE[k] }}>
                    {RATE_LABEL[k]} <b style={{ ...MONO, fontSize: 10, color: '#9AA5A0', fontWeight: 400 }}>{k}</b>
                  </span>
                  <span style={{ ...MONO, fontSize: 10, color: `${RATE_TONE[k]}cc` }}>next in {RATE_DUE[k]}</span>
                </button>
              ))}
            </div>
            <span style={{ fontSize: 11.5, color: '#9AA5A0' }}>
              {flipped ? 'Rate it: 1 Forgot, 2 Hard, 3 Easy' : 'Click the card or press space to reveal'}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
