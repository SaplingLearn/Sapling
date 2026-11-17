/**
 * Gummi (ZEKUTYPE, via fonts.xyz) is the heading face, and it is commercially
 * licensed: web use on saplinglearn.com and its subdomains only, no
 * redistribution. So the files are NOT in this repository. They live in the R2
 * bucket `sapling-licensed-fonts` (Saplinglearn Cloudflare account), served at
 * GUMMI_ORIGIN, whose CORS allowlist names exactly the hosts below. See
 * docs/licensed-fonts.md.
 *
 * The font is switched on per host, before first paint, by GUMMI_BOOT_SCRIPT
 * (an inline <head> script in app/layout.tsx). On any other host — a
 * `*.workers.dev` Worker Preview, an E2E slot on 127.0.0.1:310N, a fork —
 * `--font-gummi` stays on Aleo (globals.css) and no Gummi file is ever
 * requested, so an unlicensed host neither uses the font nor logs a CORS error.
 *
 * Keep LICENSED_HOSTS in step with the bucket's CORS rule.
 */

export const GUMMI_ORIGIN = 'https://fonts.saplinglearn.com';

/** Bump with the object prefix when a file changes: objects are `immutable`. */
export const GUMMI_PREFIX = '/gummi/v1';

export const GUMMI_FILES = {
  regular: `${GUMMI_ORIGIN}${GUMMI_PREFIX}/Gummi-Regular.woff2`,
  italic: `${GUMMI_ORIGIN}${GUMMI_PREFIX}/Gummi-Italics.woff2`,
  bold: `${GUMMI_ORIGIN}${GUMMI_PREFIX}/Gummi-Bold.otf`,
} as const;

/**
 * `location.host` values that may load Gummi. saplinglearn.com and any
 * subdomain (the licence), plus the local dev server (the developer's own
 * browser, fetching from saplinglearn.com).
 */
const LICENSED_HOST_RE = /^(?:[a-z0-9-]+\.)*saplinglearn\.com$|^localhost:3000$/;

export function isGummiLicensedHost(host: string): boolean {
  return LICENSED_HOST_RE.test(host.toLowerCase());
}

/**
 * Faces + the role switch, injected only on a licensed host. `html:root`
 * outranks globals.css's `:root` default however the stylesheets end up
 * ordered. Gummi ships no medium (500), so `--medium-stroke` thickens a 500
 * heading; on the Aleo fallback (a real 500) it stays 0.
 */
export const GUMMI_CSS = [
  `@font-face{font-family:'Gummi';src:url('${GUMMI_FILES.regular}') format('woff2');font-weight:400;font-style:normal;font-display:swap}`,
  `@font-face{font-family:'Gummi';src:url('${GUMMI_FILES.italic}') format('woff2');font-weight:400;font-style:italic;font-display:swap}`,
  `@font-face{font-family:'Gummi';src:url('${GUMMI_FILES.bold}') format('opentype');font-weight:700;font-style:normal;font-display:swap}`,
  `html:root{--font-gummi:'Gummi',var(--font-aleo);--medium-stroke:0.6px}`,
].join('');

export const GUMMI_BOOT_SCRIPT =
  `(function(){try{` +
  `if(!${LICENSED_HOST_RE.toString()}.test(location.host.toLowerCase()))return;` +
  `var h=document.head,l=document.createElement('link');` +
  `l.rel='preload';l.as='font';l.type='font/woff2';l.crossOrigin='anonymous';` +
  `l.href=${JSON.stringify(GUMMI_FILES.regular)};h.appendChild(l);` +
  `var s=document.createElement('style');s.id='gummi-faces';` +
  `s.textContent=${JSON.stringify(GUMMI_CSS)};h.appendChild(s);` +
  `}catch(e){}})();`;
