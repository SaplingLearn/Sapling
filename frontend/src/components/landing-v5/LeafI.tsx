/**
 * The "i" of a typeset "Sapling": a dotless ı under the approved wordmark's own
 * leaf, so set type carries the same leaf tittle as the drawn logo. Sized and
 * placed in em against Aleo, so it follows whatever font-size it is set in;
 * its own line-height of 1 keeps the leaf's offset from the glyph the same
 * whatever line-height the surrounding text is set in.
 */
export function LeafI() {
  return (
    <span style={{ position: 'relative', display: 'inline-block', lineHeight: 1 }}>
      ı
      {/* eslint-disable-next-line @next/next/no-img-element -- a static vector; next/image adds nothing for SVG */}
      <img
        src="/design/sapling/sapling-leaf.svg"
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
