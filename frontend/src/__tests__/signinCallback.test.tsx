/**
 * Tests for app/signin/callback/page.tsx
 *
 * Covers the new error branches added to the OAuth callback handler:
 * - Successful session → redirect to /dashboard
 * - 403 from session API → redirect to /pending
 * - Other failures from session API → inline error
 * - Network errors → inline error
 * - Missing user_id/name params → inline error
 * - Missing is_approved param → inline error (not a /pending redirect)
 * - Explicit is_approved=false → /pending redirect
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';

const replace = jest.fn();
const setActiveUser = jest.fn();
const confirmApproved = jest.fn();
let searchParams = new URLSearchParams();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => searchParams,
}));

jest.mock('@/context/UserContext', () => ({
  useUser: () => ({ setActiveUser, confirmApproved }),
}));

import CallbackPage from '@/app/signin/callback/page';

beforeEach(() => {
  jest.clearAllMocks();
  searchParams = new URLSearchParams();
  global.fetch = jest.fn();
});

afterEach(() => {
  // @ts-expect-error allow cleanup
  delete global.fetch;
});

function setParams(params: Record<string, string>) {
  searchParams = new URLSearchParams(params);
}

describe('signin/callback page', () => {
  it('redirects to /dashboard on a successful session', async () => {
    setParams({ user_id: 'u1', name: 'Ada', is_approved: 'true' });
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, status: 200 });

    render(<CallbackPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(setActiveUser).toHaveBeenCalledWith('u1', 'Ada', '');
    expect(confirmApproved).toHaveBeenCalled();
  });

  it('redirects to /pending when session API returns 403', async () => {
    setParams({ user_id: 'u1', name: 'Ada', is_approved: 'true' });
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 403 });

    render(<CallbackPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/signin?error=not_approved'));
    expect(confirmApproved).not.toHaveBeenCalled();
  });

  it('shows an inline error when session API returns a non-403 failure', async () => {
    setParams({ user_id: 'u1', name: 'Ada', is_approved: 'true' });
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 500 });

    render(<CallbackPage />);

    expect(await screen.findByText(/unable to complete sign-in/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('shows an inline error when the session fetch rejects', async () => {
    setParams({ user_id: 'u1', name: 'Ada', is_approved: 'true' });
    (global.fetch as jest.Mock).mockRejectedValue(new Error('network down'));

    render(<CallbackPage />);

    expect(await screen.findByText(/unable to reach the server/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('shows an inline error when user_id is missing', async () => {
    setParams({ name: 'Ada', is_approved: 'true' });

    render(<CallbackPage />);

    expect(await screen.findByText(/sign-in failed/i)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it('shows an inline error when is_approved is missing entirely', async () => {
    setParams({ user_id: 'u1', name: 'Ada' });

    render(<CallbackPage />);

    expect(await screen.findByText(/sign-in failed/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('redirects to /pending when is_approved is explicitly "false"', async () => {
    setParams({ user_id: 'u1', name: 'Ada', is_approved: 'false' });

    render(<CallbackPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/signin?error=not_approved'));
  });

  it('redirects to /pending when error=not_approved is set', async () => {
    setParams({ error: 'not_approved' });

    render(<CallbackPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/signin?error=not_approved'));
  });
});
