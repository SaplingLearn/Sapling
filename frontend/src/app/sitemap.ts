import type { MetadataRoute } from 'next';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { JOBS } from './(public)/careers/jobs';

// Only the public marketing/legal surface belongs here — the app shell is
// auth-gated and disallowed in robots.ts.
export default function sitemap(): MetadataRoute.Sitemap {
  const base = resolveSiteUrl(process.env);
  return [
    { url: `${base}/`, changeFrequency: 'weekly', priority: 1 },
    { url: `${base}/about`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${base}/careers`, changeFrequency: 'weekly', priority: 0.6 },
    { url: `${base}/privacy`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${base}/terms`, changeFrequency: 'yearly', priority: 0.3 },
    ...JOBS.map(job => ({
      url: `${base}/careers/${job.slug}`,
      changeFrequency: 'weekly' as const,
      priority: 0.5,
    })),
  ];
}
