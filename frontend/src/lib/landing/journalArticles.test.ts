/**
 * The journal's post metadata has one source of truth.
 *
 * Before #601 the same six posts were described three times — `POSTS` +
 * `POST_META` (landing), `NEWS_POSTS` (/news), `JOURNAL_ARTICLES` (article
 * pages) — each with its own hand-typed tag, date and read time. They had
 * already drifted: the graph post was tagged `Under the hood` on the landing
 * and `Product` everywhere else, and `/news` printed `6/12/2026` against the
 * article header's `JUN 2026`. Nothing could catch that, because agreement
 * between three literal tables is not a property any of them state.
 *
 * These tests state it. The surfaces are derived now, so most of this holds
 * by construction — the point is that it keeps holding when someone adds the
 * seventh post.
 */
import { describe, expect, it } from 'vitest';

import { NEWS_FILTERS, NEWS_POSTS } from './companionContent';
import { POSTS } from './content';
import { JOURNAL_ARTICLES, articleText, dateLabel, getArticle, readTime } from './journalArticles';

describe('dateLabel', () => {
  it('renders an ISO date as the mono eyebrow format', () => {
    expect(dateLabel('2026-06-12')).toBe('12 JUN 2026');
    expect(dateLabel('2026-05-04')).toBe('04 MAY 2026');
  });

  it('does not shift the day across timezones', () => {
    // `new Date('2026-01-01')` is UTC midnight; formatting it anywhere west
    // of Greenwich yields 31 DEC 2025. The formatter must read the string.
    expect(dateLabel('2026-01-01')).toBe('01 JAN 2026');
    expect(dateLabel('2026-12-31')).toBe('31 DEC 2026');
  });
});

describe('readTime', () => {
  const words = (n: number) => Array.from({ length: n }, () => 'word').join(' ');

  it('derives minutes from the body at 200wpm', () => {
    expect(readTime([{ t: 'p', text: words(1200) }])).toBe('6 MIN');
    expect(readTime([{ t: 'p', text: words(600) }])).toBe('3 MIN');
  });

  it('counts headings and list items, not just paragraphs', () => {
    const body = [
      { t: 'p' as const, text: words(300) },
      { t: 'h2' as const, text: words(100) },
      { t: 'ul' as const, items: [words(100), words(100)] },
    ];
    expect(readTime(body)).toBe('3 MIN');
  });

  it('floors at one minute rather than reporting 0 MIN', () => {
    expect(readTime([{ t: 'p', text: 'Three short words.' }])).toBe('1 MIN');
  });
});

describe('articleText', () => {
  it('flattens every block into searchable prose', () => {
    const text = articleText([
      { t: 'h2', text: 'Incentives' },
      { t: 'p', text: 'The deal on offer' },
      { t: 'ul', items: ['guides instead of solving', 'grounded in your course'] },
    ]);
    expect(text).toContain('Incentives');
    expect(text).toContain('The deal on offer');
    expect(text).toContain('grounded in your course');
  });
});

describe('JOURNAL_ARTICLES', () => {
  it('gives every post artwork — no post falls through to an empty panel', () => {
    for (const article of JOURNAL_ARTICLES) {
      if (article.art.kind === 'photo') {
        expect(article.art.src, article.slug).toMatch(/^\/.+\.(png|jpg|webp)$/);
      } else {
        expect(article.art.motif, article.slug).toBeTruthy();
      }
    }
  });

  it('files every post under a category the /news filter offers', () => {
    const keys = NEWS_FILTERS.map((f) => f.key);
    for (const article of JOURNAL_ARTICLES) {
      expect(keys, article.slug).toContain(article.cat);
    }
  });

  it('dates every post as an ISO day', () => {
    for (const article of JOURNAL_ARTICLES) {
      expect(article.publishedAt, article.slug).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it('resolves each slug', () => {
    for (const article of JOURNAL_ARTICLES) {
      expect(getArticle(article.slug)?.title).toBe(article.title);
    }
    expect(getArticle('no-such-post')).toBeUndefined();
  });
});

describe('the card surfaces agree with the article table', () => {
  it('/news cards carry the article tag, date and read time', () => {
    expect(NEWS_POSTS).toHaveLength(JOURNAL_ARTICLES.length);
    for (const post of NEWS_POSTS) {
      const article = getArticle(post.slug);
      expect(article, post.slug).toBeDefined();
      expect(post.tag).toBe(article!.tag);
      expect(post.title).toBe(article!.title);
      expect(post.excerpt).toBe(article!.deck);
      expect(post.date).toBe(dateLabel(article!.publishedAt));
      expect(post.time).toBe(readTime(article!.body));
    }
  });

  it('landing cards are the three most recent articles, same metadata', () => {
    expect(POSTS).toHaveLength(3);
    POSTS.forEach((post, i) => {
      const article = JOURNAL_ARTICLES[i];
      expect(post.slug).toBe(article.slug);
      expect(post.tag).toBe(article.tag);
      expect(post.date).toBe(dateLabel(article.publishedAt));
      expect(post.time).toBe(readTime(article.body));
      expect(post.excerpt).toBe(article.deck);
    });
  });
});
