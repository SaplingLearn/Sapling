// @vitest-environment jsdom
/**
 * The pinned field's sticky box must match its act's stage.
 *
 * This is a coupling between two files that nothing else enforces, and
 * getting it wrong is invisible in review: both shapes look like reasonable
 * ways to pin a decorative layer. A `sticky; top:0; height:0` box and a
 * `sticky; top:0; height:100vh` box pin identically — they only diverge on
 * RELEASE, because a sticky element stops sticking once its containing
 * block's bottom reaches its own height above the fold. Zero-height releases
 * a full viewport later, so for the last 100vh of every act the copy scrolled
 * away while the clusters stayed welded to the top of the screen. Measured at
 * 882px of divergence through act-tutor before the fix.
 *
 * jsdom has no sticky positioning, so this asserts the geometry rather than
 * the behaviour; e2e/landing-drag-field.spec.ts measures what it actually
 * does in a browser. Both are needed — this one names the invariant, that one
 * proves it holds.
 */
import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ActIngest } from './ActIngest';
import { ActTutor } from './ActTutor';
import { DragField } from './DragField';
import { Faq } from './Faq';

/** The act's stage: the sticky child of the section that carries the copy. */
function stageOf(section: HTMLElement): HTMLElement {
  const stage = Array.from(section.children).find(
    (el) => el instanceof HTMLElement
      && el.style.position === 'sticky'
      && !el.querySelector('[data-dragnode]')
      && !el.classList.contains('drag-field'),
  );
  expect(stage, 'every act should have a sticky stage').toBeTruthy();
  return stage as HTMLElement;
}

function fieldOf(container: HTMLElement): HTMLElement {
  const field = container.querySelector<HTMLElement>('.drag-field');
  expect(field, 'every act should carry a drag field').toBeTruthy();
  return field!;
}

const ACTS: Array<[name: string, render: () => HTMLElement]> = [
  ['act-tutor', () => render(
    <ActTutor carouselRef={React.createRef()} tutorMode={0} onSetMode={() => {}} />,
  ).container],
  ['act-ingest', () => render(
    <ActIngest ingestSceneRef={React.createRef()} ingestStageRef={React.createRef()} />,
  ).container],
];

describe.each(ACTS)('%s', (_name, renderAct) => {
  it('pins its drag field on exactly the stage\'s sticky geometry', () => {
    const container = renderAct();
    const section = container.querySelector('section')!;
    const stage = stageOf(section);
    const field = fieldOf(container);

    // Same three properties, same values. If the stage's height ever changes,
    // this fails and the field has to follow it.
    expect(field.style.position).toBe(stage.style.position);
    expect(field.style.top).toBe(stage.style.top);
    expect(field.style.height).toBe(stage.style.height);
    expect(field.style.height).toBe('100vh');
  });

  it('keeps the field out of the act\'s flow', () => {
    const container = renderAct();
    const field = fieldOf(container);
    const wrapper = field.parentElement!;

    // A 100vh sticky box in flow would push the stage down by a viewport.
    // The absolute wrapper is what buys the geometry without the shove.
    expect(wrapper.style.position).toBe('absolute');
    expect(wrapper.style.inset).toBe('0px');
    expect(field.parentElement?.parentElement?.tagName).toBe('SECTION');
  });

  it('puts the field before the stage, under the copy', () => {
    const container = renderAct();
    const section = container.querySelector('section')!;
    const wrapper = fieldOf(container).parentElement!;
    expect(Array.from(section.children).indexOf(wrapper))
      .toBeLessThan(Array.from(section.children).indexOf(stageOf(section)));
  });
});

describe('static sections', () => {
  it.each(['faq', 'newsletter', 'cta'] as const)(
    'gives %s a plain absolute field, never the 100vh layer',
    (section) => {
      const { container } = render(<DragField section={section} />);
      const field = fieldOf(container);
      // An absolutely positioned 100vh child extends the document's
      // scrollHeight, which on the last section is a viewport of dead scroll
      // below the footer.
      expect(field.style.position).toBe('absolute');
      expect(field.style.inset).toBe('0px');
      expect(field.style.height).toBe('');
    },
  );

  it('welds faq\'s clusters to the copy that pins inside it', () => {
    const { container } = render(<DragField section="faq" />);
    // The section's own rect is the right box for PLACING these clusters and
    // the wrong one for MOVING them: the question column pins 375px inside a
    // section that never stops scrolling. Naming it is what closes the gap.
    expect(fieldOf(container).dataset.dragTrack).toBe('[data-drag-anchor="faq"]');
  });

  it.each(['newsletter', 'cta'] as const)(
    'leaves %s untracked, since nothing pins inside it',
    (section) => {
      const { container } = render(<DragField section={section} />);
      expect(fieldOf(container).dataset.dragTrack).toBeUndefined();
    },
  );

  it('finds exactly one sticky column behind faq\'s selector', () => {
    // The coupling this file exists to catch, in its static-section form:
    // DragField names a selector, Faq owns the element, and nothing else
    // fails if the two drift apart.
    const { container } = render(<Faq openFaq={-1} onToggle={() => {}} />);
    const tracked = container.querySelectorAll<HTMLElement>('[data-drag-anchor="faq"]');
    expect(tracked).toHaveLength(1);
    expect(tracked[0].style.position).toBe('sticky');
    // A static tracked element would make the whole mechanism a no-op.
    expect(tracked[0].style.top).toBe('110px');
  });

  it('still hands every cluster to the sim', () => {
    const { container } = render(<DragField section="faq" />);
    const clusters = container.querySelectorAll('[data-dragnode]');
    expect(clusters.length).toBeGreaterThan(0);
    clusters.forEach((cluster) => {
      // The bindings engine/sim.ts resolves by: rings, and a glow before and
      // a label after each one.
      const rings = cluster.querySelectorAll('[data-sim]');
      expect(rings.length).toBeGreaterThan(0);
      rings.forEach((ring) => {
        expect(ring.previousElementSibling?.tagName).toBe('circle');
        expect(ring.nextElementSibling?.tagName).toBe('text');
      });
    });
  });
});
