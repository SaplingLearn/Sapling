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

const MONO = "'JetBrains Mono',monospace";
const SERIF = "'Spectral',Georgia,serif";
const DISPLAY = "'Playfair Display',Georgia,serif";

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
      <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: 880, margin: '0 auto', padding: '64px 32px', boxSizing: 'border-box' }}>
        <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857', animation: 'fadeUp 600ms ease both' }}>
          Straight answers
        </span>
        <h1 style={{ margin: '14px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', animation: 'fadeUp 700ms ease 60ms both' }}>
          Questions we get
        </h1>
        <p style={{ margin: '24px 0 0', fontFamily: SERIF, fontSize: 16, lineHeight: 1.6, color: '#3f3b31', maxWidth: '62ch', animation: 'fadeUp 700ms ease 140ms both' }}>
          The honest version, including the ones that are uncomfortable for us. If your question is
          not here, it is worth asking us directly.
        </p>

        <div style={{ marginTop: 44, display: 'flex', flexDirection: 'column', gap: 34 }}>
          {INDEXED.map((g) => (
            <section key={g.label}>
              <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C', marginBottom: 6 }}>
                {g.label}
              </span>
              {g.items.map((item) => {
                const isOpen = open === item.i;
                const panelId = `faq-panel-${item.i}`;
                return (
                  <div key={item.q} style={{ borderBottom: '1px solid rgba(42,39,31,0.10)' }}>
                    <button
                      data-faq={item.i}
                      aria-controls={panelId}
                      onClick={() => setOpen(isOpen ? -1 : item.i)}
                      aria-expanded={isOpen}
                      type="button"
                      style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', padding: '20px 0', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 22 }}
                    >
                      <span style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.45, color: '#1a1814', letterSpacing: '-0.01em' }}>{item.q}</span>
                      <span
                        style={{
                          flex: '0 0 auto', width: 22, height: 22, marginTop: 1, borderRadius: 99,
                          border: `1px solid ${isOpen ? '#1B6C42' : 'rgba(42,39,31,0.16)'}`,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          // the plus rotates into a cross and fills in when open
                          transform: isOpen ? 'rotate(45deg)' : 'rotate(0deg)',
                          background: isOpen ? '#1B6C42' : 'transparent',
                          color: isOpen ? '#faf8f3' : '#6f6857',
                          transition: 'all 260ms cubic-bezier(0.22,1,0.36,1)',
                        }}
                      >
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                          <path d="M12 5v14M5 12h14" />
                        </svg>
                      </span>
                    </button>
                    {/* `visibility` is what takes the collapsed answer out of the
                        tab order: max-height 0 + overflow hidden still leaves the
                        text focusable and readable to a screen reader, so every
                        collapsed answer was announced as if it were open. It is
                        listed in the transition so it flips only after the
                        collapse finishes and doesn't cut the animation short. */}
                    <div
                      id={panelId}
                      style={{
                        overflow: 'hidden',
                        transition: 'max-height 380ms cubic-bezier(0.22,1,0.36,1), opacity 300ms ease, visibility 380ms',
                        maxHeight: isOpen ? 420 : 0,
                        opacity: isOpen ? 1 : 0,
                        visibility: isOpen ? 'visible' : 'hidden',
                      }}
                    >
                      <p style={{ margin: '0 0 20px', paddingRight: 44, fontFamily: SERIF, fontSize: 15.5, lineHeight: 1.7, color: '#3f3b31' }}>
                        {item.a}
                      </p>
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </div>

        <div style={{ marginTop: 52, borderRadius: 18, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)', padding: 'clamp(26px,4vw,40px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ maxWidth: '44ch' }}>
            <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C' }}>
              Still curious
            </span>
            <p style={{ margin: '10px 0 0', fontFamily: SERIF, fontSize: 15.5, lineHeight: 1.65, color: '#3f3b31' }}>
              Definitions for the terms above live in the Wiki. Everything else, ask us in the beta
              and one of the four of us will answer.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <Link href="/wiki" style={{ border: '1px solid rgba(42,39,31,0.16)', borderRadius: 8, padding: '13px 20px', fontSize: 14.5, fontWeight: 600, color: '#1a1814', background: '#faf8f3', whiteSpace: 'nowrap' }}>
              Read the Wiki
            </Link>
            <Link href="/#newsletter" className="cp-cta" style={{ background: '#1B6C42', color: '#fff', borderRadius: 8, padding: '13px 22px', fontSize: 14.5, fontWeight: 600, whiteSpace: 'nowrap' }}>
              Join the beta
            </Link>
          </div>
        </div>
      </div>
    </CompanionShell>
  );
}
