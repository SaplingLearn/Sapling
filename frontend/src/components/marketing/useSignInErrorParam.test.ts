// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useSignInErrorParam } from './useSignInErrorParam';

describe('useSignInErrorParam (#756)', () => {
  afterEach(() => window.history.replaceState({}, '', '/'));

  it('reads ?error= once and strips it from the address bar', () => {
    window.history.replaceState({}, '', '/?error=account_deleted&ref=x#faq');
    const { result } = renderHook(() => useSignInErrorParam());
    expect(result.current[0]).toBe('account_deleted');
    expect(window.location.search).toBe('?ref=x');
    expect(window.location.hash).toBe('#faq');
    act(() => result.current[1]());
    expect(result.current[0]).toBeNull();
  });

  it('is null without the param', () => {
    window.history.replaceState({}, '', '/');
    const { result } = renderHook(() => useSignInErrorParam());
    expect(result.current[0]).toBeNull();
  });

  it('ignores a malformed code (but still strips it)', () => {
    window.history.replaceState({}, '', '/?error=%3Cscript%3E');
    const { result } = renderHook(() => useSignInErrorParam());
    expect(result.current[0]).toBeNull();
    expect(window.location.search).toBe('');
  });
});
