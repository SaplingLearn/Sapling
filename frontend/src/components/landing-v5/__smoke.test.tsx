// @vitest-environment jsdom
// TEMPORARY smoke check — deleted after running. Not part of the suite.
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Gallery } from './Gallery';
import { Faq } from './Faq';
import { Navbar } from './Navbar';
import { NAV_LIGHT } from './navTheme';
import { CardsDemo } from './lab/CardsDemo';
import { CalendarDemo } from './lab/CalendarDemo';
import { QuizDemo } from './lab/QuizDemo';
import { GuideDemo } from './lab/GuideDemo';
import { NotesDemo } from './lab/NotesDemo';
import { GUIDES } from './lab/labData';
import { galIndexOf, GAL } from '@/lib/landing/content';

describe('contract', () => {
  it('galIndexOf resolves every kind to its GAL slot', () => {
    expect(galIndexOf('quiz')).toBe(0);
    expect(galIndexOf('tutor')).toBe(7);
    GAL.forEach((c, i) => expect(galIndexOf(c.kind)).toBe(i));
  });
});

describe('gallery keyboard', () => {
  it('opens a card with Enter and Space, ghosts stay inert', () => {
    const onOpen = vi.fn();
    const ref = { current: null } as React.RefObject<HTMLDivElement | null>;
    render(<Gallery trackARef={ref} trackBRef={{ current: null }} onOpen={onOpen} />);
    const cards = document.querySelectorAll('[data-tk]');
    const real = Array.from(cards).filter((c) => !c.hasAttribute('aria-hidden'));
    const ghosts = Array.from(cards).filter((c) => c.hasAttribute('aria-hidden'));
    expect(real.length).toBe(8);
    expect(ghosts.length).toBe(8);
    real.forEach((c) => { expect(c.getAttribute('tabindex')).toBe('0'); expect(c.getAttribute('role')).toBe('button'); });
    ghosts.forEach((c) => { expect(c.getAttribute('tabindex')).toBeNull(); expect(c.getAttribute('role')).toBeNull(); });

    fireEvent.keyDown(real[0], { key: 'Enter' });
    fireEvent.keyDown(real[1], { key: ' ' });
    expect(onOpen.mock.calls.map((c) => c[0])).toEqual([0, 1]);

    expect(document.querySelectorAll('[role="group"][aria-label]').length).toBe(2);
  });
});

describe('faq', () => {
  it('links to /faq and wires aria-controls, closed panels are inert', () => {
    render(<Faq openFaq={0} onToggle={() => {}} />);
    expect(screen.getByText('Read the full FAQ').getAttribute('href')).toBe('/faq');
    const triggers = document.querySelectorAll('button[aria-controls]');
    expect(triggers.length).toBe(8);
    triggers.forEach((t) => {
      const panel = document.getElementById(t.getAttribute('aria-controls')!);
      expect(panel).not.toBeNull();
      const open = t.getAttribute('aria-expanded') === 'true';
      expect(panel!.hasAttribute('inert')).toBe(!open);
    });
  });
});

describe('navbar', () => {
  it('is non-interactive before the hero mounts, and drops the fake menu roles', () => {
    const { rerender } = render(
      <Navbar navRef={{ current: null }} heroMounted={false} exploring={false} navMenuOpen={false}
        theme={NAV_LIGHT} onToggleMenu={() => {}} onCloseMenu={() => {}} onLogoClick={() => {}}
        onSignIn={() => {}} onGetStarted={() => {}} />,
    );
    const nav = document.querySelector('nav.sapling-nav') as HTMLElement;
    expect(nav.hasAttribute('inert')).toBe(true);
    expect(nav.style.visibility).toBe('hidden');
    expect(nav.style.pointerEvents).toBe('none');
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(document.querySelector('[aria-haspopup]')).toBeNull();

    rerender(
      <Navbar navRef={{ current: null }} heroMounted exploring={false} navMenuOpen={false}
        theme={NAV_LIGHT} onToggleMenu={() => {}} onCloseMenu={() => {}} onLogoClick={() => {}}
        onSignIn={() => {}} onGetStarted={() => {}} />,
    );
    expect(nav.hasAttribute('inert')).toBe(false);
    expect(nav.style.visibility).toBe('visible');
  });
});

describe('lab demos', () => {
  it('cards demo: flip is a button, and typing in a field is not a shortcut', () => {
    render(<CardsDemo />);
    const flip = screen.getByRole('button', { name: /reveal the answer/i });
    expect(flip.tagName).toBe('BUTTON');
    fireEvent.click(flip);
    expect(screen.getByRole('button', { name: /hide the answer/i })).toBeTruthy();

    // A keystroke targeting an input must not be swallowed as a card shortcut.
    const input = document.createElement('input');
    document.body.appendChild(input);
    const ev = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
    input.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    input.remove();
  });

  it('calendar demo: blanks are disabled, real days carry aria-pressed', () => {
    render(<CalendarDemo />);
    const days = Array.from(document.querySelectorAll('button')).filter((b) => b.style.minHeight === '44px');
    const blanks = days.filter((d) => (d as HTMLButtonElement).disabled);
    const real = days.filter((d) => !(d as HTMLButtonElement).disabled);
    expect(blanks.length).toBeGreaterThan(0);
    blanks.forEach((b) => expect(b.getAttribute('aria-pressed')).toBeNull());
    expect(real.length).toBeGreaterThan(20);
    real.forEach((d) => expect(d.getAttribute('aria-pressed')).toMatch(/true|false/));
    expect(real.filter((d) => d.getAttribute('aria-pressed') === 'true').length).toBe(1);
  });

  it('quiz demo: options are radios and the streak uses a functional update', () => {
    render(<QuizDemo />);
    const radios = screen.getAllByRole('radio');
    expect(radios.length).toBeGreaterThan(1);
    radios.forEach((r) => expect(r.getAttribute('aria-checked')).toBe('false'));
    fireEvent.click(radios[0]);
    expect(screen.getAllByRole('radio')[0].getAttribute('aria-checked')).toBe('true');
  });

  it('guide demo: every recent pick exists in its course exam list', () => {
    render(<GuideDemo />);
    const recents = Array.from(document.querySelectorAll('button')).filter((b) => /Midterm/.test(b.textContent || ''));
    expect(recents.length).toBeGreaterThan(0);
    // The data invariant itself, read straight off the fixture.
    expect(GUIDES['MA 242'].exams).toContain('Midterm 2 · Oct 24');
    expect(GUIDES['CS 201'].exams).toContain('Midterm 1 · Oct 17');
  });

  it('notes demo: an empty extraction does not print "1 concepts"', async () => {
    vi.useFakeTimers();
    try {
      render(<NotesDemo />);
      const body = document.querySelector('textarea')!;
      fireEvent.change(body, { target: { value: 'nothing recognisable here at all' } });
      fireEvent.click(screen.getByText(/extract concepts/i));
      await vi.advanceTimersByTimeAsync(800);
      expect(document.body.textContent).toContain('No concepts found');
      expect(document.body.textContent).not.toContain('1 concepts');
      expect(document.body.textContent).toContain('Concepts you extract are linked');
    } finally {
      vi.useRealTimers();
    }
  });
});
