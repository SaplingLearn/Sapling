// @vitest-environment jsdom
/**
 * The client boundary around an expandable screenshot.
 *
 * This component exists so /wiki can have the interaction at all: that page is
 * a server component (it exports `metadata`), so it cannot hold the open state
 * itself. The boundary is drawn around the one element that needs it rather
 * than converting a whole reference page.
 *
 * The property worth pinning is that a closed shot mounts NO portal — twelve
 * of these on /gallery must not be twelve overlays sitting in the document.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ZoomableShot } from './ZoomableShot';

afterEach(cleanup);

function shot() {
  render(
    <ZoomableShot
      src="/gallery/shot-tree.png"
      alt="The knowledge graph screen in Sapling"
      title="Knowledge graph"
      caption="Nodes and edges."
      route="/tree"
    />,
  );
}

describe('ZoomableShot', () => {
  it('renders a labelled button and no overlay until it is clicked', () => {
    shot();
    expect(screen.getByRole('button', { name: 'Expand Knowledge graph' })).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the route badge', () => {
    shot();
    expect(screen.getByText('/tree')).toBeTruthy();
  });

  it('opens the lightbox on click, carrying its own metadata through', () => {
    shot();
    fireEvent.click(screen.getByRole('button', { name: 'Expand Knowledge graph' }));
    const dialog = screen.getByRole('dialog', { name: 'Knowledge graph' });
    expect(dialog).toBeTruthy();
    expect(screen.getByAltText('The knowledge graph screen in Sapling')).toBeTruthy();
    expect(screen.getByText('Nodes and edges.')).toBeTruthy();
  });
  /**
   * Reopening. The Lightbox instance is NOT unmounted on close here — this
   * component always renders it and it returns null while closed — so its exit
   * state has to be reset when it opens again. Left set, the exit effect fires
   * on the first render of the second open and closes it ~EXIT_MS later with
   * no input from anyone.
   *
   * Nothing covered this before: every other test opens exactly once.
   */
  it('stays open when reopened after a close', () => {
    vi.useFakeTimers();
    try {
      shot();
      const trigger = screen.getByRole('button', { name: 'Expand Knowledge graph' });

      fireEvent.click(trigger);
      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      act(() => { vi.advanceTimersByTime(400); });
      expect(screen.queryByRole('dialog')).toBeNull();

      fireEvent.click(trigger);
      expect(screen.getByRole('dialog')).toBeTruthy();
      // Well past the exit duration: it must still be there.
      act(() => { vi.advanceTimersByTime(600); });
      expect(screen.queryByRole('dialog')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });
});
