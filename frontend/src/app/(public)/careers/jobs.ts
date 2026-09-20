export interface Job {
  id: number;
  slug: string;
  title: string;
  department: string;
  location: string;
  type: string;
  description: string;
  tags: string[];
}

/**
 * Open roles. Empty means we are not hiring, and /careers says so rather than
 * rendering an empty table — see the empty state in `CareersList`.
 *
 * Everything downstream already tolerates this: `generateStaticParams` yields
 * no slugs, the sitemap spreads nothing, and `/careers/<anything>` hard-404s
 * through the existing `notFound()` (#187). Adding a role back is a matter of
 * pushing one object here.
 */
export const JOBS: Job[] = [];

/**
 * Department chip colours. Kept while `JOBS` is empty: the palette is per
 * department, not per role, so a returning Growth listing should not have to
 * re-derive it.
 *
 * The alphas are up from 0.07/0.18: these used to sit
 * on the app shell's near-white `--bg`, and once /careers moved onto the
 * companion chrome the chip tints against `#f4f1ea` paper, where a 7% amber
 * wash was indistinguishable from the ground. The hue is unchanged — amber
 * belongs on warm paper.
 */
export const DEPT_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  Growth: { bg: 'rgba(217,119,6,0.12)', text: '#b45309', border: 'rgba(217,119,6,0.26)' },
};
