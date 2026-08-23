// @vitest-environment jsdom
/**
 * The band's two load-bearing behaviours (#344 step 2).
 *
 * 1. **Alternation.** The spec's requirement is that the product surfaces
 *    alternate sides down the page. `featureBands.tsx` derives `surfaceSide`
 *    from position rather than writing it down per band, so this asserts the
 *    invariant (adjacent bands differ) instead of restating three literals —
 *    inserting a band can't silently put two surfaces in the same gutter.
 * 2. **DOM order is always copy-first.** The flip is a `grid-column` swap in
 *    CSS, never a source reorder, because the source order is what the phone
 *    layout and a screen reader get. A regression to `flex-direction:
 *    row-reverse` on the markup would pass a visual check and fail this.
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';

import FeatureBand from './FeatureBand';
import { FEATURE_BANDS } from './featureBands';

afterEach(cleanup);

/** Every band, mounted the way `page.tsx` mounts them. */
function renderAll() {
  return render(
    <div className="landing-page">
      {FEATURE_BANDS.map((b) => (
        <FeatureBand key={b.id} {...b} />
      ))}
    </div>,
  );
}

describe('featureBands', () => {
  it('carries the three bands of the material-in → practice → retention arc', () => {
    expect(FEATURE_BANDS.map((b) => b.id)).toEqual(['upload', 'quiz', 'review']);
  });

  it('alternates the surface side between consecutive bands', () => {
    for (let i = 1; i < FEATURE_BANDS.length; i++) {
      expect(
        FEATURE_BANDS[i].surfaceSide,
        `band ${FEATURE_BANDS[i].id} must not share a side with ${FEATURE_BANDS[i - 1].id}`,
      ).not.toBe(FEATURE_BANDS[i - 1].surfaceSide);
    }
  });

  it('opens on the left so the first surface sits under the graph, not beside the CTA', () => {
    expect(FEATURE_BANDS[0].surfaceSide).toBe('left');
  });

  it('addresses the student and avoids the banned marketing vocabulary', () => {
    // The brand guide bans these outright; "AI-powered" is banned as a badge.
    const banned = /leverage|empower|seamless|revolutionary|cutting-edge|synergy|ai-powered/i;
    for (const b of FEATURE_BANDS) {
      const copy = `${b.eyebrow} ${b.headline} ${b.body}`;
      expect(copy, b.id).not.toMatch(banned);
    }
  });
});

describe('FeatureBand', () => {
  it('renders each band with its eyebrow, headline, body and surface', () => {
    renderAll();
    for (const b of FEATURE_BANDS) {
      const band = screen.getByTestId(`landing-band-${b.id}`);
      expect(within(band).getByTestId(`landing-band-${b.id}-eyebrow`)).toHaveTextContent(b.eyebrow);
      expect(within(band).getByRole('heading', { level: 2 })).toHaveTextContent(b.headline);
      expect(band).toHaveTextContent(b.body);
      // The surface is a real recreation, not an empty slot.
      expect(band.querySelector('.landing-surface')).toBeTruthy();
    }
  });

  it('exposes the resolved side on the section, and matches it to the layout class', () => {
    renderAll();
    for (const b of FEATURE_BANDS) {
      const band = screen.getByTestId(`landing-band-${b.id}`);
      expect(band).toHaveAttribute('data-surface-side', b.surfaceSide);
      expect(band.querySelector(`.landing-band--surface-${b.surfaceSide}`)).toBeTruthy();
    }
  });

  it('keeps the copy before the surface in the DOM regardless of which side it renders on', () => {
    renderAll();
    for (const b of FEATURE_BANDS) {
      const grid = screen.getByTestId(`landing-band-${b.id}`).querySelector('.landing-band-grid')!;
      const kids = Array.from(grid.children);
      expect(kids[0].className, b.id).toContain('landing-band-copy');
      expect(kids[1].className, b.id).toContain('landing-band-surface');
    }
  });

  it('names each band for assistive tech via its own headline', () => {
    renderAll();
    for (const b of FEATURE_BANDS) {
      const band = screen.getByTestId(`landing-band-${b.id}`);
      expect(band).toHaveAttribute('aria-labelledby', `band-${b.id}-headline`);
      expect(band.querySelector(`#band-${b.id}-headline`)).toBeTruthy();
    }
  });

  it('ships no interactive controls — the surfaces are pictures, not widgets', () => {
    // The spec's "no per-tile buttons". It is also what makes reduced-motion /
    // IS_TEST_MODE parking a non-issue here: there is no frame but the
    // complete one.
    const { container } = renderAll();
    expect(container.querySelectorAll('button, input, textarea, a')).toHaveLength(0);
  });
});
