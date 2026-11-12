/**
 * The wiki's account of onboarding says what onboarding asks today.
 */
import { describe, expect, it } from 'vitest';
import { WIKI_ONBOARDING_SPECS } from './companionContent';

describe('WIKI_ONBOARDING_SPECS', () => {
  const text = WIKI_ONBOARDING_SPECS.map((r) => `${r.label} ${r.value} ${r.note}`).join('\n');

  it('no longer claims onboarding asks for majors or a learning style', () => {
    expect(text).not.toMatch(/majors/i);
    expect(text).not.toMatch(/learning style/i);
  });

  it('describes sign-in first, the age check and courses added later', () => {
    expect(text).toContain('You sign in first');
    expect(text).toContain('13 or older');
    expect(text).toContain('add them later');
  });
});
