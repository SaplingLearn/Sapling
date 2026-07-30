// @vitest-environment jsdom
/**
 * #172: a dedicated app/global-error.tsx must exist (rendering its own
 * <html>/<body> around the branded fallback), and the root segment boundary
 * error.tsx must stop masquerading as "GlobalError".
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import GlobalError from './global-error';
import RootError from './error';

afterEach(cleanup);

describe('#172 global-error boundary', () => {
  it('renders the branded fallback with a recovery action', () => {
    // React warns about <html> nesting inside the jsdom container; the markup
    // itself still renders, which is what we assert on.
    render(<GlobalError error={new Error('provider init failed')} reset={() => {}} />);
    expect(screen.getByText(/we hit a snag/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
  });

  it('the segment boundary is no longer named GlobalError', () => {
    expect(RootError.name).toBe('RootError');
    expect(GlobalError.name).toBe('GlobalError');
  });
});
