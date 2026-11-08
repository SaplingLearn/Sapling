/*
 * Stand-in for ./gummi.licensed.ts when the licensed Gummi files are not on
 * disk (CI, E2E, a checkout without LICENSED_FONTS_TOKEN). next.config aliases
 * `@gummi-font` here in that case; deploy builds refuse to (they fail instead).
 *
 * No font is loaded: `--font-gummi` resolves to Aleo through the
 * `.gummi-fallback` rule in globals.css, so headings keep the pre-Gummi look.
 */
export const gummi = { variable: 'gummi-fallback' } as const;
