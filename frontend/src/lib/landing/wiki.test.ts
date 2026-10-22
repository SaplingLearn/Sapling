/**
 * The wiki registry holds together.
 *
 * Splitting the single page into /wiki/<slug> routes made a handful of
 * things that used to be one document's job into cross-references between
 * data: slugs are URLs, screenshots key on slugs, and the old /wiki#<id>
 * links forward through `legacyId`. A typo in any of them fails silently in
 * the browser — a 404, a missing figure, a hash link that stops on the
 * index — so they are pinned here instead.
 */
import { describe, expect, it } from 'vitest';

import { matchEntries } from '@/app/(public)/wiki/WikiSearch';

import { GALLERY_SHOTS, WIKI_SHOTS } from './companionContent';
import {
  WIKI_GROUPS, WIKI_ORDER, WIKI_PAGES, getWikiPage, wikiEntries, wikiNeighbours,
  wikiSearchText, wikiSlugForLegacyId,
} from './wiki';

describe('wiki registry', () => {
  it('gives every page a unique, URL-safe slug', () => {
    const slugs = WIKI_PAGES.map((p) => p.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
    for (const s of slugs) expect(s).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
  });

  it('files every page under a known group, and leaves no group empty', () => {
    for (const p of WIKI_PAGES) expect(WIKI_GROUPS).toContain(p.group);
    for (const g of WIKI_GROUPS) expect(WIKI_PAGES.some((p) => p.group === g)).toBe(true);
    expect(WIKI_ORDER).toHaveLength(WIKI_PAGES.length);
  });

  it('gives every page a summary and at least one block', () => {
    for (const p of WIKI_PAGES) {
      expect(p.summary.trim().length).toBeGreaterThan(0);
      expect(p.blocks.length).toBeGreaterThan(0);
    }
  });

  it('keys every screenshot on a real page and a real gallery capture', () => {
    const slots = new Set<string>(GALLERY_SHOTS.map((s) => s.slot));
    for (const [slug, shot] of Object.entries(WIKI_SHOTS)) {
      expect(getWikiPage(slug), `WIKI_SHOTS.${slug}`).toBeDefined();
      expect(slots.has(shot.slot)).toBe(true);
    }
  });

  it('forwards every old single-page section id', () => {
    // The ids the single-page wiki shipped with, and that /faq and old
    // links may still carry.
    const old = ['graph', 'mastery', 'deltas', 'progress', 'quizzes', 'tutor', 'uploads',
      'ingestion', 'notes', 'flashcards', 'guide', 'calendar', 'grades', 'rooms', 'class',
      'onboarding', 'achievements', 'privacy'];
    for (const id of old) expect(wikiSlugForLegacyId(id), id).toBeDefined();
  });

  it('chains previous/next through every page exactly once', () => {
    const first = WIKI_ORDER[0];
    const last = WIKI_ORDER[WIKI_ORDER.length - 1];
    expect(wikiNeighbours(first.slug).prev).toBeUndefined();
    expect(wikiNeighbours(last.slug).next).toBeUndefined();
    const seen = [first.slug];
    let at = first.slug;
    for (let n = wikiNeighbours(at).next; n; n = wikiNeighbours(at).next) {
      seen.push(n.slug);
      at = n.slug;
    }
    expect(seen).toEqual(WIKI_ORDER.map((p) => p.slug));
  });

  it('searches the prose, not just titles, and never the CSS', () => {
    // The 0.75 floor appears only in a tier row, never in a title.
    expect(wikiSearchText(getWikiPage('mastery-tiers')!)).toContain('0.75');
    expect(matchEntries(wikiEntries(), 'velocity').map((e) => e.slug)).toContain('progress-stats');
    for (const p of WIKI_PAGES) {
      const t = wikiSearchText(p);
      expect(t).not.toContain('background:');
      expect(t).not.toContain('color:#');
    }
    expect(wikiEntries().map((e) => e.slug)).toEqual(WIKI_ORDER.map((p) => p.slug));
  });
});
