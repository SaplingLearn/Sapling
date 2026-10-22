import { preload } from 'react-dom';

const LEAF_SRC = '/design/sapling/sapling-leaf.svg';

/**
 * The "i" of a typeset "Sapling": a real "i" with its dot clipped off, under the
 * approved wordmark's own leaf, so set type carries the same leaf tittle as the
 * drawn logo. The text stays a plain "i", so copy/paste, find-in-page and
 * crawlers still read "Sapling".
 *
 * Sized and placed in em against Aleo, so it follows whatever font-size it is
 * set in; its own line-height of 1 keeps the clip and the leaf's offset from
 * the glyph the same whatever line-height the surrounding text is set in. In
 * that box Aleo's dot ends at 0.22em and the stem starts at 0.29em (weights
 * 600 and 700), so the clip line sits between them at 25.5%.
 *
 * The leaf is preloaded so the server-rendered intro overlay doesn't paint a
 * bare stem while the image is still in flight.
 */
export function LeafI() {
  preload(LEAF_SRC, { as: 'image' });
  return (
    <span style={{ position: 'relative', display: 'inline-block', lineHeight: 1 }}>
      <span
        style={{
          display: 'inline-block',
          clipPath: 'polygon(-50% 25.5%, 150% 25.5%, 150% 150%, -50% 150%)',
        }}
      >
        i
      </span>
      {/* eslint-disable-next-line @next/next/no-img-element -- a static vector; next/image adds nothing for SVG */}
      <img
        src={LEAF_SRC}
        alt=""
        aria-hidden
        draggable={false}
        style={{
          position: 'absolute',
          left: '50%',
          top: '-0.02em',
          width: '0.3em',
          height: 'auto',
          transform: 'translateX(-38%)',
          pointerEvents: 'none',
        }}
      />
    </span>
  );
}
