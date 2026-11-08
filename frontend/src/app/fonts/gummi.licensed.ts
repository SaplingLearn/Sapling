import localFont from 'next/font/local';

/*
 * Gummi (ZEKUTYPE, via fonts.xyz): the heading face. It owns the display role
 * (`--font-display`, FONT_DISPLAY, the landing's section headings). Aleo keeps
 * long-form reading text, SUSE the UI, Plex Mono numerals and code.
 *
 * Commercially licensed, NOT OFL: the binaries in ./licensed are fetched at
 * build time from a private repo (scripts/fetch-licensed-fonts.mjs) and are
 * git-ignored. This module is only bundled when they are present; next.config
 * aliases `@gummi-font` to ./gummi.fallback.ts otherwise.
 *
 * Gummi ships no medium: a 500 heading renders Regular, thickened by the
 * `--medium-stroke` rules in globals.css so it doesn't read thin.
 */
export const gummi = localFont({
  src: [
    { path: './licensed/Gummi-Regular.woff2', weight: '400', style: 'normal' },
    { path: './licensed/Gummi-Italics.woff2', weight: '400', style: 'italic' },
    { path: './licensed/Gummi-Bold.otf', weight: '700', style: 'normal' },
  ],
  variable: '--font-gummi',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
  adjustFontFallback: 'Times New Roman',
});
