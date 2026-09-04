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
 *
 * Dismissal is also two-phase: the parent closes by unmounting this component,
 * so `onClose` is deferred by the exit animation's duration. Calling it
 * straight away would unmount mid-animation and there would be no exit at all.
 * Every dismissal goes through that one path, which is what these pin.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
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

  it('closes on a press that starts on the backdrop, once the exit ends', () => {
    vi.useFakeTimers();
    try {
      const onClose = open();
      const panel = screen.getByRole('dialog');
      fireEvent.pointerDown(panel.parentElement!);
      // Deferred: unmounting here would cut the exit animation off.
      expect(onClose).not.toHaveBeenCalled();
      expect(panel.className).toContain('cp-lightbox-panel--closing');
      act(() => { vi.advanceTimersByTime(200); });
      expect(onClose).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does NOT close on a press that starts inside the panel', () => {
    const onClose = open();
    fireEvent.pointerDown(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape, through the same exit path', () => {
    vi.useFakeTimers();
    try {
      const onClose = open();
      const panel = screen.getByRole('dialog');
      fireEvent.keyDown(panel, { key: 'Escape' });
      expect(panel.className).toContain('cp-lightbox-panel--closing');
      act(() => { vi.advanceTimersByTime(200); });
      expect(onClose).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('closes on the close button', () => {
    vi.useFakeTimers();
    try {
      const onClose = open();
      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      act(() => { vi.advanceTimersByTime(200); });
      expect(onClose).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('fires onClose exactly once however long the page lives after', () => {
    vi.useFakeTimers();
    try {
      const onClose = open();
      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      act(() => { vi.advanceTimersByTime(5000); });
      expect(onClose).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
