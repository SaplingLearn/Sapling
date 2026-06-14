import { describe, expect, it } from 'vitest';
import { sanitizeCookieDomain } from './cookieDomain';

describe('sanitizeCookieDomain', () => {
  it('accepts well-formed domains (with or without a leading dot)', () => {
    expect(sanitizeCookieDomain('.saplinglearn.com')).toBe('.saplinglearn.com');
    expect(sanitizeCookieDomain('saplinglearn.com')).toBe('saplinglearn.com');
    expect(sanitizeCookieDomain('app.example.com')).toBe('app.example.com');
  });

  it('trims surrounding whitespace', () => {
    expect(sanitizeCookieDomain('  saplinglearn.com  ')).toBe('saplinglearn.com');
  });

  it('rejects overly-broad bare suffixes', () => {
    expect(sanitizeCookieDomain('.com')).toBeUndefined();
    expect(sanitizeCookieDomain('com')).toBeUndefined();
  });

  it('rejects single-label hosts', () => {
    expect(sanitizeCookieDomain('localhost')).toBeUndefined();
  });

  it('rejects values carrying a scheme, port, path, or whitespace', () => {
    expect(sanitizeCookieDomain('https://saplinglearn.com')).toBeUndefined();
    expect(sanitizeCookieDomain('saplinglearn.com:443')).toBeUndefined();
    expect(sanitizeCookieDomain('saplinglearn.com/path')).toBeUndefined();
    expect(sanitizeCookieDomain('sapling learn.com')).toBeUndefined();
  });

  it('rejects empty / nullish input', () => {
    expect(sanitizeCookieDomain('')).toBeUndefined();
    expect(sanitizeCookieDomain('   ')).toBeUndefined();
    expect(sanitizeCookieDomain(undefined)).toBeUndefined();
    expect(sanitizeCookieDomain(null)).toBeUndefined();
  });
});
