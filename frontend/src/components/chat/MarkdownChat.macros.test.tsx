// @vitest-environment jsdom

import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MarkdownChat } from './MarkdownChat';

// Z32: KaTeX writes \gdef / \global definitions into the macros object it is
// handed. One message's definition must never change how math renders in any
// other message (the tutor, the quiz Ask panel, flashcards — and a classmate's
// passage served verbatim as a hint), so every render gets its own macros.
describe('a message cannot redefine math for the messages after it', () => {
  it('a \\gdef in one message leaves \\frac in the next one alone', () => {
    render(<MarkdownChat>{String.raw`Notation used in this handout: $\gdef\frac#1#2{#2/#1}$`}</MarkdownChat>);
    const { container } = render(<MarkdownChat>{String.raw`Half of it: $\frac{1}{2}$`}</MarkdownChat>);
    expect(container.querySelector('mfrac')).not.toBeNull();
    expect(container.querySelector('.katex-error')).toBeNull();
  });

  it('a self-referencing \\gdef of a shortcut does not break the shortcut elsewhere', () => {
    render(<MarkdownChat>{String.raw`$\gdef\R{\R\R}$`}</MarkdownChat>);
    const { container } = render(<MarkdownChat>{String.raw`A value in $\R$.`}</MarkdownChat>);
    expect(container.querySelector('.katex-error')).toBeNull();
    expect(container.querySelector('.katex')).not.toBeNull();
  });

  it('the source shortcuts still work in every message', () => {
    const { container } = render(<MarkdownChat>{String.raw`$\R$ and $\norm{x}$`}</MarkdownChat>);
    expect(container.querySelectorAll('.katex').length).toBe(2);
    expect(container.querySelector('.katex-error')).toBeNull();
  });
});
