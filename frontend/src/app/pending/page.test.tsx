// @vitest-environment jsdom
/**
 * #290 — the approval gate needs a surface and a confirmation beat.
 *
 * The page used to float a sprout, a headline, a paragraph and a button
 * directly on a radial gradient: signing up ended in silence rather than a
 * "you're in" moment. These tests pin the three things that fix has to keep
 * true — the content sits on a real `.card` surface, the beat plays exactly
 * once, and both E2E anchors survive the redesign untouched.
 */
import React from 'react';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const replace = vi.fn();
const signOut = vi.fn().mockResolvedValue(undefined);

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));
vi.mock('@/context/UserContext', () => ({ useUser: () => ({ signOut }) }));

import PendingPage from './page';

afterEach(() => {
  cleanup();
  replace.mockClear();
  signOut.mockClear();
});

describe('#290 approval gate', () => {
  it('keeps both E2E anchors', () => {
    render(<PendingPage />);
    expect(screen.getByTestId('pending-gate')).toBeTruthy();
    expect(screen.getByTestId('pending-signout')).toBeTruthy();
  });

  it('still signs out and returns to the landing page', async () => {
    render(<PendingPage />);
    fireEvent.click(screen.getByTestId('pending-signout'));
    await waitFor(() => expect(signOut).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/'));
  });

  it('puts the message on a card surface instead of floating on the gradient', () => {
    render(<PendingPage />);
    const gate = screen.getByTestId('pending-gate');
    const card = gate.querySelector('.card');
    expect(card, 'the gate content should sit inside a .card surface').toBeTruthy();
    // .card supplies bg/border/radius/shadow but no padding — that is the
    // caller's job, and an unpadded card is the bug in a different costume.
    expect(
      (card as HTMLElement).style.padding,
      'the card must set its own padding',
    ).not.toBe('');
    // The anchors must live INSIDE the new surface, not beside it.
    expect(card!.contains(screen.getByTestId('pending-signout'))).toBe(true);
  });

  it('plays the confirmation beat exactly once', () => {
    const css = fs.readFileSync(path.resolve(__dirname, '../globals.css'), 'utf8');
    const rules = css.match(/\.pending-[\w-]+[^{]*\{[^}]*\}/g) ?? [];
    expect(rules.length, 'the beat should be defined in globals.css').toBeGreaterThan(0);
    for (const rule of rules) {
      expect(rule, `a confirmation beat must be finite:\n${rule}`).not.toMatch(/infinite/);
    }
    // Finite also means it ENDS in the resting state: every staggered step
    // needs a fill mode, or it flashes at its pre-animation value first.
    const stepped = rules.filter((r) => /animation-delay|animation:[^;]*\dms\s+\S+\s+\d/.test(r));
    for (const rule of stepped) {
      expect(rule, `a delayed step needs a fill mode:\n${rule}`).toMatch(/both|backwards/);
    }
  });
});
