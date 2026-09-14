/**
 * Every gallery card has a screenshot behind it.
 *
 * /gallery's own subtitle promises "Every screen in Sapling, as it actually
 * looks", and for its whole life it rendered twelve empty tinted panels. The
 * failure was silent in the way #601's was: content assumed, never supplied,
 * and nothing anywhere that fails when it is missing.
 *
 * This is that missing check. Adding a thirteenth card without capturing its
 * screenshot now fails here instead of shipping another empty panel.
 * Regenerate with `make gallery-shots`.
 *
 * Staleness — a shot that exists but no longer looks like the product — is
 * deliberately NOT checked. That would need the full stack on every CI run
 * and would fail on every intentional redesign.
 */
import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { GALLERY_SHOTS } from './companionContent';

const DIR = path.join(process.cwd(), 'public', 'gallery');

describe('gallery screenshots', () => {
  it('has a captured screenshot for every gallery slot', () => {
    const missing = GALLERY_SHOTS.map((s) => s.slot).filter(
      (slot) => !fs.existsSync(path.join(DIR, `${slot}.png`)),
    );
    expect(missing, `run \`make gallery-shots\` to capture: ${missing.join(', ')}`).toEqual([]);
  });

  it('has no orphaned screenshots for slots that no longer exist', () => {
    const slots = new Set<string>(GALLERY_SHOTS.map((s) => s.slot));
    const orphans = fs.existsSync(DIR)
      ? fs
          .readdirSync(DIR)
          .filter((f) => f.endsWith('.png'))
          .map((f) => f.replace(/\.png$/, ''))
          .filter((slot) => !slots.has(slot))
      : [];
    expect(orphans).toEqual([]);
  });
});
