'use client';

/**
 * Careers — the open-roles list.
 *
 * Moved onto CompanionShell, which owns the header, the footer and the
 * content box. The page used to ship its own 52px sticky bar carrying a lone
 * link home, plus a hand-rolled five-entry link row at the bottom that had
 * drifted from the shared one; both are gone. Palette converted from the
 * app-shell `var(--*)` tokens to the warm paper hexes, because inside the
 * shell those variables resolve against a different layer and fight the
 * paper ground.
 *
 * Rows run the full width of the shell box rather than sitting in the old
 * 760px column: a narrow list inside a wide frame is the "one right edge"
 * failure. The one genuinely long block — a role's description — gets a
 * two-column expansion so the prose lands near a 65-character measure with
 * the tags and the apply button beside it, instead of a 150-character line.
 */

import { useState } from 'react';
import Link from 'next/link';
import { JOBS, DEPT_COLORS } from './jobs';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ACCENT, BODY, DISPLAY, INK, MONO, MUTED, SERIF } from '@/lib/landing/companionType';

const HAIRLINE = '1px solid rgba(42,39,31,0.10)';

const EYEBROW: React.CSSProperties = {
  display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em',
  textTransform: 'uppercase', color: ACCENT,
};

const META: React.CSSProperties = {
  fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.12em',
  textTransform: 'uppercase', color: MUTED,
};

/**
 * Chip colours for a department `jobs.ts` has no entry for. The old fallback
 * read `DEPT_COLORS.Engineering`, a key that no longer exists in the map, so
 * the first job in a new department would have crashed on `dept.bg` rather
 * than degrading to a neutral chip.
 */
const DEPT_FALLBACK = { bg: 'rgba(42,39,31,0.05)', text: MUTED, border: 'rgba(42,39,31,0.14)' };

