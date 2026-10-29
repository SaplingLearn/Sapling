// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GradescopeSyncModal } from './GradescopeSyncModal';
import { getGradescopeStatus, listGradescopeCourses, listGradescopeLinks, syncGradescopeCourse, connectGradescopeViaBuSso, saveGradescopeCredentials } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  getGradescopeStatus: vi.fn(), saveGradescopeCredentials: vi.fn(),
  connectGradescopeViaBuSso: vi.fn(), listGradescopeCourses: vi.fn(),
  listGradescopeLinks: vi.fn(), linkGradescopeCourse: vi.fn(),
  syncGradescopeCourse: vi.fn(), deleteGradescopeCredentials: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(listGradescopeCourses).mockResolvedValue({ courses: [{
    id: '123', name: 'CS101', full_name: 'Intro to CS', semester: 'Fall', year: '2025', num_assignments: '1',
  }] });
  vi.mocked(getGradescopeStatus).mockResolvedValue({
    has_credentials: true, auth_mode: 'cookies', last_synced_at: null,
  });
  vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [{
    id: 'link', sapling_course_id: 'c1', gradescope_course_id: '123', last_synced_at: null,
  }] });
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe('Gradescope sync results', () => {
  it('returns to sign-in when a session expires during sync', async () => {
    vi.mocked(syncGradescopeCourse).mockRejectedValue(Object.assign(new Error('{"detail":"Gradescope session expired."}'), { status: 401 }));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('Connect Gradescope')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Gradescope session expired.');
  });

  it('opens an already-linked course without a live Gradescope login', async () => {
    // Every course listing is a full Gradescope login + scrape on a 10/5min
    // budget; Sync logs in anyway, so opening the dialog must not.
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    expect(listGradescopeCourses).not.toHaveBeenCalled();
  });

  it('lets an existing link select a different course without deleting credentials', async () => {
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Change course' }));
    expect(await screen.findByText('Pick the matching Gradescope course')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /CS101/ })).toBeInTheDocument();
    expect(listGradescopeCourses).toHaveBeenCalledTimes(1);
  });

  it('sends an ambiguous sync to the course picker instead of retrying it', async () => {
    vi.mocked(syncGradescopeCourse).mockRejectedValue(Object.assign(
      new Error('{"detail":"Multiple Gradescope links match this course. Select a semester and reconnect the course."}'),
      { status: 409 },
    ));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('Pick the matching Gradescope course')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Multiple Gradescope links match this course.');
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
    expect(syncGradescopeCourse).toHaveBeenCalledTimes(1);
  });

  it('asks for reconnection when saved credentials no longer authenticate', async () => {
    vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [] });
    vi.mocked(listGradescopeCourses).mockRejectedValue(Object.assign(new Error('{"detail":"Session expired"}'), { status: 401 }));
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    expect(await screen.findByText('Connect Gradescope')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Session expired');
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
  });

  it('opens the sign-in choices directly when reconnecting an existing account', async () => {
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    expect(await screen.findByText('Connect Gradescope')).toBeInTheDocument();
    expect(getGradescopeStatus).not.toHaveBeenCalled();
  });

  it('shows partial failure and lets the user retry in the same semester', async () => {
    vi.mocked(syncGradescopeCourse)
      .mockResolvedValueOnce({ inserted: 1, updated: 0, skipped: 0, failed: 1 })
      .mockResolvedValueOnce({ inserted: 1, updated: 1, skipped: 0, failed: 0 });
    const onSynced = vi.fn();
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" semester="Fall 2025" onClose={vi.fn()} onSynced={onSynced} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('Sync needs attention')).toBeInTheDocument();
    expect(screen.queryByText('Sync complete')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry sync' }));
    expect(await screen.findByText('Sync complete')).toBeInTheDocument();
    expect(listGradescopeLinks).toHaveBeenCalledWith('u1', 'Fall 2025');
    expect(syncGradescopeCourse).toHaveBeenLastCalledWith('u1', 'c1', 'Fall 2025');
    expect(onSynced).toHaveBeenCalledTimes(2);
  });

  it('surfaces a failed import without displaying raw JSON or success', async () => {
    vi.mocked(syncGradescopeCourse).mockRejectedValue(new Error('{"detail":"No assignments could be saved."}'));
    const onSynced = vi.fn();
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} onSynced={onSynced} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No assignments could be saved.'));
    expect(screen.getByRole('alert').textContent).not.toContain('{');
    expect(onSynced).not.toHaveBeenCalled();
  });

  it('retries a temporary outage without asking for replacement credentials', async () => {
    vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [] });
    vi.mocked(listGradescopeCourses).mockRejectedValueOnce(Object.assign(new Error('Gradescope unavailable'), { status: 502 }));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Retry connection' }));
    expect(await screen.findByText('Pick the matching Gradescope course')).toBeInTheDocument();
    expect(saveGradescopeCredentials).not.toHaveBeenCalled();
  });

  it('ignores a previous semester lookup after the dialog changes semester', async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof listGradescopeLinks>>) => void;
    vi.mocked(listGradescopeLinks)
      .mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ links: [] });
    const onClose = vi.fn();
    const { rerender } = render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" semester="Fall 2025" onClose={onClose} />);
    await waitFor(() => expect(listGradescopeLinks).toHaveBeenCalledWith('u1', 'Fall 2025'));
    rerender(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" semester="Spring 2026" onClose={onClose} />);
    expect(await screen.findByText('Pick the matching Gradescope course')).toBeInTheDocument();
    await act(async () => resolveOld({ links: [{ id: 'old', sapling_course_id: 'c1', gradescope_course_id: '123', last_synced_at: null }] }));
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
    expect(screen.getByText('Pick the matching Gradescope course')).toBeInTheDocument();
  });

  it('does not report a completed sync into a closed and reopened dialog', async () => {
    let resolveSync!: (value: Awaited<ReturnType<typeof syncGradescopeCourse>>) => void;
    vi.mocked(syncGradescopeCourse).mockImplementation(() => new Promise(resolve => { resolveSync = resolve; }));
    const onSynced = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    const props = { userId: 'u1', saplingCourseId: 'c1', onSynced, onClose };
    const { rerender } = render(<GradescopeSyncModal {...props} open />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    rerender(<GradescopeSyncModal {...props} open={false} />);
    rerender(<GradescopeSyncModal {...props} open />);
    await screen.findByRole('button', { name: 'Sync now' });
    await act(async () => resolveSync({ inserted: 1, updated: 0, skipped: 0, failed: 0 }));
    expect(onSynced).not.toHaveBeenCalled();
    expect(screen.queryByText('Sync complete')).not.toBeInTheDocument();
  });

  it('keeps focus in the dialog and restores it when closing', async () => {
    const trigger = document.createElement('button');
    document.body.append(trigger);
    trigger.focus();
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { unmount } = render(<GradescopeSyncModal open reconnect userId="u1" onClose={onClose} />);
    const cancel = await screen.findByRole('button', { name: 'Cancel' });
    cancel.focus();
    await user.tab();
    expect(screen.getByRole('button', { name: /BU SSO \+ Duo/ })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it('labels BU credentials and prevents a second SSO submit while waiting', async () => {
    vi.mocked(connectGradescopeViaBuSso).mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /BU SSO \+ Duo/ }));
    await user.type(screen.getByLabelText('BU username'), 'student');
    await user.type(screen.getByLabelText('BU password'), 'test-password');
    await user.dblClick(screen.getByRole('button', { name: 'Sign in & send Duo push' }));
    expect(await screen.findByText('Waiting for Duo approval')).toBeInTheDocument();
    expect(connectGradescopeViaBuSso).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      'a Duo timeout whose detail carries the page dump',
      408,
      "Stuck on Shibboleth after Duo for 120s. page=https://shib.bu.edu/idp title='Duo' elements=[input[name='j_username' type='text']]",
      "Duo push wasn't approved in time. Tap Approve quickly when your phone buzzes.",
    ],
    [
      'an SSO failure whose detail is a page dump',
      401,
      "SSO ended at an unexpected URL: https://example.edu/x. page=https://example.edu/x title='Oops' elements=[a[text='Help' href='']]",
      'BU sign-in failed. Try again, or connect with session cookies instead.',
    ],
    [
      'a wrong BU password',
      401,
      'BU login failed — username or password is incorrect.',
      'BU login failed. Username or password is incorrect.',
    ],
  ])('explains %s in BU SSO terms, not Sapling-session terms', async (_case, status, detail, copy) => {
    vi.mocked(connectGradescopeViaBuSso).mockRejectedValue(
      Object.assign(new Error(JSON.stringify({ detail })), { status }),
    );
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /BU SSO \+ Duo/ }));
    await user.type(screen.getByLabelText('BU username'), 'student');
    await user.type(screen.getByLabelText('BU password'), 'test-password');
    await user.click(screen.getByRole('button', { name: 'Sign in & send Duo push' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(copy);
    expect(screen.getByRole('alert')).not.toHaveTextContent('Your session expired');
  });
});
