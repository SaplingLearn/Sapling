import type { MetadataRoute } from 'next';
import { resolveFrontendEnv, resolveSiteUrl } from '@/lib/deployGuard';
import { SHELL_PREFIXES } from '@/lib/appRoutes';

// The private app surface: every app-shell route (lib/appRoutes.ts — the
// same list middleware.ts auth-gates), plus the auth/api/onboarding flows and
// app routes that live outside (shell).
const PRIVATE = [
  ...SHELL_PREFIXES,
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
