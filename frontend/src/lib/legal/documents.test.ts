/**
 * The legal documents' one source of truth. The version strings are read by a
 * backend test (backend/config.py must match), so their exact form
 * is pinned here too.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { PRIVACY, TERMS, legalDateLabel, legalDocumentText } from './documents';
import { PRIVACY_VERSION, TERMS_VERSION } from './versions';

describe('legal versions', () => {
  it('are the documents\' "Last updated" dates', () => {
    expect(TERMS_VERSION).toBe('2026-10-22');
    expect(PRIVACY_VERSION).toBe('2026-11-16');
    expect(TERMS.version).toBe(TERMS_VERSION);
    expect(PRIVACY.version).toBe(PRIVACY_VERSION);
    expect(legalDateLabel(TERMS.version)).toBe('October 22, 2026');
    expect(legalDateLabel(PRIVACY.version)).toBe('November 16, 2026');
  });

  it('keep the exact form the backend reads', () => {
    const source = readFileSync(path.join(__dirname, 'versions.ts'), 'utf8');
    expect(source).toContain('export const TERMS_VERSION = "2026-10-22";');
    expect(source).toContain('export const PRIVACY_VERSION = "2026-11-16";');
  });
});

describe('legalDateLabel', () => {
  it('formats an ISO date without a time-zone shift, and passes anything else through', () => {
    expect(legalDateLabel('2026-01-01')).toBe('January 1, 2026');
    expect(legalDateLabel('2026-13-01')).toBe('2026-13-01');
    expect(legalDateLabel('soon')).toBe('soon');
  });
});

describe('the documents', () => {
  it('name what Sapling uses today, not the old onboarding copy', () => {
    const terms = legalDocumentText(TERMS).join('\n');
    expect(terms).toContain("Sapling uses Anthropic's Claude");
    expect(terms).not.toContain('Sapling uses Google Gemini');
    const privacy = legalDocumentText(PRIVACY).join('\n');
    expect(privacy).toContain('PostHog');
    expect(privacy).toContain('Do Not Track');
  });

  it('describe self-service deletion as the backend does it: hidden at once, erased after 30 days', () => {
    // services/profile/deletion.py + services/account_purge.py (GRACE_DAYS,
    // KEPT_AFTER_PURGE). The Settings Danger Zone and the account_deleted
    // sign-in error say the same.
    const retention = PRIVACY.sections.find((s) => s.title.startsWith('5. '))!;
    const text = legalDocumentText({ ...PRIVACY, sections: [retention] }).join('\n');
    expect(text).toContain('Settings → Data');
    expect(text).toContain('30 days after the deletion');
    expect(text).toContain('Gradescope');
    expect(text).toContain('AI usage records');
    expect(text).not.toContain('feedback tool');
  });

  it('number their sections in order', () => {
    for (const doc of [TERMS, PRIVACY]) {
      doc.sections.forEach((s, i) => expect(s.title.startsWith(`${i + 1}. `), s.title).toBe(true));
    }
  });
});
