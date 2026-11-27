// @vitest-environment jsdom

import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MarkdownChat } from './MarkdownChat';

// Z32: KaTeX writes \gdef / \global definitions into the macros object it is
// handed. Class material the learning loop serves verbatim (an H2 hint is a
// classmate's passage; its transcript renders "inert", Z08) must never change
// how math renders in any other message of the tab — the tutor, the quiz Ask
// panel, flashcards — nor be changed by one: every inert render gets its own
// copy of the pristine shortcut table. A "rich" render keeps main's shared
// table (the loop-off app renders exactly as on main).
describe('class material cannot redefine math for other messages', () => {
  it('a \\gdef in an inert render leaves \\frac alone everywhere after it', () => {
    render(<MarkdownChat profile="inert">{String.raw`Notation used in this handout: $\gdef\frac#1#2{#2/#1}$`}</MarkdownChat>);
    for (const profile of ['rich', 'inert'] as const) {
      const { container } = render(<MarkdownChat profile={profile}>{String.raw`Half of it: $\frac{1}{2}$`}</MarkdownChat>);
      expect(container.querySelector('mfrac')).not.toBeNull();
      expect(container.querySelector('.katex-error')).toBeNull();
    }
  });

  it('a self-referencing \\gdef of a shortcut breaks the shortcut nowhere else', () => {
    render(<MarkdownChat profile="inert">{String.raw`$\gdef\R{\R\R}$`}</MarkdownChat>);
    for (const profile of ['rich', 'inert'] as const) {
      const { container } = render(<MarkdownChat profile={profile}>{String.raw`A value in $\R$.`}</MarkdownChat>);
      expect(container.querySelector('.katex-error')).toBeNull();
      expect(container.querySelector('.katex')).not.toBeNull();
    }
  });

  it('the source shortcuts work in every render', () => {
    for (const profile of ['rich', 'inert'] as const) {
      const { container } = render(<MarkdownChat profile={profile}>{String.raw`$\R$ and $\norm{x}$`}</MarkdownChat>);
      expect(container.querySelectorAll('.katex').length).toBe(2);
      expect(container.querySelector('.katex-error')).toBeNull();
    }
  });
});
