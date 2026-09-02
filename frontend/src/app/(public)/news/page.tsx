'use client';

/**
 * News.
 *
 * Ported from `News.dc.html`. A responsive card grid over a combined
 * search-and-filter bar, closing on a Journal call-out.
 *
 * The filter is a real listbox rather than a row of pills — the source packs
 * the query field, a clear button and the category menu into one rounded
 * control, and the menu marks its active option with a check.
 *
 * Posts without artwork show a plain tinted panel. The source fills those
 * with its `image-slot` authoring component (a drag-to-fill drop zone), which
 * has no place in the shipped page; the import carries images for two of the
 * six posts.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { NEWS_FILTERS, NEWS_POSTS } from '@/lib/landing/companionContent';

const MONO = "'JetBrains Mono',monospace";
const SERIF = "'Spectral',Georgia,serif";
const DISPLAY = "'Playfair Display',Georgia,serif";

/** The two posts the import ships artwork for. */
const ART: Record<string, string> = {
  'assets/journal-founding.png': '/journal-founding.png',
  'assets/journal-ai-homework.png': '/journal-ai-homework.png',
};

export default function NewsPage() {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Closing the menu has to hand focus back to the trigger. Without it a
  // keyboard user who dismisses the listbox loses their place entirely: the
  // option they were on is display:none'd and focus falls to <body>, so the
  // next Tab restarts from the top of the document.
  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    triggerRef.current?.focus();
  }, []);

  // close the category menu on an outside click, like the source's away handler
  useEffect(() => {
    const away = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, []);

  // Escape is the other half of the dismiss contract the source never wired
  // (WAI-ARIA listbox pattern): a popup opened from a button must close on
  // Escape. Bound only while open so it can't swallow Escape from anything
  // else on the page.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      closeMenu();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [menuOpen, closeMenu]);

  const q = query.trim().toLowerCase();
  const posts = NEWS_POSTS.filter((p) => {
    if (filter !== 'all' && p.cat !== filter) return false;
    if (!q) return true;
    return `${p.title} ${p.excerpt} ${p.tag}`.toLowerCase().includes(q);
  });

  const activeLabel = NEWS_FILTERS.find((f) => f.key === filter)?.label ?? 'All articles';

  return (
    <CompanionShell current="/news">
      <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: 1240, margin: '0 auto', padding: '64px 32px', boxSizing: 'border-box' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div>
            <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857', animation: 'fadeUp 600ms ease both' }}>
              Notes from the build
            </span>
            <h1 style={{ margin: '14px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', animation: 'fadeUp 700ms ease 60ms both' }}>
              News
            </h1>
          </div>
          <Link
            href="/#newsletter"
            className="cp-navlink"
            style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#1B6C42', paddingBottom: 4, borderBottom: '1px solid rgba(27,108,66,0.35)' }}
          >
            Subscribe →
          </Link>
        </div>

        <p style={{ margin: '20px 0 0', fontFamily: SERIF, fontSize: 16, lineHeight: 1.6, color: '#3f3b31', maxWidth: '62ch', animation: 'fadeUp 700ms ease 140ms both' }}>
          Releases, decisions, and what we are learning about learning. One letter a month while we
          build.
        </p>

        {/* one control: query, clear, divider, category listbox */}
        <div style={{ position: 'relative', zIndex: 30, marginTop: 30, display: 'flex', alignItems: 'center', gap: 10, maxWidth: 560, padding: '6px 6px 6px 14px', borderRadius: 10, border: '1px solid rgba(42,39,31,0.16)', background: '#faf8f3' }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6f6857" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.3-4.3" />
          </svg>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search posts"
            aria-label="Search posts"
            style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent', fontFamily: "'DM Sans',sans-serif", fontSize: 14, color: '#1a1814' }}
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              type="button"
              aria-label="Clear search"
              style={{ flex: '0 0 auto', width: 20, height: 20, borderRadius: 99, border: 'none', background: 'rgba(42,39,31,0.10)', color: '#6f6857', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          )}
          <span aria-hidden="true" style={{ flex: '0 0 auto', width: 1, height: 22, background: 'rgba(42,39,31,0.14)' }} />

          <div ref={menuRef} style={{ flex: '0 0 auto', position: 'relative' }}>
            <button
              ref={triggerRef}
              onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}
              type="button"
              aria-haspopup="listbox"
              aria-expanded={menuOpen}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, border: 'none', background: 'transparent', fontFamily: "'DM Sans',sans-serif", fontSize: 13.5, fontWeight: 500, color: '#1a1814', cursor: 'pointer', whiteSpace: 'nowrap' }}
            >
              {activeLabel}
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#6f6857" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, transition: 'transform 220ms', transform: menuOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}>
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>

            <div
              role="listbox"
              style={{
                position: 'absolute', right: 0, top: 'calc(100% + 10px)', minWidth: '100%',
                width: 'max-content', zIndex: 40, borderRadius: 12, background: '#faf8f3',
                border: '1px solid rgba(42,39,31,0.12)', boxShadow: '0 16px 38px -18px rgba(26,24,20,0.4)',
                padding: 6, display: menuOpen ? 'flex' : 'none', flexDirection: 'column', gap: 1,
              }}
            >
              {NEWS_FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => { setFilter(f.key); closeMenu(); }}
                  type="button"
                  role="option"
                  aria-selected={f.key === filter}
                  className="cp-menuitem"
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, width: '100%', textAlign: 'left', padding: '9px 12px', borderRadius: 8, border: 'none', background: 'transparent', fontFamily: "'DM Sans',sans-serif", fontSize: 13.5, color: f.key === filter ? '#1a1814' : '#6f6857', fontWeight: f.key === filter ? 600 : 500, cursor: 'pointer' }}
                >
                  {f.label}
                  {f.key === filter && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#1B6C42" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>

        {posts.length === 0 && (
          <div style={{ marginTop: 44, padding: '44px 0', borderTop: '1px solid rgba(42,39,31,0.10)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, textAlign: 'center' }}>
            <span style={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: 22, letterSpacing: '-0.015em', color: '#1a1814' }}>
              Nothing matches &ldquo;{query}&rdquo;
            </span>
            <span style={{ fontFamily: SERIF, fontSize: 15, lineHeight: 1.6, color: '#3f3b31' }}>
              Try a different word, or clear the filters.
            </span>
            <button
              onClick={() => { setQuery(''); setFilter('all'); }}
              type="button"
              style={{ marginTop: 10, padding: '11px 20px', borderRadius: 8, border: '1px solid rgba(42,39,31,0.16)', background: '#faf8f3', fontFamily: "'DM Sans',sans-serif", fontSize: 13.5, color: '#1a1814', cursor: 'pointer' }}
            >
              Clear filters
            </button>
          </div>
        )}

        <div style={{ marginTop: 26, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px,1fr))', gap: 26 }}>
          {posts.map((p) => {
            const art = ART[p.src];
            return (
              <Link
                key={p.title}
                // Every card points at the Journal sign-up, not an article page —
                // none of these posts is published yet. The label below has to say
                // so, or the card promises a read it cannot deliver.
                href="/#newsletter"
                aria-label={`${p.title} — get notified when this article is published`}
                className="cp-newscard"
                style={{ display: 'flex', flexDirection: 'column', borderRadius: 16, overflow: 'hidden', background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)', color: 'inherit', transition: 'border-color 220ms, transform 220ms' }}
              >
                <div style={{ position: 'relative', width: '100%', aspectRatio: '16 / 10', background: '#ebe6dc', borderBottom: '1px solid rgba(42,39,31,0.08)' }}>
                  {art && <Image src={art} alt="" fill sizes="(max-width: 900px) 100vw, 33vw" style={{ objectFit: 'cover' }} />}
                </div>
                <div style={{ padding: '20px 22px 24px', display: 'flex', flexDirection: 'column', gap: 11 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 12, lineHeight: 1 }}>
                    <span style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1, letterSpacing: '0.06em', color: '#6f6857' }}>{p.date}</span>
                    <span style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C' }}>{p.tag}</span>
                  </span>
                  <h2 style={{ margin: 0, fontFamily: DISPLAY, fontWeight: 500, fontSize: 21, lineHeight: 1.24, letterSpacing: '-0.015em', color: '#1a1814' }}>{p.title}</h2>
                  <p style={{ margin: 0, fontFamily: SERIF, fontSize: 14.5, lineHeight: 1.62, color: '#3f3b31' }}>{p.excerpt}</p>
                  <span style={{ marginTop: 5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, lineHeight: 1 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, lineHeight: 1, color: '#1B6C42' }}>Get notified →</span>
                    <span style={{ fontFamily: MONO, fontSize: 10, lineHeight: 1, letterSpacing: '0.14em', color: '#6f6857' }}>{p.time}</span>
                  </span>
                </div>
              </Link>
            );
          })}
        </div>

        <div style={{ marginTop: 52, borderRadius: 18, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.10)', padding: 'clamp(26px,4vw,40px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ maxWidth: '46ch' }}>
            <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C' }}>
              The Sapling Journal
            </span>
            <p style={{ margin: '10px 0 0', fontFamily: SERIF, fontSize: 15.5, lineHeight: 1.65, color: '#3f3b31' }}>
              One letter a month, written by the four of us. First issue lands with the beta.
            </p>
          </div>
          <Link href="/#newsletter" className="cp-cta" style={{ background: '#1B6C42', color: '#fff', borderRadius: 8, padding: '13px 24px', fontSize: 14.5, fontWeight: 600, whiteSpace: 'nowrap' }}>
            Get the Journal
          </Link>
        </div>
      </div>
    </CompanionShell>
  );
}
