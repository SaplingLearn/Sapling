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

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ArticleArt } from '@/components/journal/ArticleArt';
import { NEWS_FILTERS, NEWS_POSTS } from '@/lib/landing/companionContent';
import { cn } from "@/lib/cn";

export default function NewsPage() {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // close the category menu on an outside click, like the source's away handler
  useEffect(() => {
    const away = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, []);

  const q = query.trim().toLowerCase();
  const posts = NEWS_POSTS.filter((p) => {
    if (filter !== 'all' && p.cat !== filter) return false;
    if (!q) return true;
    // the article body too, not just the card copy (#601)
    return `${p.title} ${p.excerpt} ${p.tag} ${p.text}`.toLowerCase().includes(q);
  });

  const activeLabel = NEWS_FILTERS.find((f) => f.key === filter)?.label ?? 'All articles';

  return (
    <CompanionShell current="/news">
      <div>
        <div className="flex items-end justify-between gap-6 flex-wrap">
          <div>
            <span className="block font-sans text-sm text-text-muted [animation:fadeUp_600ms_ease_both]">
              Notes from the build
            </span>
            <h1 className="mt-3.5 mx-0 mb-0 font-display font-medium text-[48px] leading-[1.15] tracking-[-0.015em] [animation:fadeUp_700ms_ease_60ms_both]">
              News
            </h1>
          </div>
          <Link
            href="/#newsletter"
            className="cp-navlink font-sans text-md text-brand-forest pb-1 border-b border-b-[rgba(68,93,34,0.35)]"
          >
            Subscribe →
          </Link>
        </div>

        <p className="mt-5 mx-0 mb-0 font-serif text-lg leading-[1.6] text-ink-600 max-w-[62ch] [animation:fadeUp_700ms_ease_140ms_both]">
          Releases, decisions, and what we are learning about learning. One letter a month while we
          build.
        </p>

        {/* one control: query, clear, divider, category listbox */}
        <div className="relative z-30 mt-7.5 flex items-center gap-2.5 max-w-140 pt-1.5 pr-1.5 pb-1.5 pl-3.5 rounded-md border border-[rgba(42,39,31,0.16)] bg-ink-0">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6f6857" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.3-4.3" />
          </svg>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search posts"
            aria-label="Search posts"
            className="flex-1 min-w-0 border-0 outline-none bg-transparent font-sans text-base text-ink-800"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              type="button"
              aria-label="Clear search"
              className="flex-[0_0_auto] w-5 h-5 rounded-[99px] border-0 bg-[rgba(42,39,31,0.10)] text-text-muted cursor-pointer flex items-center justify-center"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          )}
          <span aria-hidden="true" className="flex-[0_0_auto] w-px h-5.5 bg-[rgba(42,39,31,0.14)]" />

          <div ref={menuRef} className="flex-[0_0_auto] relative">
            <button
              onClick={() => setMenuOpen((o) => !o)}
              type="button"
              aria-haspopup="listbox"
              aria-expanded={menuOpen}
              className="flex items-center gap-2 py-2 px-3 rounded-[8px] border-0 bg-transparent font-sans text-[13.5px] font-medium text-ink-800 cursor-pointer whitespace-nowrap"
            >
              {activeLabel}
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#6f6857" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className={cn("shrink-0 [transition:transform_220ms]", menuOpen ? "[transform:rotate(180deg)]" : "[transform:rotate(0deg)]")}>
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>

            <div
              role="listbox"
              className={cn("absolute right-0 top-[calc(100%_+_10px)] min-w-full w-max z-40 rounded-[12px] bg-ink-0 border border-[rgba(42,39,31,0.12)] [box-shadow:0_16px_38px_-18px_rgba(26,24,20,0.4)] p-1.5 flex-col gap-px", menuOpen ? "flex" : "hidden")}
            >
              {NEWS_FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => { setFilter(f.key); setMenuOpen(false); }}
                  type="button"
                  role="option"
                  aria-selected={f.key === filter}
                  className={cn("cp-menuitem", "flex items-center justify-between gap-3 w-full text-left py-[9px] px-3 rounded-[8px] border-0 [background:transparent] font-sans text-[13.5px] cursor-pointer", f.key === filter ? "text-ink-800" : "text-text-muted", f.key === filter ? "font-semibold" : "font-medium")}
                >
                  {f.label}
                  {f.key === filter && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#445D22" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>

        {posts.length === 0 && (
          <div className="mt-11 py-11 px-0 border-t border-t-[rgba(42,39,31,0.10)] flex flex-col items-center gap-2 text-center">
            <span className="font-display font-medium text-2xl tracking-[-0.015em] text-ink-800">
              Nothing matches &ldquo;{query}&rdquo;
            </span>
            <span className="font-serif text-[15px] leading-[1.6] text-ink-600">
              Try a different word, or clear the filters.
            </span>
            <button
              onClick={() => { setQuery(''); setFilter('all'); }}
              type="button"
              className="mt-2.5 py-[11px] px-5 rounded-[8px] border border-[rgba(42,39,31,0.16)] bg-ink-0 font-sans text-[13.5px] text-ink-800 cursor-pointer"
            >
              Clear filters
            </button>
          </div>
        )}

        <div className="mt-6.5 grid grid-cols-[repeat(auto-fill,_minmax(330px,1fr))] gap-6.5">
          {posts.map((p) => (
            <Link
              key={p.title}
              href={`/news/${p.slug}`}
              className="cp-newscard flex flex-col rounded-lg overflow-hidden [background:#faf8f3] border border-[rgba(42,39,31,0.10)] text-inherit [transition:border-color_220ms,_transform_220ms]"
            >
              <div className="relative w-full aspect-[16/10] bg-ink-100 border-b border-b-[rgba(42,39,31,0.08)]">
                <ArticleArt art={p.art} sizes="(max-width: 900px) 100vw, 33vw" />
              </div>
              <div className="pt-5 px-5.5 pb-6 flex flex-col gap-[11px]">
                <span className="flex items-center gap-3 leading-none">
                  <span className="font-sans text-sm leading-none tracking-[0.06em] text-text-muted">{p.date}</span>
                  <span className="font-sans text-sm leading-none text-brand-forest-bright">{p.tag}</span>
                </span>
                <h2 className="m-0 font-display font-medium text-[21px] leading-[1.24] tracking-[-0.015em] text-ink-800">{p.title}</h2>
                <p className="m-0 font-serif text-[14.5px] leading-[1.62] text-ink-600">{p.excerpt}</p>
                <span className="mt-[5px] flex items-center justify-between gap-3 leading-none">
                  <span className="text-md font-semibold leading-none text-brand-forest">Read article →</span>
                  <span className="font-sans text-sm leading-none tracking-[0.14em] text-text-muted">{p.time}</span>
                </span>
              </div>
            </Link>
          ))}
        </div>

        <div className="mt-13 rounded-[18px] bg-ink-0 border border-[rgba(42,39,31,0.10)] p-[clamp(26px,4vw,40px)] flex items-center justify-between gap-6 flex-wrap">
          <div className="max-w-[46ch]">
            <span className="block font-sans text-sm text-brand-forest-bright">
              The Sapling Journal
            </span>
            <p className="mt-2.5 mx-0 mb-0 font-serif text-[15.5px] leading-[1.65] text-ink-600">
              One letter a month, written by the four of us. First issue lands with the beta.
            </p>
          </div>
          <Link href="/#newsletter" className="cp-cta [background:var(--brand-forest)] text-accent-fg rounded-[8px] py-[13px] px-6 text-[14.5px] font-semibold whitespace-nowrap">
            Get the Journal
          </Link>
        </div>
      </div>
    </CompanionShell>
  );
}
