import { describe, expect, it } from 'vitest';
import { canDismissGradescopeDialog, connectedCopy, gradescopeDialogTitle, type Stage } from './gradescopeDialog';

describe('gradescopeDialogTitle', () => {
  it.each<[Stage, string]>([
    ['loading', 'Pull grades from Gradescope'],
    ['verification-error', "Couldn't verify Gradescope"],
    ['choose-mode', 'Connect Gradescope'],
    ['credentials', 'Sign in with Gradescope password'],
    ['cookies', 'Paste your Gradescope session'],
    ['bu-sso-form', 'Sign in with BU SSO'],
    ['bu-sso-waiting', 'Waiting for Duo approval'],
    ['connected', 'Gradescope is connected'],
    ['link', 'Pick the matching Gradescope course'],
    ['ready', 'Pull grades from Gradescope'],
    ['syncing', 'Pull grades from Gradescope'],
  ])('titles %s', (stage, title) => {
    expect(gradescopeDialogTitle(stage, null)).toBe(title);
    expect(gradescopeDialogTitle(stage, { failed: 3 })).toBe(title);
  });

  it('titles done by whether anything failed', () => {
    expect(gradescopeDialogTitle('done', { failed: 0 })).toBe('Sync complete');
    expect(gradescopeDialogTitle('done', null)).toBe('Sync complete');
    expect(gradescopeDialogTitle('done', { failed: 1 })).toBe('Sync needs attention');
  });
});

describe('canDismissGradescopeDialog', () => {
  it('blocks while saving, during a non-pending sync, and while waiting for Duo', () => {
    expect(canDismissGradescopeDialog('ready', false, false)).toBe(true);
    expect(canDismissGradescopeDialog('ready', true, false)).toBe(false);
    expect(canDismissGradescopeDialog('syncing', false, false)).toBe(false);
    expect(canDismissGradescopeDialog('syncing', false, true)).toBe(true);
    expect(canDismissGradescopeDialog('syncing', true, true)).toBe(false);
    expect(canDismissGradescopeDialog('bu-sso-waiting', false, false)).toBe(false);
    expect(canDismissGradescopeDialog('bu-sso-waiting', false, true)).toBe(false);
    expect(canDismissGradescopeDialog('done', false, false)).toBe(true);
  });
});

describe('connectedCopy', () => {
  it('pluralises the verified course count', () => {
    expect(connectedCopy(1)).toMatch(/^Your Gradescope account is verified with 1 student course\. /);
    expect(connectedCopy(2)).toMatch(/with 2 student courses\. Go to a course/);
  });

  it('explains an account with no student courses', () => {
    expect(connectedCopy(0)).toMatch(/^Sign-in was verified, but this account has no student courses\./);
  });
});
