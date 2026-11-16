// @vitest-environment jsdom
// Characterization of GradescopeSyncDialog's stages, titles, handlers and
// dismissal rules — pinned before the complexity split so the refactor can be
// checked against the exact DOM and behavior it replaced.
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GradescopeSyncModal } from './GradescopeSyncModal';
import {
  getGradescopeStatus, listGradescopeCourses, listGradescopeLinks, syncGradescopeCourse,
  saveGradescopeCredentials, deleteGradescopeCredentials, linkGradescopeCourse,
  connectGradescopeViaBuSso,
} from '@/lib/api';

vi.mock('@/lib/api', () => ({
  getGradescopeStatus: vi.fn(), saveGradescopeCredentials: vi.fn(),
  connectGradescopeViaBuSso: vi.fn(), listGradescopeCourses: vi.fn(),
  listGradescopeLinks: vi.fn(), linkGradescopeCourse: vi.fn(),
  syncGradescopeCourse: vi.fn(), deleteGradescopeCredentials: vi.fn(),
}));

const COURSES = [
  { id: '123', name: 'CS101', full_name: 'Intro to CS', semester: 'Fall', year: '2025', num_assignments: '1' },
  { id: '456', name: 'MA201', full_name: 'MA201', semester: '', year: '2026', num_assignments: '2' },
];
const LAST = '2026-01-02T03:04:05Z';

beforeEach(() => {
  vi.mocked(listGradescopeCourses).mockResolvedValue({ courses: COURSES });
  vi.mocked(getGradescopeStatus).mockResolvedValue({
    has_credentials: true, auth_mode: 'cookies', last_synced_at: null,
  });
  vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [{
    id: 'link', sapling_course_id: 'c1', gradescope_course_id: '123', last_synced_at: LAST,
  }] });
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

/** The portal's DOM with React's generated ids, the machine's locale/timezone
 *  rendering of the last sync and the Duo wait counter normalised away. */
function dialogHtml() {
  const dialog = screen.getByRole('dialog');
  return dialog.outerHTML
    .replace(/ (id|for)="[^"]*"/g, ' $1="X"')
    .replace(/Last sync · [^<]*/g, 'Last sync · DATE')
    .replace(/Waiting · \d+s/g, 'Waiting · Ns');
}

function title() {
  return screen.getByRole('heading', { level: 2 }).textContent;
}

