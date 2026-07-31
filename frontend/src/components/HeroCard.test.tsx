// @vitest-environment jsdom
/**
 * #288 — the hero surface is shared, and stays shared.
 *
 * The gradient behind the sign-in and beta modals was pasted at five sites
 * and had already drifted at four of them (three shadow alphas, two radii,
 * one missing inset) while the --surface-hero tokens sat unused. These tests
 * pin the contract that replaced it: one component, one pair of classes, and
 * no literal left anywhere to drift from.
 */
import React from 'react';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import { HeroCard } from './HeroCard';

const SRC = path.resolve(__dirname, '..');
const GLOBALS = path.join(SRC, 'app/globals.css');

/** The literal that used to be inlined at all five sites. */
const GRADIENT = 'linear-gradient(145deg, #d5e8d8 0%, #e8f0e3 45%, #f0ebe0 100%)';

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    // Application source only — a test is allowed to name the literal it
    // guards against (this file does, right above).
    else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

afterEach(cleanup);

describe('#288 hero surface', () => {
  it('carries both classes and forwards className, props and ref', () => {
    const ref = React.createRef<HTMLDivElement>();
    render(
      <HeroCard ref={ref} className="modal-card-in" data-testid="probe" role="dialog">
        body
      </HeroCard>,
    );
    const el = screen.getByTestId('probe');
    expect(el.className.split(/\s+/)).toEqual(
      expect.arrayContaining(['card', 'card--hero', 'modal-card-in']),
    );
    // The variant has to sit alongside .card, not replace it.
    expect(el.className).toContain('card');
    expect(el.getAttribute('role')).toBe('dialog');
    expect(ref.current).toBe(el);
  });

  it('renders without a className', () => {
    render(<HeroCard data-testid="bare">body</HeroCard>);
    expect(screen.getByTestId('bare').className).toBe('card card--hero');
  });

  it('leaves no inlined copy of the gradient anywhere in src/', () => {
    const offenders = walk(SRC)
      .filter((f) => fs.readFileSync(f, 'utf8').includes(GRADIENT))
      .map((f) => path.relative(SRC, f));
    // globals.css is not walked (only .ts/.tsx), so the token definition and
    // the class fallbacks are correctly out of scope here.
    expect(
      offenders,
      `the hero gradient must come from .card--hero / .hero-surface, not a literal:\n${offenders.join('\n')}`,
    ).toEqual([]);
  });

  it('gives both hero rules a literal fallback, so an out-of-scope mount still paints', () => {
    const css = fs.readFileSync(GLOBALS, 'utf8');
    // --surface-hero is scoped to .public-surface/.landing-page. A hero card
    // mounted outside that subtree resolves the var to nothing, so the
    // fallback is the only thing standing between it and a transparent card.
    const background = css.match(/\.hero-surface,\s*\n\.card--hero\s*\{[^}]*\}/);
    expect(background, '.hero-surface/.card--hero background rule should exist').not.toBeNull();
    expect(background![0]).toContain('var(--surface-hero,');
    expect(background![0]).toContain(GRADIENT);

    const shadow = css.match(/\.card--hero\s*\{[^}]*box-shadow[^}]*\}/);
    expect(shadow, '.card--hero box-shadow rule should exist').not.toBeNull();
    expect(shadow![0]).toContain('var(--surface-hero-shadow,');
    // The fallback must include the inset half, or the token and the fallback
    // render as two different surfaces.
    expect(shadow![0]).toMatch(/inset 0 0 0 1px/);
  });
});
