'use client';

/**
 * The wiki's search: one matcher, one input, used by the index and the rail.
 *
 * On the single-page wiki the search read every section's text out of the
 * DOM, because every section was in it. Each topic is its own page now, so
 * the text comes in as `WikiEntry.text` — built from the same blocks the
 * pages render (`wikiSearchText`), so it is still one copy of the content
 * and cannot drift from what is on screen.
 *
 * It matches prose, not just titles: the question is nearly always "which
 * page talks about X", and nobody hunting the retention intervals searches
 * for "How mastery moves". Matching the group name too means "capture" finds
 * the whole Capture set, which is how people search a contents list.
 */

import * as React from 'react';
import type { WikiEntry } from '@/lib/landing/wiki';

export function matchEntries(entries: readonly WikiEntry[], q: string): WikiEntry[] {
  if (!q) return [...entries];
  return entries.filter((e) => e.text.toLowerCase().includes(q));
}

/**
 * A short window of the page's text around the first hit, so a result says
 * why it matched. `null` when the title already explains it.
 */
export function snippet(entry: WikiEntry, q: string, radius = 70): string | null {
  if (!q || entry.title.toLowerCase().includes(q)) return null;
  // Search the summary first so a hit there is shown in its own words.
  const summaryAt = entry.summary.toLowerCase().indexOf(q);
  if (summaryAt >= 0) return null;
  // The page's own words only: the text opens with the title, group and
  // summary, and a hit on the group name ("capture") is not worth quoting.
  const s = entry.text.indexOf(entry.summary);
  const text = s >= 0 ? entry.text.slice(s + entry.summary.length).trim() : entry.text;
  const at = text.toLowerCase().indexOf(q);
  if (at < 0) return null;
  // Widen to whole words, so the window never opens or closes mid-word.
  let start = Math.max(0, at - radius);
  let end = Math.min(text.length, at + q.length + radius);
  if (start > 0) start = Math.min(at, text.indexOf(' ', start) + 1 || at);
  if (end < text.length) end = Math.max(at + q.length, text.lastIndexOf(' ', end));
  const body = text.slice(start, end).replace(/\s+/g, ' ').trim();
  return `${start > 0 ? '…' : ''}${body}${end < text.length ? '…' : ''}`;
}

export function WikiSearchBox({ value, onChange, style, autoFocus }: {
  value: string;
  onChange: (v: string) => void;
  style?: React.CSSProperties;
  autoFocus?: boolean;
}) {
  return (
    <div style={{ position: 'relative', maxWidth: 420, ...style }}>
      <svg
        aria-hidden="true"
        width="15" height="15" viewBox="0 0 24 24" fill="none"
        stroke="#8d866f" strokeWidth="2" strokeLinecap="round"
        style={{ position: 'absolute', left: 13, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
      >
        <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" />
      </svg>
      <input
        type="search"
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
        /* Escape clears rather than blurs: a stale query left behind hides
           most of the wiki from someone who has moved on to reading. */
        onKeyDown={(e) => { if (e.key === 'Escape') onChange(''); }}
        placeholder="Search the wiki"
        aria-label="Search the wiki"
        className="wiki-search"
        style={{
          width: '100%', boxSizing: 'border-box', padding: '11px 14px 11px 38px',
          borderRadius: 10, border: '1px solid rgba(42,39,31,0.16)', background: '#fffdf7',
          fontFamily: 'inherit', fontSize: 15, color: '#2b2619', outline: 'none',
          transition: 'border-color 140ms ease',
        }}
      />
    </div>
  );
}
