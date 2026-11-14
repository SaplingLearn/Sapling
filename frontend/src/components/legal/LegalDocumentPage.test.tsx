// @vitest-environment jsdom
/**
 * The public /terms and /privacy pages render the shared legal documents in
 * full — the same text, version and date onboarding shows and a student
 * agrees to (lib/legal/documents.ts).
 */
import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import TermsPage from '@/app/(public)/terms/page';
import PrivacyPage from '@/app/(public)/privacy/page';
import { PRIVACY, TERMS, legalDocumentText, type LegalDocument } from '@/lib/legal/documents';

/** Whitespace-normalised, so a string split across JSX lines still matches. */
const flat = (s: string) => s.replace(/\s+/g, ' ').trim();

function expectWhole(doc: LegalDocument) {
  const text = flat(document.body.textContent ?? '');
  for (const part of legalDocumentText(doc)) expect(text, part.slice(0, 60)).toContain(flat(part));
}

describe('public legal pages', () => {
  afterEach(cleanup);

  it('/terms is the shared Terms of Service, dated by its version', () => {
    render(<TermsPage />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Terms of Service');
    expect(screen.getByTestId('legal-updated').textContent).toBe('Last updated: October 22, 2026');
    expectWhole(TERMS);
    expect(screen.getByRole('link', { name: 'careers@saplinglearn.com' }).getAttribute('href')).toBe(
      'mailto:careers@saplinglearn.com',
    );
  });

  it('/privacy is the shared Privacy Policy, dated by its version', () => {
    render(<PrivacyPage />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Privacy Policy');
    expect(screen.getByTestId('legal-updated').textContent).toBe('Last updated: November 3, 2026');
    expectWhole(PRIVACY);
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(PRIVACY.sections.length);
  });
});