describe('GradescopeSyncDialog stage DOM', () => {
  it('renders the loading stage with the default kicker', async () => {
    vi.mocked(getGradescopeStatus).mockImplementation(() => new Promise(() => {}));
    render(<GradescopeSyncModal open userId="u1" onClose={vi.fn()} />);
    expect(await screen.findByText('Loading…')).toBeInTheDocument();
    expect(title()).toBe('Pull grades from Gradescope');
    expect(screen.getByText(/Gradescope · Connection/)).toBeInTheDocument();
    expect(dialogHtml()).toMatchSnapshot();
  });

  it('renders the verification-error stage and its Reconnect path', async () => {
    vi.mocked(getGradescopeStatus).mockRejectedValue(Object.assign(new Error('boom'), { status: 502 }));
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" saplingCourseLabel="CS 101" onClose={onClose} />);
    expect(await screen.findByRole('button', { name: 'Retry connection' })).toBeInTheDocument();
    expect(title()).toBe("Couldn't verify Gradescope");
    expect(screen.getByText(/Gradescope · CS 101/)).toBeInTheDocument();
    expect(dialogHtml()).toMatchSnapshot();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', { name: 'Reconnect' }));
    expect(title()).toBe('Connect Gradescope');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('renders each sign-in form with its title and Back returns to the choices', async () => {
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    await screen.findByText('Connect Gradescope');
    expect(dialogHtml()).toMatchSnapshot('choose-mode');

    await user.click(screen.getByRole('button', { name: /Email \+ password/ }));
    expect(title()).toBe('Sign in with Gradescope password');
    expect(dialogHtml()).toMatchSnapshot('credentials');
    await user.click(screen.getByRole('button', { name: '← Back' }));
    expect(title()).toBe('Connect Gradescope');

    await user.click(screen.getByRole('button', { name: /Session cookies/ }));
    expect(title()).toBe('Paste your Gradescope session');
    expect(dialogHtml()).toMatchSnapshot('cookies');
    await user.click(screen.getByRole('button', { name: '← Back' }));

    await user.click(screen.getByRole('button', { name: /BU SSO \+ Duo/ }));
    expect(title()).toBe('Sign in with BU SSO');
    expect(dialogHtml()).toMatchSnapshot('bu-sso-form');
    await user.click(screen.getByRole('button', { name: '← Back' }));
    expect(title()).toBe('Connect Gradescope');
  });

  it('renders the link stage with course rows and picks a course', async () => {
    vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [] });
    vi.mocked(linkGradescopeCourse).mockResolvedValue({ link: null });
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" saplingCourseLabel="CS 101" semester="Fall 2025" onClose={vi.fn()} />);
    expect(await screen.findByText('Pick the matching Gradescope course')).toBeInTheDocument();
    expect(screen.getByText('Intro to CS')).toBeInTheDocument();
    expect(screen.getByText('Fall 2025')).toBeInTheDocument();
    expect(screen.getByText('2026')).toBeInTheDocument();
    expect(dialogHtml()).toMatchSnapshot();
    const row = screen.getByRole('button', { name: /CS101/ });
    fireEvent.mouseEnter(row);
    expect(row.style.borderColor).toBe('var(--border-strong)');
    fireEvent.mouseLeave(row);
    expect(row.style.borderColor).toBe('var(--border)');
    await user.click(row);
    expect(linkGradescopeCourse).toHaveBeenCalledWith('u1', 'c1', '123', 'Fall 2025');
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    expect(screen.queryByText(/Last sync/)).not.toBeInTheDocument();
    expect(screen.getByText('123')).toBeInTheDocument();
  });

  it('renders the empty link stage', async () => {
    vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [] });
    vi.mocked(listGradescopeCourses).mockResolvedValue({ courses: [] });
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    expect(await screen.findByText(/didn.t find any student courses/)).toBeInTheDocument();
    expect(dialogHtml()).toMatchSnapshot();
  });

  it('shows a failed link without leaving the picker', async () => {
    vi.mocked(listGradescopeLinks).mockResolvedValue({ links: [] });
    vi.mocked(linkGradescopeCourse).mockRejectedValue(new Error('{"detail":"Link refused."}'));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /CS101/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Link refused.');
    expect(title()).toBe('Pick the matching Gradescope course');
  });

  it.each([
    [COURSES, 'with 2 student courses'],
    [COURSES.slice(0, 1), 'with 1 student course.'],
    [[], 'no student courses'],
  ])('renders the settings-mode connected stage (%#)', async (courses, copy) => {
    vi.mocked(listGradescopeCourses).mockResolvedValue({ courses });
    vi.mocked(getGradescopeStatus).mockResolvedValue({
      has_credentials: true, auth_mode: 'cookies', last_synced_at: courses.length ? LAST : null,
    });
    render(<GradescopeSyncModal open userId="u1" onClose={vi.fn()} />);
    expect(await screen.findByText('Gradescope is connected')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(copy))).toBeInTheDocument();
    expect(screen.queryByText(/Last sync/) !== null).toBe(courses.length > 0);
    expect(listGradescopeLinks).not.toHaveBeenCalled();
    expect(dialogHtml()).toMatchSnapshot();
  });

  it('renders the ready stage with the last sync and the syncing stage', async () => {
    vi.mocked(syncGradescopeCourse).mockImplementation(() => new Promise(() => {}));
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" saplingCourseLabel="CS 101" onClose={onClose} />);
    await screen.findByRole('button', { name: 'Sync now' });
    expect(screen.getByText(/Last sync ·/)).toBeInTheDocument();
    expect(dialogHtml()).toMatchSnapshot('ready');
    await user.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(screen.getByRole('button', { name: 'Syncing…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Change course' })).toBeDisabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(title()).toBe('Pull grades from Gradescope');
    expect(dialogHtml()).toMatchSnapshot('syncing');
    // A non-pending sync can't be dismissed from the backdrop or Escape.
    fireEvent.click(screen.getByRole('dialog'));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('renders the pending-sync note', async () => {
    vi.mocked(syncGradescopeCourse).mockImplementation((_u, _c, _s, options) => {
      options?.onPending?.();
      return new Promise(() => {});
    });
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={onClose} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    await screen.findByRole('status');
    expect(dialogHtml()).toMatchSnapshot();
    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('renders the done stage for a clean sync', async () => {
    vi.mocked(syncGradescopeCourse).mockResolvedValue({ inserted: 3, updated: 2, skipped: 1, failed: 0 });
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={onClose} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('Sync complete')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry sync' })).not.toBeInTheDocument();
    expect(dialogHtml()).toMatchSnapshot('clean');
    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('renders the done stage for a partial sync', async () => {
    vi.mocked(syncGradescopeCourse).mockResolvedValue({ inserted: 1, updated: 0, skipped: 0, failed: 2 });
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('Sync needs attention')).toBeInTheDocument();
    expect(dialogHtml()).toMatchSnapshot('partial');
  });

  it('keeps the ready stage on a sync failure that is not a sign-in problem', async () => {
    vi.mocked(syncGradescopeCourse).mockRejectedValue(Object.assign(new Error('{"detail":"Upstream down."}'), { status: 502 }));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Sync now' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Upstream down.');
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeEnabled();
    expect(dialogHtml()).toMatchSnapshot();
  });
});

describe('GradescopeSyncDialog handlers', () => {
  it('saves password credentials, clears the password and reloads the state', async () => {
    vi.mocked(saveGradescopeCredentials).mockResolvedValue(undefined as never);
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /Email \+ password/ }));
    await user.type(screen.getByLabelText('Email'), '  me@bu.edu ');
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Connect' }));
    expect(saveGradescopeCredentials).toHaveBeenCalledWith('u1', { auth_mode: 'password', email: 'me@bu.edu', password: 'pw' });
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    expect(getGradescopeStatus).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['{"detail":"Invalid email or password"}', 'Invalid Gradescope credentials.'],
    ['{"detail":"Gradescope is down"}', 'Gradescope is down'],
  ])('maps a failed password save %s', async (message, copy) => {
    vi.mocked(saveGradescopeCredentials).mockRejectedValue(Object.assign(new Error(message), { status: 400 }));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /Email \+ password/ }));
    await user.type(screen.getByLabelText('Email'), 'me@bu.edu');
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(copy);
    expect(title()).toBe('Sign in with Gradescope password');
    expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled();
  });

  it('requires a session cookie, then saves trimmed cookies', async () => {
    vi.mocked(saveGradescopeCredentials).mockResolvedValue(undefined as never);
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /Session cookies/ }));
    const session = screen.getByLabelText(/_gradescope_session/);
    await user.type(session, '   ');
    fireEvent.submit(session.closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('Paste your _gradescope_session cookie value.');
    expect(saveGradescopeCredentials).not.toHaveBeenCalled();
    await user.clear(session);
    await user.type(session, ' sess ');
    await user.click(screen.getByRole('button', { name: 'Verify & connect' }));
    expect(saveGradescopeCredentials).toHaveBeenCalledWith('u1', { auth_mode: 'cookies', gradescope_session: 'sess', signed_token: undefined });
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument();
  });

  it('shows the backend reason when cookies are rejected', async () => {
    vi.mocked(saveGradescopeCredentials).mockRejectedValue(Object.assign(new Error('{"detail":"Cookie truncated."}'), { status: 400 }));
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /Session cookies/ }));
    await user.type(screen.getByLabelText(/_gradescope_session/), 'sess');
    await user.type(screen.getByLabelText(/signed_token/), ' tok ');
    await user.click(screen.getByRole('button', { name: 'Verify & connect' }));
    expect(saveGradescopeCredentials).toHaveBeenCalledWith('u1', { auth_mode: 'cookies', gradescope_session: 'sess', signed_token: 'tok' });
    expect(await screen.findByRole('alert')).toHaveTextContent('Cookie truncated.');
    expect(title()).toBe('Paste your Gradescope session');
  });

  it('requires BU credentials before sending a Duo push', async () => {
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: /BU SSO \+ Duo/ }));
    fireEvent.submit(screen.getByLabelText('BU username').closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter your BU username and password.');
    expect(connectGradescopeViaBuSso).not.toHaveBeenCalled();
  });

  it('blocks dismissal while waiting for Duo, then reloads after approval', async () => {
    let approve!: () => void;
    vi.mocked(connectGradescopeViaBuSso).mockImplementation(() => new Promise(resolve => { approve = () => resolve(undefined as never); }));
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" saplingCourseId="c1" onClose={onClose} />);
    await user.click(await screen.findByRole('button', { name: /BU SSO \+ Duo/ }));
    await user.type(screen.getByLabelText('BU username'), ' student ');
    await user.type(screen.getByLabelText('BU password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Sign in & send Duo push' }));
    expect(await screen.findByText('Waiting for Duo approval')).toBeInTheDocument();
    expect(connectGradescopeViaBuSso).toHaveBeenCalledWith('u1', 'student', 'pw', 120);
    expect(dialogHtml()).toMatchSnapshot();
    fireEvent.click(screen.getByRole('dialog'));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => approve());
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument();
  });

  it('removes credentials after confirming and returns to the choices', async () => {
    vi.mocked(deleteGradescopeCredentials).mockResolvedValue(undefined as never);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Disconnect' }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(deleteGradescopeCredentials).toHaveBeenCalledWith('u1');
    expect(await screen.findByText('Connect Gradescope')).toBeInTheDocument();
    confirm.mockRestore();
  });

  it('keeps credentials when the removal is not confirmed, and reports a failed removal', async () => {
    vi.mocked(deleteGradescopeCredentials).mockRejectedValue(new Error('{"detail":"Delete failed."}'));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    render(<GradescopeSyncModal open userId="u1" saplingCourseId="c1" onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Use different account' }));
    expect(deleteGradescopeCredentials).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Use different account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Delete failed.');
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    confirm.mockRestore();
  });
});

