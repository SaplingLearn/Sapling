/**
 * Which module `@gummi-font` resolves to, decided once when next.config loads.
 *
 * Gummi (the heading face) is commercially licensed and its files are fetched
 * at build time into src/app/fonts/licensed/ (scripts/fetch-licensed-fonts.mjs).
 * When they are all there the real `next/font/local` module is bundled; when
 * they are not, the Aleo stand-in is — except on a deploy build, which must
 * never ship the stand-in and so gets an error to throw instead.
 *
 * Pure (filesystem and env are passed in) so it can be unit-tested; see
 * docs/licensed-fonts.md for the whole flow.
 */

export const GUMMI_LICENSED_MODULE = './src/app/fonts/gummi.licensed.ts';
export const GUMMI_FALLBACK_MODULE = './src/app/fonts/gummi.fallback.ts';

export type GummiFontChoice =
  | { module: typeof GUMMI_LICENSED_MODULE; licensed: true }
  | { module: typeof GUMMI_FALLBACK_MODULE; licensed: false; missing: string[] }
  | { error: string };

/** A deploy build: Cloudflare Workers Builds sets WORKERS_CI=1; LICENSED_FONTS_REQUIRED=1 forces it anywhere. */
export function licensedFontsRequired(env: Record<string, string | undefined>): boolean {
  return env.WORKERS_CI === '1' || env.LICENSED_FONTS_REQUIRED === '1';
}

export function chooseGummiFont(opts: {
  files: readonly string[];
  exists: (fileName: string) => boolean;
  env: Record<string, string | undefined>;
}): GummiFontChoice {
  const missing = opts.files.filter((f) => !opts.exists(f));
  if (missing.length === 0) return { module: GUMMI_LICENSED_MODULE, licensed: true };
  if (licensedFontsRequired(opts.env)) {
    return {
      error:
        `Licensed heading font missing: ${missing.join(', ')} not in src/app/fonts/licensed/. ` +
        'A deploy build must not ship the Aleo stand-in. Set LICENSED_FONTS_TOKEN as a build ' +
        'secret so scripts/fetch-licensed-fonts.mjs can download them (docs/licensed-fonts.md).',
    };
  }
  return { module: GUMMI_FALLBACK_MODULE, licensed: false, missing };
}
