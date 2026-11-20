// @vitest-environment jsdom

import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MarkdownChat } from './MarkdownChat';

describe('patched KaTeX in the actual tutor markdown pipeline', () => {
  it('renders inline/display math, source macros, chemistry and prose together', () => {
    const { container } = render(<MarkdownChat>{String.raw`A value in $\R$ and water $\ce{H2O}$.

$$
\frac{1}{2} + \sqrt{4}
$$

**Keep the explanation.**`}</MarkdownChat>);
    expect(screen.getByText('Keep the explanation.')).toBeInTheDocument();
    expect(container.querySelectorAll('.katex').length).toBe(3);
    expect(container.querySelector('.katex-display .katex-base')).not.toBeNull();
    expect(container.querySelectorAll('math').length).toBe(3);
    expect(container.querySelector('.katex-error')).toBeNull();
  });

  it('does not produce an unsafe math link even with inherited prototype trust', () => {
    const previous = Object.getOwnPropertyDescriptor(Object.prototype, 'trust');
    Object.defineProperty(Object.prototype, 'trust', { value: true, writable: true, configurable: true });
    try {
      const { container } = render(<MarkdownChat>{String.raw`$\href{javascript:alert(1)}{click}$`}</MarkdownChat>);
      expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
      expect(container.querySelector('a')).toBeNull();
      expect(container.querySelector('math')).not.toBeNull();
    } finally {
      if (previous) Object.defineProperty(Object.prototype, 'trust', previous);
      else Reflect.deleteProperty(Object.prototype, 'trust');
    }
  });

  it('retains code fences and mathematical Mermaid labels', async () => {
    const { default: mermaid } = await import('mermaid');
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', forceLegacyMathML: true });
    // jsdom does not provide SVG layout; this verifies the real diagram parser,
    // not browser rendering/geometry. The separate markdown cases render KaTeX.
    expect(await mermaid.parse('flowchart LR\n A["$$\\frac{1}{2}$$"] --> B[Done]')).toBeTruthy();
    const { container } = render(<MarkdownChat>{'```python\nprint(1 + 2)\n```'}</MarkdownChat>);
    expect(container.querySelector('code.language-python')).not.toBeNull();
  });
});