describe('GradescopeSyncDialog focus trap', () => {
  it('wraps Tab and Shift+Tab around the dialog controls', async () => {
    const user = userEvent.setup();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={vi.fn()} />);
    const first = await screen.findByRole('button', { name: /BU SSO \+ Duo/ });
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveFocus());
    await user.tab({ shift: true });
    expect(cancel).toHaveFocus();
    await user.tab();
    expect(first).toHaveFocus();
    await user.tab({ shift: true });
    expect(cancel).toHaveFocus();
    // Other keys and a mid-list Tab are left alone.
    fireEvent.keyDown(cancel, { key: 'a' });
    expect(cancel).toHaveFocus();
  });

  it('keeps focus on the dialog when it has no enabled controls', async () => {
    vi.mocked(getGradescopeStatus).mockImplementation(() => new Promise(() => {}));
    render(<GradescopeSyncModal open userId="u1" onClose={vi.fn()} />);
    await screen.findByText('Loading…');
    const dialog = screen.getByRole('dialog');
    const event = fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(event).toBe(false); // preventDefault was called
    expect(dialog).toHaveFocus();
  });

  it('does not close from a click inside the panel', async () => {
    const onClose = vi.fn();
    render(<GradescopeSyncModal open reconnect userId="u1" onClose={onClose} />);
    fireEvent.click(await screen.findByText('Connect Gradescope'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
