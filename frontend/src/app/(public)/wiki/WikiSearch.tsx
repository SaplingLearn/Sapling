'use client';

/**
 * The wiki's search, split across two places on the page.
 *
 * The box belongs in the masthead, under the deck, where it reads as "search
 * this reference"; the results belong in the contents rail, which is already
 * the list of everywhere you can go. Those two sit in different branches of
 * the layout, and the page between them is a server component that has to
 * stay one so it keeps exporting `metadata` — so the shared query rides a
 * context whose provider wraps both slots, and the server-rendered sections
 * pass through it untouched as children.
 *
 * The alternative was hoisting the whole page to a client component to get
 * one `useState`, which would have cost the metadata export and shipped
 * eighteen sections of static reference prose to the browser as JavaScript.
 */

import * as React from 'react';
import { WIKI_TOC } from '@/lib/landing/companionContent';

interface WikiSearchValue {
  /** Raw input text. */
  query: string;
  /** Trimmed and lowercased — what every matcher should actually test. */
  q: string;
  setQuery: (v: string) => void;
  /** Section id → that section's text, lowercased. Empty until first use. */
  prose: Record<string, string>;
  /** Read the sections out of the document, once, on the first keystroke. */
  index: () => void;
}

const Ctx = React.createContext<WikiSearchValue | null>(null);

/**
 * Read every section's rendered text.
 *
 * The rail is handed titles and nothing else, so a title-only search answers
 * "is this section called X" when the question is nearly always "which
 * section talks about X" — nobody hunting the retention intervals searches
 * for "How mastery moves". Every section is already in the document, so the
 * prose is there to read; taking it from the DOM keeps one copy of the
 * content instead of an index beside `WIKI_TOC` that would drift the first
 * time a paragraph changed.
 */
function readSections(): Record<string, string> {
  const map: Record<string, string> = {};
  for (const group of WIKI_TOC) {
    for (const item of group.items) {
      const id = item.href.slice(1);
      const el = document.getElementById(id);
      if (el) map[id] = (el.innerText || '').toLowerCase();
    }
  }
  return map;
}

export function WikiSearchProvider({ children }: { children: React.ReactNode }) {
  const [query, setQuery] = React.useState('');
  const [prose, setProse] = React.useState<Record<string, string>>({});
  const indexed = React.useRef(false);

  // Built from the event handler rather than an effect, so a reader who never
  // searches never pays to walk eighteen sections, and nothing touches the
  // DOM during render.
  const index = React.useCallback(() => {
    if (indexed.current) return;
    indexed.current = true;
    setProse(readSections());
  }, []);

  const value = React.useMemo(
    () => ({ query, q: query.trim().toLowerCase(), setQuery, prose, index }),
    [query, prose, index],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWikiSearch(): WikiSearchValue {
  const v = React.useContext(Ctx);
  if (!v) throw new Error('useWikiSearch outside WikiSearchProvider');
  return v;
}

/** The input itself, for the masthead. */
export function WikiSearchBox({ style }: { style?: React.CSSProperties }) {
  const { query, setQuery, index } = useWikiSearch();

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
        value={query}
        onChange={(e) => { index(); setQuery(e.target.value); }}
        /* Escape clears rather than blurs: this filters the contents rail, and
           a stale query left behind hides most of the page from someone who
           has moved on to reading. */
        onKeyDown={(e) => { if (e.key === 'Escape') setQuery(''); }}
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
