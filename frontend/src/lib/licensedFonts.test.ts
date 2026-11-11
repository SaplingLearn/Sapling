// @vitest-environment jsdom
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { GUMMI_BOOT_SCRIPT, GUMMI_FILES, isGummiLicensedHost } from './licensedFonts';

describe('isGummiLicensedHost', () => {
  it.each([
    'saplinglearn.com',
    'staging.saplinglearn.com',
    'www.saplinglearn.com',
    'SapLingLearn.com',
    'localhost:3000',
  ])('licenses %s', (host) => {
    expect(isGummiLicensedHost(host)).toBe(true);
  });

  it.each([
    'pr-12-frontend-staging.saplinglearn.workers.dev',
    'frontend.saplinglearn.workers.dev',
    'saplinglearn.com.evil.example',
    'notsaplinglearn.com',
    '127.0.0.1:3101',
    'localhost:3101',
    'localhost:5000',
    'saplinglearn.com:8443',
  ])('refuses %s', (host) => {
    expect(isGummiLicensedHost(host)).toBe(false);
  });
});

describe('GUMMI_BOOT_SCRIPT', () => {
  afterEach(() => {
    document.head.innerHTML = '';
  });

  // The script reads `location.host`; jsdom's is fixed, so run it with a
  // stand-in bound to that name.
  function boot(host: string) {
    new Function('location', GUMMI_BOOT_SCRIPT)({ host });
  }

  it('injects the faces and preload on a licensed host', () => {
    boot('saplinglearn.com');
    const style = document.getElementById('gummi-faces');
    expect(style?.textContent).toContain(GUMMI_FILES.regular);
    expect(style?.textContent).toContain(GUMMI_FILES.bold);
    expect(style?.textContent).toContain("html:root{--font-gummi:'Gummi',var(--font-aleo)");
    const preload = document.head.querySelector('link[rel="preload"]');
    expect(preload?.getAttribute('href')).toBe(GUMMI_FILES.regular);
    expect(preload?.getAttribute('crossorigin')).toBe('anonymous');
  });

  it('does nothing on a workers.dev preview', () => {
    boot('pr-12-frontend-staging.saplinglearn.workers.dev');
    expect(document.head.innerHTML).toBe('');
  });
});

describe('the repository', () => {
  const src = path.resolve(__dirname, '..');
  const pub = path.resolve(__dirname, '../../public');

  function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const p = path.join(dir, name);
      return statSync(p).isDirectory() ? walk(p) : [p];
    });
  }

  it('ships no Gummi file', () => {
    const fonts = [...walk(src), ...walk(pub)].filter((p) => /gummi/i.test(path.basename(p)));
    expect(fonts.filter((p) => /\.(woff2?|otf|ttf|eot)$/i.test(p))).toEqual([]);
  });

  it('never names the family outside licensedFonts.ts', () => {
    // A bare 'Gummi' in a stack would fetch the font on an unlicensed host.
    const offenders = walk(src)
      .filter((p) => /\.(tsx?|css)$/.test(p) && !/licensedFonts(\.test)?\.ts$/.test(p))
      .filter((p) => /['"]Gummi['"]/.test(readFileSync(p, 'utf8')));
    expect(offenders).toEqual([]);
  });
});
