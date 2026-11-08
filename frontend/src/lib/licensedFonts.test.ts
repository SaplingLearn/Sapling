import { describe, expect, it } from 'vitest';
import {
  GUMMI_FALLBACK_MODULE,
  GUMMI_LICENSED_MODULE,
  chooseGummiFont,
  licensedFontsRequired,
} from './licensedFonts';
import manifest from '../app/fonts/licensed-fonts.json';

const FILES = ['Gummi-Regular.woff2', 'Gummi-Italics.woff2', 'Gummi-Bold.otf'];
const all = () => true;
const none = () => false;

describe('chooseGummiFont', () => {
  it('bundles the licensed module when every file is present', () => {
    expect(chooseGummiFont({ files: FILES, exists: all, env: {} })).toEqual({
      module: GUMMI_LICENSED_MODULE,
      licensed: true,
    });
  });

  it('falls back to the Aleo stand-in off-deploy and names what is missing', () => {
    const choice = chooseGummiFont({ files: FILES, exists: (f) => f !== 'Gummi-Bold.otf', env: { CI: 'true' } });
    expect(choice).toEqual({ module: GUMMI_FALLBACK_MODULE, licensed: false, missing: ['Gummi-Bold.otf'] });
  });

  it('refuses the stand-in on a Cloudflare Workers Build', () => {
    const choice = chooseGummiFont({ files: FILES, exists: none, env: { WORKERS_CI: '1' } });
    expect('error' in choice && choice.error).toMatch(/Gummi-Regular\.woff2[\s\S]*LICENSED_FONTS_TOKEN/);
  });

  it('refuses the stand-in when LICENSED_FONTS_REQUIRED=1', () => {
    expect('error' in chooseGummiFont({ files: FILES, exists: none, env: { LICENSED_FONTS_REQUIRED: '1' } })).toBe(true);
  });

  it('still uses the licensed module on a deploy build when the files are there', () => {
    expect(chooseGummiFont({ files: FILES, exists: all, env: { WORKERS_CI: '1' } })).toMatchObject({ licensed: true });
  });
});

describe('licensedFontsRequired', () => {
  it('is only true for an exact "1"', () => {
    expect(licensedFontsRequired({})).toBe(false);
    expect(licensedFontsRequired({ WORKERS_CI: '0' })).toBe(false);
    expect(licensedFontsRequired({ WORKERS_CI: 'true' })).toBe(false);
    expect(licensedFontsRequired({ WORKERS_CI: '1' })).toBe(true);
    expect(licensedFontsRequired({ LICENSED_FONTS_REQUIRED: '1' })).toBe(true);
  });
});

describe('licensed-fonts.json', () => {
  it('lists exactly the files gummi.licensed.ts loads, each with a SHA-256', () => {
    expect(manifest.files.map((f) => f.name).sort()).toEqual([...FILES].sort());
    for (const f of manifest.files) expect(f.sha256).toMatch(/^[0-9a-f]{64}$/);
  });
});
