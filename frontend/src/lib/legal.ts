/**
 * The effective date of the Privacy Policy and Terms of Service.
 *
 * One ISO day shared by both documents (they are revised together), the
 * "Last updated" line each prints, and their sitemap lastmod. Bump it with any
 * substantive change to either document.
 */
export const LEGAL_LAST_UPDATED = '2026-10-12';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** `2026-05-03` → `May 3, 2026`, read off the string so no timezone can shift it. */
export function legalDateLabel(iso: string = LEGAL_LAST_UPDATED): string {
  const [year, month, day] = iso.split('-');
  return `${MONTHS[Number(month) - 1]} ${Number(day)}, ${year}`;
}
