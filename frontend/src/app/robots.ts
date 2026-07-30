import type { MetadataRoute } from 'next';
import { resolveFrontendEnv, resolveSiteUrl } from '@/lib/deployGuard';

// The private app surface: everything middleware.ts auth-gates, plus the
// auth/api/onboarding flows and app routes that live outside (shell). Keep in
// step with middleware.ts PROTECTED when a new shell route lands.
const PRIVATE = [
  '/dashboard',
  '/learn',
  '/quiz',
  '/study',
  '/tree',
  '/library',
  '/calendar',
  '/social',
  '/settings',
  '/achievements',
  '/admin',
  '/gradebook',
  '/course-planner',
  '/notetaker',
  '/profile',
  '/flashcards',
  '/onboarding',
  '/pending',
  '/auth/',
  '/api/',
];

export default function robots(): MetadataRoute.Robots {
  // Staging serves real UI on a public host — it must never be indexed or the
  // canonical production pages end up competing with their staging twins.
  if (resolveFrontendEnv(process.env).env === 'staging') {
    return { rules: [{ userAgent: '*', disallow: '/' }] };
  }
  const base = resolveSiteUrl(process.env);
  return {
    rules: [{ userAgent: '*', allow: '/', disallow: PRIVATE }],
    sitemap: `${base}/sitemap.xml`,
  };
}
