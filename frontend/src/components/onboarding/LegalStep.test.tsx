// @vitest-environment jsdom
/**
 * Onboarding's Terms and Privacy screens show the whole published document
 * (lib/legal/documents.ts), with its date — nothing dropped on the way.
 */
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { LegalStep } from './LegalStep';
import { PRIVACY, TERMS, legalDateLabel, legalDocumentText } from '@/lib/legal/documents';

const flat = (s: string) => s.replace(/\s+/g, ' ').trim();

describe('LegalStep', () => {
  afterEach(cleanup);

  it.each([TERMS, PRIVACY])('renders all of $title', (doc) => {
    render(<LegalStep doc={doc} reachedEnd={false} agreed={false} onReachEnd={vi.fn()} onAgree={vi.fn()} />);
    const text = flat(screen.getByTestId('onboarding-legal-body').textContent ?? '');
    for (const part of legalDocumentText(doc).slice(1)) expect(text, part.slice(0, 60)).toContain(flat(part));
    expect(screen.getByTestId('onboarding-legal-updated').textContent).toBe(`Last updated: ${legalDateLabel(doc.version)}`);
    expect(screen.getByTestId('onboarding-agree').textContent).toContain(`I agree to the ${doc.title}`);
  });

  it('shows a notice under the heading and names it as the heading\'s description', () => {
    render(
      <LegalStep doc={TERMS} reachedEnd agreed={false} notice="Changed." onReachEnd={vi.fn()} onAgree={vi.fn()} />,
    );
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading.getAttribute('aria-describedby')).toBe(screen.getByTestId('onboarding-notice').id);
    expect(heading.getAttribute('tabindex')).toBe('-1');
  });
});
