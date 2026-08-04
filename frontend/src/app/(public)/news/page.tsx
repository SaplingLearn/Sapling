'use client';

import { useState } from 'react';
import Image from 'next/image';
import { CompanionBody, CompanionShell } from '@/components/companion/CompanionShell';
import { CloserNote, PageTitle, Prose } from '@/components/companion/primitives';
import { NEWS_FILTERS, NEWS_POSTS } from '@/lib/landing/companionContent';

/** The two posts that have artwork in the import; the rest run text-only. */
const ART: Record<string, string> = {
  'assets/journal-founding.png': '/journal-founding.png',
  'assets/journal-ai-homework.png': '/journal-ai-homework.png',
};

export default function NewsPage() {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');

  const q = query.trim().toLowerCase();
  const posts = NEWS_POSTS.filter((p) => {
    if (filter !== 'all' && p.cat !== filter) return false;
    if (!q) return true;
    return (p.title + ' ' + p.excerpt + ' ' + p.tag).toLowerCase().includes(q);
  });

  return (
    <CompanionShell current="/news">
      <CompanionBody>
        <PageTitle>News</PageTitle>
        <Prose delay={80}>
          Releases, decisions, and what we are learning about learning. One letter a month while we
          build.
        </Prose>

        <div style={{ marginTop: 36, display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', animation: 'fadeUp 700ms ease 140ms both' }}>
          {NEWS_FILTERS.map((f) => {
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
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search articles"
            aria-label="Search articles"
            style={{ marginLeft: 'auto', width: 200, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.16)', borderRadius: 6, padding: '9px 14px', fontFamily: "'DM Sans',system-ui,sans-serif", fontSize: 13, color: '#1a1814', outline: 'none' }}
          />
        </div>

        {posts.length === 0 ? (
          <p style={{ marginTop: 40, fontFamily: "'Spectral',Georgia,serif", fontSize: 15, color: '#6f6857' }}>
            Nothing matches &ldquo;{query}&rdquo;.{' '}
            <button
              onClick={() => { setQuery(''); setFilter('all'); }}
              style={{ background: 'none', border: 'none', padding: 0, color: '#1B6C42', cursor: 'pointer', font: 'inherit', textDecoration: 'underline' }}
            >
              Clear filters
            </button>
          </p>
        ) : (
          <div style={{ marginTop: 40, display: 'flex', flexDirection: 'column', gap: 32 }}>
            {posts.map((p, i) => {
              const art = ART[p.src];
              return (
                <article key={p.title} style={{ display: 'grid', gridTemplateColumns: art ? '200px 1fr' : '1fr', gap: 24, alignItems: 'start', paddingBottom: 32, borderBottom: '1px solid rgba(42,39,31,0.10)', animation: 'fadeUp 700ms ease both', animationDelay: `${80 + i * 60}ms` }}>
                  {art && (
                    <div style={{ position: 'relative', width: '100%', aspectRatio: '16 / 10', borderRadius: 10, overflow: 'hidden', background: '#EEF1EC' }}>
                      <Image src={art} alt="" fill sizes="200px" style={{ objectFit: 'cover' }} />
                    </div>
                  )}
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase' }}>
                      <span style={{ color: '#2D8F5C' }}>{p.tag}</span>
                      <span style={{ color: '#9a9689' }}>{p.date}</span>
                      <span style={{ color: '#9a9689' }}>{p.time}</span>
                    </div>
                    <h2 style={{ margin: '10px 0 0', fontFamily: "'Playfair Display',Georgia,serif", fontWeight: 500, fontSize: 24, lineHeight: 1.25, letterSpacing: '-0.01em', color: '#1a1814' }}>
                      {p.title}
                    </h2>
                    <p style={{ margin: '8px 0 0', fontFamily: "'Spectral',Georgia,serif", fontSize: 15, lineHeight: 1.65, color: '#3f3b31' }}>
                      {p.excerpt}
                    </p>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <CloserNote>One letter a month, written by the four of us. First issue lands with the beta.</CloserNote>
      </CompanionBody>
    </CompanionShell>
  );
}
