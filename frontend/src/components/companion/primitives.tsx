'use client';

/**
 * Small shared pieces for the companion pages.
 *
 * Ported from the sibling `.dc.html` design components, which repeat these
 * same type styles on every page.
 */

const SERIF = "'Spectral',Georgia,serif";
const DISPLAY = "'Playfair Display',Georgia,serif";
const MONO = "'JetBrains Mono',monospace";

/** The page title. `fadeUp` is defined alongside the other landing keyframes. */
export function PageTitle({ children }: { children: React.ReactNode }) {
  return (
    <h1 style={{ margin: '0 0 32px', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', color: '#1a1814', animation: 'fadeUp 700ms ease both' }}>
      {children}
    </h1>
  );
}

/** Body copy. `delay` steps the entrance down the page. */
export function Prose({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  return (
    <p style={{ margin: 0, fontFamily: SERIF, fontWeight: 400, fontSize: 16, lineHeight: 1.6, color: '#3f3b31', animation: 'fadeUp 700ms ease both', animationDelay: `${delay}ms` }}>
      {children}
    </p>
  );
}

/** The small green all-caps label that opens a block. */
export function Eyebrow({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  return (
    <p style={{ margin: '0 0 24px', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C', animation: 'fadeUp 700ms ease both', animationDelay: `${delay}ms` }}>
      {children}
    </p>
  );
}

export function SectionHeading({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <h2 id={id} style={{ margin: '0 0 12px', fontFamily: DISPLAY, fontWeight: 500, fontSize: 28, lineHeight: 1.2, letterSpacing: '-0.012em', color: '#1a1814', scrollMarginTop: 110 }}>
      {children}
    </h2>
  );
}

/** A bulleted list with the design's green dot. */
export function Bullets({ items }: { items: readonly string[] }) {
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((t) => (
        <li key={t} style={{ display: 'flex', gap: 12, fontFamily: SERIF, fontSize: 15, lineHeight: 1.6, color: '#3f3b31' }}>
          <span style={{ color: '#2D8F5C', marginTop: 2, flex: '0 0 auto' }}>&bull;</span>
          <span>{t}</span>
        </li>
      ))}
    </ul>
  );
}

export function Award({ title, org, body, delay }: { title: string; org: string; body: string; delay?: string }) {
  return (
    <div style={{ animation: 'fadeUp 700ms ease both', animationDelay: delay }}>
      <p style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#1a1814' }}>{title}</p>
      <p style={{ margin: '2px 0 0', fontSize: 12, fontWeight: 500, color: '#2D8F5C' }}>{org}</p>
      <p style={{ margin: '8px 0 0', fontFamily: SERIF, fontSize: 14, lineHeight: 1.6, color: '#3f3b31' }}>{body}</p>
    </div>
  );
}

/** The hairline-and-note that closes several of the pages. */
export function CloserNote({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 48, paddingTop: 32, borderTop: '1px solid rgba(42,39,31,0.10)', fontSize: 13, color: '#6f6857' }}>
      {children}
    </div>
  );
}
