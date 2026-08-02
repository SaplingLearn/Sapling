// @vitest-environment jsdom
/**
 * #188: the (shell) segment must ship a loading.tsx so route transitions
 * paint a skeleton instead of a blank <main>.
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import ShellLoading from './(shell)/loading';

afterEach(cleanup);

describe('#188 shell loading skeleton', () => {
  it('renders an immediate skeleton', () => {
    render(<ShellLoading />);
    expect(screen.getByTestId('shell-loading')).toBeTruthy();
  });
});
