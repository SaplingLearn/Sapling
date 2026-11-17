// @vitest-environment jsdom
/**
 * Onboarding's Terms and Privacy screens show the whole published document
 * (lib/legal/documents.ts), with its date — nothing dropped on the way — and
 * count it as read only at its end.
 */
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LegalStep } from './LegalStep';
import { PRIVACY, TERMS, legalDateLabel, legalDocumentText } from '@/lib/legal/documents';

const flat = (s: string) => s.replace(/\s+/g, ' ').trim();

/** Gives the document panel a size: jsdom lays nothing out. */
function sized(body: HTMLElement, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(body, 'scrollHeight', { configurable: true, value: scrollHeight });
  Object.defineProperty(body, 'clientHeight', { configurable: true, value: clientHeight });
}

function scrollBodyTo(body: HTMLElement, top: number) {
  body.scrollTop = top;
  fireEvent.scroll(body);
}

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

  it('counts a long document as read only within 8px of its end', () => {
    const onReachEnd = vi.fn();
    render(<LegalStep doc={TERMS} reachedEnd={false} agreed={false} onReachEnd={onReachEnd} onAgree={vi.fn()} />);
    const body = screen.getByTestId('onboarding-legal-body');
    sized(body, 10_000, 500);
    // 99% of the way down still leaves 95px unread.
    scrollBodyTo(body, 9_405);
    expect(onReachEnd).not.toHaveBeenCalled();
    scrollBodyTo(body, 9_491);
    expect(onReachEnd).not.toHaveBeenCalled();
    scrollBodyTo(body, 9_492);
    expect(onReachEnd).toHaveBeenCalledTimes(1);
  });

  it('counts a document that fits without scrolling as read at once', async () => {
    const onReachEnd = vi.fn();
    render(<LegalStep doc={TERMS} reachedEnd={false} agreed={false} onReachEnd={onReachEnd} onAgree={vi.fn()} />);
    sized(screen.getByTestId('onboarding-legal-body'), 400, 500);
    await waitFor(() => expect(onReachEnd).toHaveBeenCalled());
  });
});
