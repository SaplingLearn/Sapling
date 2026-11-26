import localFont from 'next/font/local';

/*
 * The app's self-hosted faces, shared by the root layout and Storybook
 * (.storybook/preview.tsx) so the catalog renders in the same fonts.
 */

/*
 * Self-hosted, not `next/font/google`.
 *
 * `next/font/google` downloads at build time, and when that fetch fails it
 * does not fail the build — it emits a metric-adjusted fallback and carries
 * on. This project shipped a whole session that way: every face on the site
 * was Times New Roman or Arial wearing the real font's metrics, close enough
 * that layout looked right and only the letterforms were wrong. The warning
 * for it sits in the dev log, which nobody reads while the page renders.
 *
 * The type is the approved Pen set from the redesign (#728) — Aleo for
 * long-form reading text, SUSE for UI, labels and numerals — with headings
 * since moved to the licensed Gummi (below, loaded at runtime). There is no
 * mono webfont: real code falls back to the system monospace (`--font-code`).
 * Each woff2 in ./fonts is a lossless conversion of the official
 * google/fonts binary (ttf SHA-256 62b6cb49… Aleo, 9b4c074d… Aleo Italic,
 * 16bda691… SUSE), committed so the build never needs the network to be
 * typeset correctly. Aleo and SUSE are variable, one file spanning their
 * whole range.
 *
 * All of them are SIL Open Font License 1.1 (the text sits beside each family
 * in ./fonts), which permits redistribution.
 */
export const aleo = localFont({
  src: [
    { path: './fonts/Aleo-variable.woff2', weight: '100 900', style: 'normal' },
    { path: './fonts/Aleo-variable-italic.woff2', weight: '100 900', style: 'italic' },
  ],
  variable: '--font-aleo',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
  adjustFontFallback: 'Times New Roman',
});

/*
 * Gummi (ZEKUTYPE, via fonts.xyz), the heading face, is NOT loaded here: it is
 * commercially licensed (saplinglearn.com only, no redistribution), so its
 * files live outside the repo on fonts.saplinglearn.com and GUMMI_BOOT_SCRIPT
 * (below, in <head>) switches it on only on a licensed host. Everywhere else
 * `--font-gummi` stays on Aleo. See lib/licensedFonts.ts.
 */

export const suse = localFont({
  src: './fonts/SUSE-variable.woff2',
  weight: '100 900',
  variable: '--font-suse',
  display: 'swap',
  fallback: ['system-ui', 'sans-serif'],
});

/*
 * The annotation hand. One use today — the landing gallery's "click to demo
 * the features!" note — and deliberately not wired into any token role, so it
 * stays a voice rather than becoming a fifth body face.
 *
 * `adjustFontFallback` is off: the system `cursive` behind this is Comic Sans
 * on Windows and Apple Chancery on macOS, faces whose metrics have nothing in
 * common with each other or with Caveat. Letting Next metric-match one of them
 * would reflow the note into whichever shape the swap happened to pick, and a
 * rotated scrawl beside an arrow is exactly where that shows.
 */
export const caveat = localFont({
  src: './fonts/Caveat-variable.woff2',
  weight: '400 700',
  variable: '--font-caveat',
  display: 'swap',
  fallback: ['cursive'],
  adjustFontFallback: false,
});

/** The class that puts all three font variables on <html>. */
export const fontVariables = `${aleo.variable} ${suse.variable} ${caveat.variable}`;
