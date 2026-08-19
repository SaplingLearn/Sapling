'use client';

/**
 * The browser-chrome frame every feature-lab demo sits in.
 *
 * Ported from `FeatureLab.dc.html`: three dots, the fake route, and an
 * INTERACTIVE badge, over a scrolling body. The badge is not decoration —
 * these demos really do respond, which is what the panel's
 * "TRY IT · THIS ONE ACTUALLY WORKS" line is promising.
 */

export const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

/** Lab-local tier swatches; see labData.ts for why they differ from the graph's. */
export const LAB_TIER = {
  mastered: '#3a7d4e', learning: '#c89b5e', struggling: '#b25855', unexplored: '#C3CCC6',
} as const;

export function LabShell({ route, children }: { route: string; children: React.ReactNode }) {
  return (
    <div style={{ width: '100%', height: '100%', overflow: 'hidden', fontFamily: "'DM Sans',sans-serif", color: '#12201A', background: '#FDFCF9', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: '0 0 auto', height: 38, borderBottom: '1px solid #ECE9DE', background: '#F6F8F4', display: 'flex', alignItems: 'center', gap: 10, padding: '0 14px' }}>
        <span style={{ display: 'flex', gap: 5 }}>
          {[0, 1, 2].map((i) => (
            <span key={i} style={{ width: 8, height: 8, borderRadius: 99, background: '#E3E0D5' }} />
          ))}
        </span>
        <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.2em', color: '#8B9891' }}>{route}</span>
        <span style={{ marginLeft: 'auto', ...MONO, fontSize: 9, letterSpacing: '0.18em', color: '#0C5638', background: '#E6F2E8', border: '1px solid #DCE7DE', borderRadius: 99, padding: '3px 9px' }}>
          INTERACTIVE
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>{children}</div>
    </div>
  );
}

/** Shared button styles the demos reuse. */
export const PRIMARY_BTN: React.CSSProperties = {
  padding: '11px 24px', borderRadius: 10, border: 'none', background: '#12201A',
  color: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 13.5,
  fontWeight: 600, cursor: 'pointer', transition: 'background 200ms',
};

export const GHOST_BTN: React.CSSProperties = {
  padding: '10px 20px', borderRadius: 10, border: '1px solid #DCE7DE',
  background: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 13,
  color: '#33443B', cursor: 'pointer',
};

/** The segmented control used by the tutor and calendar demos. */
export function Segmented<T extends string>({
  options, value, onChange,
}: {
  options: readonly { key: T; label: string }[];
  value: T;
  onChange: (k: T) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 2, padding: 3, borderRadius: 9, background: '#F6F8F4', border: '1px solid #E3EBE5' }}>
      {options.map((o) => {
        const on = o.key === value;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            type="button"
            aria-pressed={on}
            style={{
              padding: '6px 13px', borderRadius: 7, border: 'none', cursor: 'pointer',
              ...MONO, fontSize: 9.5, letterSpacing: '0.14em',
              background: on ? '#12201A' : 'transparent',
              color: on ? '#FDFCF9' : '#61726A',
              fontWeight: on ? 600 : 400,
              transition: 'all 200ms',
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
