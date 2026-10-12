/**
 * schema.org JSON-LD for the public surface.
 *
 * Builders only — `components/seo/JsonLd.tsx` renders them. Every builder
 * takes the site origin so URLs are absolute (JSON-LD has no metadataBase to
 * resolve against) and stays a pure function of data the page already
 * renders: the FAQ entries are the same `{q, a}` rows the accordion shows,
 * the article fields are the same `JournalArticle` the article page prints.
 * Structured data that disagrees with the visible page is a spam signal, so
 * never hand-write a second copy of the content here.
 */

import type { JournalArticle } from '@/lib/landing/journalArticles';
import { DEFAULT_OG_IMAGE, SITE_NAME } from './pageMetadata';

type JsonLdObject = Record<string, unknown>;

const SAME_AS = ['https://github.com/SaplingLearn/Sapling'];

const DESCRIPTION =
  'Sapling turns your syllabi, lecture notes, and readings into a living knowledge graph, ' +
  'with an AI tutor, quizzes, and study guides that grow with you.';

function orgId(origin: string): string {
  return `${origin}/#organization`;
}

export function organizationLd(origin: string, contactEmail: string): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    '@id': orgId(origin),
    name: SITE_NAME,
    url: `${origin}/`,
    logo: `${origin}/sapling-icon.svg`,
    description: DESCRIPTION,
    email: contactEmail,
    sameAs: SAME_AS,
    contactPoint: {
      '@type': 'ContactPoint',
      contactType: 'customer support',
      email: contactEmail,
    },
  };
}

export function websiteLd(origin: string): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    '@id': `${origin}/#website`,
    name: SITE_NAME,
    url: `${origin}/`,
    description: DESCRIPTION,
    inLanguage: 'en',
    publisher: { '@id': orgId(origin) },
  };
}

export function faqPageLd(origin: string, path: string, items: readonly { q: string; a: string }[]): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    url: `${origin}${path}`,
    mainEntity: items.map((item) => ({
      '@type': 'Question',
      name: item.q,
      acceptedAnswer: { '@type': 'Answer', text: item.a },
    })),
  };
}

/** The article's own photo when it has one; the shared OG card otherwise. */
export function articleImage(article: JournalArticle): string {
  return article.art.kind === 'photo' ? article.art.src : DEFAULT_OG_IMAGE.url;
}

export function articleLd(origin: string, article: JournalArticle): JsonLdObject {
  const url = `${origin}/news/${article.slug}`;
  return {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    '@id': `${url}#article`,
    headline: article.title,
    description: article.deck,
    datePublished: article.publishedAt,
    dateModified: article.updatedAt ?? article.publishedAt,
    articleSection: article.tag,
    inLanguage: 'en',
    url,
    mainEntityOfPage: { '@type': 'WebPage', '@id': url },
    image: [`${origin}${articleImage(article)}`],
    // The byline on the page is "By the Sapling team", so the author is the
    // organization rather than an invented person.
    author: { '@type': 'Organization', name: `The ${SITE_NAME} team`, url: `${origin}/about` },
    publisher: { '@id': orgId(origin) },
    isPartOf: { '@type': 'Blog', name: 'The Sapling Journal', url: `${origin}/news` },
  };
}
