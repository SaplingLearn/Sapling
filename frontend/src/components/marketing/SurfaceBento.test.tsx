// @vitest-environment jsdom
/**
 * The bento's contract (#344 step 2).
 *
 * The brand guide's hard anti-pattern is a landing grid of "bubble panel: icon
 * + heading + body". The defence is structural, not stylistic: every tile must
 * mount a real recreated product surface. So these tests assert on the four
 * surfaces being present and on what they contain — a tutor exchange, a note
 * with linked concepts, a room with messages, a gradebook row with an actual
 * grade — rather than on four boxes existing.
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';

import SurfaceBento from './SurfaceBento';
import { TIER_COLOR } from './graph/courseGraphs';

afterEach(cleanup);

function renderBento() {
  return render(
    <div className="landing-page">
      <SurfaceBento />
    </div>,
  );
}

/** The four shipped screens the spec names, in the order they are laid out. */
const TILES = ['tutor', 'notes', 'rooms', 'gradebook'] as const;

describe('SurfaceBento', () => {
  it('renders all four product surfaces', () => {
    renderBento();
    for (const t of TILES) {
      expect(screen.getByTestId(`landing-surface-${t}`), t).toBeInTheDocument();
    }
  });

  it('gives each tile its own span class so the grid stays asymmetric', () => {
    const { container } = renderBento();
    for (const t of TILES) {
      expect(container.querySelector(`.landing-bento-tile--${t}`), t).toBeTruthy();
    }
  });

  it('labels every surface with the approved product vocabulary, in Title Case', () => {
    renderBento();
    const titles = Array.from(document.querySelectorAll('.landing-surface-title')).map(
      (el) => el.textContent,
    );
    // "Tutor", never "Chat Tutor"; "Notetaker", never "Notes"/"AI Notes".
    expect(titles).toEqual(['Tutor', 'Notetaker', 'Study Rooms', 'Gradebook']);
  });

  it('shows a real tutor exchange, not a description of one', () => {
    renderBento();
    const tile = screen.getByTestId('landing-surface-tutor');
    // A back-and-forth, not a single canned answer: the student asks, the
    // tutor hands back a matrix to try, the student works it out.
    expect(tile.querySelectorAll('.landing-surface-bubble').length).toBeGreaterThanOrEqual(4);
    expect(tile.querySelectorAll('.landing-surface-bubble.is-student').length).toBeGreaterThan(1);
    expect(tile.querySelectorAll('.landing-surface-bubble.is-tutor').length).toBeGreaterThan(1);
  });

  it('shows a real note with concepts linked to the graph', () => {
    renderBento();
    const tile = screen.getByTestId('landing-surface-notes');
    expect(tile.querySelector('.landing-surface-notetitle')).toBeTruthy();
    expect(tile.querySelectorAll('.landing-surface-linkrow').length).toBeGreaterThanOrEqual(3);
  });

  it('shows a real room with an invite code and messages from more than one person', () => {
    renderBento();
    const tile = screen.getByTestId('landing-surface-rooms');
    expect(within(tile).getByText('MA242-7QK')).toBeInTheDocument();
    expect(tile.querySelectorAll('.landing-surface-bubble').length).toBeGreaterThanOrEqual(3);
    // At least one incoming turn carries a sender name — the shipped panel's
    // shape, and the thing that makes it read as a room rather than a chat.
    expect(tile.querySelectorAll('.landing-surface-sender').length).toBeGreaterThan(0);
  });

  it('shows real gradebook rows carrying actual grades', () => {
    renderBento();
    const tile = screen.getByTestId('landing-surface-gradebook');
    const rows = tile.querySelectorAll('.landing-surface-gradebookrow');
    expect(rows.length).toBeGreaterThanOrEqual(3);
    // Points earned / possible, which is what makes it a gradebook.
    expect(tile).toHaveTextContent('18');
    expect(tile).toHaveTextContent('/ 20');
    expect(within(tile).getByText('A−')).toBeInTheDocument();
  });

  /**
   * Colour communicates STATE. Every mastery mark on the page must come from
   * `TIER_COLOR` — the same map the knowledge-graph section paints its nodes
   * with — so the landing never advertises a palette the product doesn't use.
   * A raw hex here (the bug `courseGraphs.ts` already had once) fails this.
   */
  it('paints every status mark with a canonical --state-* token', () => {
    renderBento();
    const allowed = new Set(Object.values(TIER_COLOR));
    const dots = Array.from(document.querySelectorAll('.landing-surface-dot'));
    expect(dots.length).toBeGreaterThan(0);
    for (const d of dots) {
      const bg = (d as HTMLElement).style.background;
      expect(allowed.has(bg), `unexpected status colour: ${bg}`).toBe(true);
    }
  });

  it('ships no icon-over-heading tiles: no tile has a bare interactive control', () => {
    const { container } = renderBento();
    expect(container.querySelectorAll('button, input, textarea')).toHaveLength(0);
  });
});
