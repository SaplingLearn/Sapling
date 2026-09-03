'use client';

/**
 * Gallery.
 *
 * Ported from `Gallery.dc.html`. A filterable grid of `<figure>` tiles, each
 * a 16/10 frame with its route badged over the top-left corner and a caption
 * pairing the screen's title with its group.
 *
 * Tiles stagger in: `animation-delay` steps 50ms per tile and caps at 400ms,
 * so a filter that returns twelve results still settles quickly.
 *
 * The frames are empty. The source fills them with its `image-slot` drop
 * zone ("Drop a screenshot of …"), which is an authoring affordance rather
 * than page content, and the import ships no screenshots. The route badge
 * stays, so each tile still says what it is.
 */

import { useState } from 'react';
import Link from 'next/link';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { GALLERY_FILTERS, GALLERY_SHOTS } from '@/lib/landing/companionContent';
import { DISPLAY, MONO, SERIF } from '@/lib/landing/companionType';

export default function GalleryPage() {
  const [filter, setFilter] = useState('all');
  const shots = GALLERY_SHOTS.filter((s) => filter === 'all' || s.cat === filter);

  return (
    <CompanionShell current="/gallery">
      <div>
        <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857', animation: 'fadeUp 600ms ease both' }}>
          Inside the product
        </span>
        <h1 style={{ margin: '14px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', animation: 'fadeUp 700ms ease 60ms both' }}>
          Gallery
        </h1>
        <p style={{ margin: '24px 0 0', fontFamily: SERIF, fontSize: 16, lineHeight: 1.6, color: '#3f3b31', maxWidth: '62ch', animation: 'fadeUp 700ms ease 140ms both' }}>
          Every screen in Sapling, as it actually looks. One course, one semester, and the same
          graph behind all of it.
        </p>

        <div style={{ marginTop: 34, display: 'flex', gap: 8, flexWrap: 'wrap', animation: 'fadeUp 700ms ease 200ms both' }}>
          {GALLERY_FILTERS.map((f) => {
            const on = f.key === filter;
            return (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                type="button"
                aria-pressed={on}
                style={{
                  padding: '8px 15px', borderRadius: 99, cursor: 'pointer',
                  fontFamily: "'DM Sans',sans-serif", fontSize: 13, fontWeight: 500,
                  transition: 'all 200ms',
                  border: `1px solid ${on ? '#1B6C42' : 'rgba(42,39,31,0.16)'}`,
                  background: on ? '#1B6C42' : 'transparent',
                  color: on ? '#faf8f3' : '#6f6857',
                }}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        <div style={{ marginTop: 26, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px,1fr))', gap: 22 }}>
          {shots.map((s, i) => (
            <figure
              key={s.slot}
              style={{
                margin: 0, display: 'flex', flexDirection: 'column', gap: 12,
                animation: 'fadeUp 600ms ease both',
                // capped so a large filter result still settles quickly
                animationDelay: `${Math.min(i * 50, 400)}ms`,
              }}
            >
              <div style={{ position: 'relative', width: '100%', aspectRatio: '16 / 10', borderRadius: 14, overflow: 'hidden', background: '#ebe6dc', border: '1px solid rgba(42,39,31,0.10)', boxShadow: '0 10px 28px -16px rgba(26,24,20,0.45)' }}>
                <span style={{ position: 'absolute', left: 10, top: 10, padding: '4px 9px', borderRadius: 6, background: 'rgba(250,248,243,0.9)', backdropFilter: 'blur(4px)', fontFamily: MONO, fontSize: 9, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#3f3b31' }}>
                  {s.route}
                </span>
              </div>
              <figcaption style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                <span style={{ display: 'flex', alignItems: 'baseline', gap: 9 }}>
                  <span style={{ fontSize: 15, fontWeight: 600, color: '#1a1814', letterSpacing: '-0.01em' }}>{s.title}</span>
                  <span style={{ fontFamily: MONO, fontSize: 9, lineHeight: 1, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C' }}>{s.group}</span>
                </span>
                <span style={{ fontFamily: SERIF, fontSize: 14, lineHeight: 1.6, color: '#3f3b31' }}>{s.body}</span>
              </figcaption>
            </figure>
          ))}
        </div>

        <div style={{ marginTop: 52, borderRadius: 18, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)', padding: 'clamp(26px,4vw,40px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ maxWidth: '46ch' }}>
            <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C' }}>
              Rather try it than look at it
            </span>
            <p style={{ margin: '10px 0 0', fontFamily: SERIF, fontSize: 15.5, lineHeight: 1.65, color: '#3f3b31' }}>
              Every screen here is playable on the home page. Open any tool in the toolkit and it
              runs a real scenario.
            </p>
          </div>
          <Link href="/#gallery" className="cp-cta" style={{ background: '#1B6C42', color: '#fff', borderRadius: 8, padding: '13px 24px', fontSize: 14.5, fontWeight: 600, whiteSpace: 'nowrap' }}>
            Open the toolkit
          </Link>
        </div>
      </div>
    </CompanionShell>
  );
}
