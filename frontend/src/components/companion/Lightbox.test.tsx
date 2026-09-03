// @vitest-environment jsdom
/**
 * The lightbox closes on the three gestures a viewer will actually try, and
 * NOT on the one that looks like a fourth.
 *
 * Click-out is the interesting case. The obvious implementation puts onClick
 * on the backdrop, which closes the viewer when a drag STARTS on the image and
 * releases on the backdrop — selecting the image, or flinging it — because the
 * click event fires on the common ancestor. Pressing on the panel and
 * releasing outside it is a normal gesture and must not dismiss anything, so
 * the backdrop listens on pointerdown and checks the target is itself.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Lightbox } from './Lightbox';

afterEach(cleanup);

function open(onClose = vi.fn()) {
  render(
    <Lightbox
      open
      onClose={onClose}
      src="/gallery/shot-tree.png"
      alt="The knowledge graph screen in Sapling"
      title="Knowledge graph"
      caption="The whole course as nodes and edges."
      eyebrow="/tree"
    />,
  );
  return onClose;
}

describe('Lightbox', () => {
  it('renders the image and its caption when open', () => {
    open();
    expect(screen.getByRole('dialog', { name: 'Knowledge graph' })).toBeTruthy();
    expect(screen.getByAltText('The knowledge graph screen in Sapling')).toBeTruthy();
    expect(screen.getByText('The whole course as nodes and edges.')).toBeTruthy();
  });

  it('renders nothing when closed', () => {
    const onClose = vi.fn();
    render(<Lightbox open={false} onClose={onClose} src="/x.png" alt="x" title="x" />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes on a press that starts on the backdrop', () => {
    const onClose = open();
    const backdrop = screen.getByRole('dialog').parentElement!;
    fireEvent.pointerDown(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does NOT close on a press that starts inside the panel', () => {
    const onClose = open();
    fireEvent.pointerDown(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape', () => {
    const onClose = open();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('closes on the close button', () => {
    const onClose = open();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
