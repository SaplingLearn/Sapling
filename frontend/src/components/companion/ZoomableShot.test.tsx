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
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

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
});
