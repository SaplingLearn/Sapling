import type { MetadataRoute } from 'next';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { JOURNAL_ARTICLES } from '@/lib/landing/journalArticles';
import { LEGAL_LAST_UPDATED } from '@/lib/legal';
import { JOBS } from './(public)/careers/jobs';

// Only the public marketing/legal surface belongs here — the app shell is
// auth-gated and disallowed in robots.ts. Every entry must be a route that
// renders 200; seo.test.ts pins the list against the (public) directory.
//
// `lastModified` is set only where a real date exists: journal posts carry
// their own, /news moves with its newest post, and the legal pages share
// LEGAL_LAST_UPDATED. A lastmod that is merely "build time" teaches crawlers
// to ignore the field, so the rest omit it.
export default function sitemap(): MetadataRoute.Sitemap {
  const base = resolveSiteUrl(process.env);
  const articleDate = (a: (typeof JOURNAL_ARTICLES)[number]) => a.updatedAt ?? a.publishedAt;
  const newestPost = JOURNAL_ARTICLES.map(articleDate).sort().at(-1);
  return [
    { url: `${base}/`, changeFrequency: 'weekly', priority: 1 },
    { url: `${base}/about`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${base}/faq`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${base}/wiki`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${base}/gallery`, changeFrequency: 'monthly', priority: 0.6 },
    { url: `${base}/news`, lastModified: newestPost, changeFrequency: 'weekly', priority: 0.7 },
    ...JOURNAL_ARTICLES.map((article) => ({
      url: `${base}/news/${article.slug}`,
      lastModified: articleDate(article),
      changeFrequency: 'yearly' as const,
      priority: 0.6,
    })),
    { url: `${base}/careers`, changeFrequency: 'weekly', priority: 0.4 },
    ...JOBS.map(job => ({
      url: `${base}/careers/${job.slug}`,
      changeFrequency: 'weekly' as const,
      priority: 0.4,
    })),
    { url: `${base}/privacy`, lastModified: LEGAL_LAST_UPDATED, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${base}/terms`, lastModified: LEGAL_LAST_UPDATED, changeFrequency: 'yearly', priority: 0.3 },
  ];
}