export default function CareersList() {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const hiring = JOBS.length > 0;

  return (
    <CompanionShell current="/careers">
      <div>
        {/* The dot is the live-role tell: forest green while something is
            open, neutral once nothing is. An accent dot over "not hiring"
            reads as a broken state rather than a deliberate one. */}
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: MUTED, animation: 'fadeUp 600ms ease both' }}>
          <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: 99, background: hiring ? ACCENT : 'rgba(42,39,31,0.28)' }} />
          {hiring ? "We're hiring" : 'Not hiring right now'}
        </span>
        <h1 style={{ margin: '14px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', color: INK, animation: 'fadeUp 700ms ease 60ms both' }}>
          Opportunities
        </h1>
        <p style={{ margin: '24px 0 0', fontFamily: SERIF, fontSize: 16, lineHeight: 1.6, color: BODY, maxWidth: '62ch', animation: 'fadeUp 700ms ease 140ms both' }}>
          We&apos;re a small team building tools that help students learn better. If that sounds like
          work worth doing, we&apos;d love to meet you.
        </p>

        {/* The list reads as a table across the whole box, so it gets a header
            row and hairline rules rather than floating cards. With nothing
            open, the same rule carries the empty state — a header reading
            "0 positions" above blank space is how a page looks broken. */}
        <div style={{ marginTop: 48, paddingBottom: 12, borderBottom: HAIRLINE, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, animation: 'fadeUp 700ms ease 200ms both' }}>
          <span style={EYEBROW}>{hiring ? 'Open roles' : 'Openings'}</span>
          {hiring ? (
            <span style={META}>
              {JOBS.length} {JOBS.length === 1 ? 'position' : 'positions'}
            </span>
          ) : null}
        </div>

        {!hiring ? (
          <p style={{ margin: '44px auto', fontFamily: SERIF, fontSize: 17, lineHeight: 1.65, color: BODY, maxWidth: '52ch', textAlign: 'center', animation: 'fadeUp 700ms ease 260ms both' }}>
            No opportunities at the moment. We post roles here as they open — and the note below
            reaches us either way.
          </p>
        ) : null}

        {JOBS.map((job, i) => {
          const dept = DEPT_COLORS[job.department] ?? DEPT_FALLBACK;
          const isOpen = expandedId === job.id;

          return (
            <div
              key={job.id}
              style={{
                borderBottom: '1px solid rgba(42,39,31,0.08)',
                animation: 'fadeUp 700ms ease both',
                animationDelay: `${260 + i * 60}ms`,
              }}
            >
              <button
                onClick={() => setExpandedId(isOpen ? null : job.id)}
                aria-expanded={isOpen}
                type="button"
                style={{
                  width: '100%', textAlign: 'left', background: 'none', border: 'none',
                  cursor: 'pointer', padding: '24px 0', display: 'flex', alignItems: 'center',
                  justifyContent: 'space-between', gap: 24,
                }}
              >
                <span style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
                  <span style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                    <span style={{ fontSize: 19, fontWeight: 600, color: INK, letterSpacing: '-0.015em' }}>
                      {job.title}
                    </span>
                    <span
                      style={{
                        fontSize: 11, fontWeight: 500, padding: '3px 10px', borderRadius: 99,
                        background: dept.bg, color: dept.text, border: `1px solid ${dept.border}`,
                      }}
                    >
                      {job.department}
                    </span>
                  </span>
                  <span style={META}>
                    {job.location} · {job.type}
                  </span>
                </span>

                {/* Same affordance as the /faq accordion: a hairline circle that
                    fills forest green once the row is open. */}
                <span
                  style={{
                    flex: '0 0 auto', width: 26, height: 26, borderRadius: 99,
                    border: `1px solid ${isOpen ? '#1B6C42' : 'rgba(42,39,31,0.16)'}`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: isOpen ? '#1B6C42' : 'transparent',
                    color: isOpen ? '#faf8f3' : MUTED,
                    transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                    transition: 'all 260ms cubic-bezier(0.22,1,0.36,1)',
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M19 9l-7 7-7-7" />
                  </svg>
                </span>
              </button>

              <div
                style={{
                  overflow: 'hidden',
                  // The cap has to clear the TALLEST the panel ever gets, which
                  // is a phone: one column, a description running past fifteen
                  // lines and the tags stacked five deep. Anything shorter
                  // clips the apply button off the bottom. The ease-out curve
                  // spends its travel early, so the slack costs nothing to look at.
                  maxHeight: isOpen ? 1100 : 0,
                  opacity: isOpen ? 1 : 0,
                  // A collapsed panel still holds a link, so opacity alone would
                  // leave an invisible tab stop. `visibility` takes it out of the
                  // tab order — flipped instantly on open, and held until the
                  // collapse finishes on close so the content does not vanish
                  // mid-animation.
                  visibility: isOpen ? 'visible' : 'hidden',
                  transition: isOpen
                    ? 'max-height 620ms cubic-bezier(0.22,1,0.36,1), opacity 400ms ease'
                    : 'max-height 620ms cubic-bezier(0.22,1,0.36,1), opacity 400ms ease, visibility 0s linear 620ms',
                }}
              >
                <div
                  style={{
                    paddingBottom: 32,
                    display: 'grid',
                    // auto-fit rather than a fixed 2fr/1fr split so the panel
                    // collapses to one column without a media query, which
                    // inline styles cannot express.
                    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%,320px),1fr))',
                    gap: 44,
                    alignItems: 'start',
                  }}
                >
                  <p style={{ margin: 0, fontFamily: SERIF, fontSize: 17, lineHeight: 1.62, color: BODY }}>
                    {job.description}
                  </p>

                  <div>
                    <span style={EYEBROW}>What you&apos;d touch</span>
                    <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                      {job.tags.map((tag) => (
                        <span
                          key={tag}
                          style={{
                            fontSize: 12, padding: '4px 11px', borderRadius: 7,
                            background: '#faf8f3', border: HAIRLINE, color: BODY,
                          }}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                    <Link
                      href={`/careers/${job.slug}`}
                      className="cp-cta"
                      style={{
                        marginTop: 24, display: 'inline-flex', alignItems: 'center', gap: 9,
                        background: '#1B6C42', color: '#fff', borderRadius: 8,
                        padding: '13px 22px', fontSize: 14.5, fontWeight: 600,
                      }}
                    >
                      Apply for this role
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12h14M12 5l7 7-7 7" />
                      </svg>
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        <div style={{ marginTop: 52, borderRadius: 18, background: '#faf8f3', border: HAIRLINE, padding: 'clamp(26px,4vw,40px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ maxWidth: '46ch' }}>
            <span style={EYEBROW}>Don&apos;t see your role?</span>
            <p style={{ margin: '10px 0 0', fontFamily: SERIF, fontSize: 15.5, lineHeight: 1.65, color: BODY }}>
              We&apos;re always interested in meeting talented people. Send us a note and tell us what
              you&apos;d build.
            </p>
          </div>
          <a
            href="mailto:careers@saplinglearn.com"
            className="cp-cta"
            style={{ background: '#1B6C42', color: '#fff', borderRadius: 8, padding: '13px 22px', fontSize: 14.5, fontWeight: 600, whiteSpace: 'nowrap' }}
          >
            Get in touch
          </a>
        </div>
      </div>
    </CompanionShell>
  );
}
