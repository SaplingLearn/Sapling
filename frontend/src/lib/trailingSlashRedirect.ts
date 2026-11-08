/**
 * The trailing-slash redirect next.config.ts installs in place of Next's own.
 *
 * `skipTrailingSlashRedirect` turns Next's built-in off, because PostHog's
 * endpoints end in a slash (`/ingest/e/`) and the built-in would 308 every
 * analytics request before the /ingest route handler sees it. This rule puts
 * the redirect back for every other path: `/about/` → `/about`, `/api/foo/`
 * → `/api/foo`, encoded slugs untouched.
 *
 * It mirrors the built-in Next applies with `trailingSlash: false` (this
 * app's setting) — `{ source: '/:path+/', destination: '/:path+' }` in
 * next/dist/lib/load-custom-routes.js — minus `/ingest/*`. That built-in has
 * NO `.well-known` exclusion (only the `trailingSlash: true` pair carries
 * one), so neither does this: `/.well-known/x/` → `/.well-known/x`, as
 * before. trailingSlashRedirect.test.ts pins the parity.
 *
 * Split into a first segment + `:rest*` on purpose: OpenNext compiles the
 * destination with path-to-regexp, which rejects a single param whose value
 * contains a "/" (a `/:path(.*)/` form 500s on /news/<slug>/). Verified under
 * `next start` AND the OpenNext worker (`wrangler dev`).
 */
export const TRAILING_SLASH_REDIRECT = {
  source: "/:first((?!ingest/)[^/]+)/:rest*/",
  destination: "/:first/:rest*",
  permanent: true,
};
