'use client';

import { useState } from 'react';
import Link from 'next/link';
import { CompanionBody, CompanionShell } from '@/components/companion/CompanionShell';
import { CloserNote, Eyebrow, PageTitle, Prose } from '@/components/companion/primitives';
import { FAQ_GROUPS } from '@/lib/landing/companionContent';

/**
 * Groups paired with a running index across ALL groups, computed once.
 *
 * The standalone FAQ is grouped into three categories, unlike the landing
 * page's flat one, but only one item is open at a time — so the index has to
 * span groups. The source increments a counter inside its render loop; doing
 * that in React mutates during render, so it is resolved up front here.
 */
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
      <CompanionBody>
        <PageTitle>Questions we get</PageTitle>
        <Prose delay={80}>
          The honest version, including the ones that are uncomfortable for us. If your question is
          not here, it is worth asking us directly.
        </Prose>

        <div style={{ marginTop: 48, display: 'flex', flexDirection: 'column', gap: 40 }}>
          {INDEXED.map((g) => (
            <div key={g.label}>
              <Eyebrow>{g.label}</Eyebrow>
              <div style={{ borderTop: '1px solid rgba(42,39,31,0.10)' }}>
                {g.items.map((item) => {
                  const i = item.i;
                  const isOpen = open === i;
                  return (
                    <div key={item.q} style={{ borderBottom: '1px solid rgba(42,39,31,0.10)' }}>
                      <button
                        data-faq={i}
                        onClick={() => setOpen(isOpen ? -1 : i)}
                        aria-expanded={isOpen}
                        style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', padding: '18px 2px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, textAlign: 'left' }}
                      >
                        <span style={{ fontSize: 15, fontWeight: 600, color: isOpen ? '#1B6C42' : '#1a1814', transition: 'color 260ms' }}>
                          {item.q}
                        </span>
                        <span
                          style={{
                            flexShrink: 0, width: 26, height: 26, borderRadius: 99,
                            border: '1px solid rgba(42,39,31,0.18)', display: 'flex',
                            alignItems: 'center', justifyContent: 'center',
                            // the plus rotates into a cross and fills in when open
                            transform: isOpen ? 'rotate(45deg)' : 'rotate(0deg)',
                            background: isOpen ? '#1B6C42' : 'transparent',
                            borderColor: isOpen ? '#1B6C42' : 'rgba(42,39,31,0.18)',
                            color: isOpen ? '#faf8f3' : '#6f6857',
                            transition: 'all 260ms cubic-bezier(0.22,1,0.36,1)',
                          }}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                            <path d="M12 5v14M5 12h14" />
                          </svg>
                        </span>
                      </button>
                      <div style={{ maxHeight: isOpen ? 420 : 0, opacity: isOpen ? 1 : 0, overflow: 'hidden', transition: 'max-height 420ms cubic-bezier(0.22,1,0.36,1), opacity 320ms ease' }}>
                        <p style={{ margin: 0, padding: '0 40px 20px 2px', fontFamily: "'Spectral',Georgia,serif", fontSize: 15, lineHeight: 1.7, color: '#3f3b31' }}>
                          {item.a}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <CloserNote>
          Definitions for the terms above live in the <Link href="/wiki" style={{ color: '#1B6C42' }}>Wiki</Link>. Everything
          else, ask us in the beta and one of the four of us will answer.
        </CloserNote>
      </CompanionBody>
    </CompanionShell>
  );
}
