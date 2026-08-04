'use client';

import { useState } from 'react';
import Link from 'next/link';
import { CompanionBody, CompanionShell } from '@/components/companion/CompanionShell';
import { CloserNote, PageTitle, Prose } from '@/components/companion/primitives';
import { GALLERY_FILTERS, GALLERY_SHOTS } from '@/lib/landing/companionContent';

/**
 * Gallery — every screen in the product, filterable by area.
 *
 * The source fills each tile with its `image-slot` authoring component. There
 * are no screenshots in the import to fill them with, so each tile renders its
 * route and title over the paper surface instead: the grid, filters, copy and
 * routes are all real, and dropping images in later is a one-line change.
 */
export default function GalleryPage() {
  const [filter, setFilter] = useState<string>('all');
  const shots = GALLERY_SHOTS.filter((s) => filter === 'all' || s.cat === filter);

  return (
    <CompanionShell current="/gallery">
      <CompanionBody>
        <PageTitle>Gallery</PageTitle>
        <Prose delay={80}>
          Every screen in Sapling, as it actually looks. One course, one semester, and the same
          graph behind all of it.
        </Prose>

        <div style={{ marginTop: 36, display: 'flex', flexWrap: 'wrap', gap: 8, animation: 'fadeUp 700ms ease 140ms both' }}>
          {GALLERY_FILTERS.map((f) => {
            const on = f.key === filter;
            return (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                aria-pressed={on}
                style={{
                  padding: '8px 16px', borderRadius: 99, cursor: 'pointer',
                  fontFamily: "'DM Sans',system-ui,sans-serif", fontSize: 13, fontWeight: 500,
                  border: `1px solid ${on ? '#1B6C42' : 'rgba(42,39,31,0.16)'}`,
                  background: on ? '#1B6C42' : 'transparent',
                  color: on ? '#faf8f3' : '#6f6857',
                  transition: 'all 220ms',
                }}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        <div style={{ marginTop: 40, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 24 }}>
          {shots.map((s, i) => (
            <Link
              key={s.slot}
              href={s.route}
              className="cp-shot"
              style={{ display: 'flex', flexDirection: 'column', color: 'inherit', animation: 'fadeUp 700ms ease both', animationDelay: `${80 + i * 40}ms` }}
            >
              <div
                style={{
                  position: 'relative', width: '100%', aspectRatio: '16 / 10',
                  borderRadius: 12, overflow: 'hidden', background: '#faf8f3',
                  border: '1px solid rgba(42,39,31,0.12)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '0.16em', color: '#9a9689' }}>
                  {s.route}
                </span>
              </div>
              <p style={{ margin: '14px 0 0', fontSize: 11, fontWeight: 500, letterSpacing: '0.14em', textTransform: 'uppercase', fontFamily: "'JetBrains Mono',monospace", color: '#2D8F5C' }}>
                {s.group}
              </p>
              <p style={{ margin: '6px 0 0', fontSize: 16, fontWeight: 600, color: '#1a1814' }}>{s.title}</p>
              <p style={{ margin: '6px 0 0', fontFamily: "'Spectral',Georgia,serif", fontSize: 14, lineHeight: 1.6, color: '#3f3b31' }}>
                {s.body}
              </p>
            </Link>
          ))}
        </div>

        <CloserNote>
          Every screen here is playable on the <Link href="/" style={{ color: '#1B6C42' }}>home page</Link>. Open any tool in
          the toolkit and it runs a real scenario.
        </CloserNote>
      </CompanionBody>
    </CompanionShell>
  );
}
