/**
 * Validate the COOKIE_DOMAIN env value before it scopes the session cookie.
 *
 * #190: COOKIE_DOMAIN was applied verbatim from env, so a misconfigured or
 * overly-broad value (e.g. ".com") would scope the session cookie across
 * unrelated subdomains. A value that fails validation is dropped (returns
 * undefined → host-only cookie) rather than silently widening cookie scope.
 *
 * Note: this is a conservative shape/breadth check, not a full public-suffix
 * lookup — it rejects bare suffixes like ".com" but cannot detect every
 * multi-label public suffix (e.g. ".co.uk"). Pair with a sane deploy config.
 */

// Lowercase DNS name, optional single leading dot, ≥2 labels, each label
// 1-63 chars of [a-z0-9-] not starting/ending with a hyphen. No scheme, port,
// path, whitespace, or uppercase.
const DOMAIN_RE =
  /^\.?(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

export function sanitizeCookieDomain(
  raw: string | undefined | null,
): string | undefined {
  if (!raw) return undefined;
  // DNS is case-insensitive; normalize to lowercase so a config like
  // ".SaplingLearn.com" isn't wrongly rejected by the lowercase-only regex.
  const value = raw.trim().toLowerCase();
  if (!value || !DOMAIN_RE.test(value)) return undefined;

  // Require ≥2 labels in the registrable portion so a bare suffix like ".com"
  // or "com" — which would scope the cookie far too widely — is rejected.
  const labels = value.replace(/^\./, '').split('.');
  if (labels.length < 2) return undefined;

  return value;
}
