import type { Metadata } from 'next';
import Link from 'next/link';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { TEAM_MEMBERS, TEAM_WAYS } from '@/lib/landing/companionContent';

/**
 * Meet the team.
 *
 * Ported from `Meet the Team.dc.html`. Square portrait tiles over a "How we
 * work" list, closing on a byline and a beta link. The source's awards block
 * is dropped here — /about already carries it, and one copy is enough.
 *
 * Portrait frames are empty: the source fills them with its `image-slot`
 * drop zone ("Drop a photo of …"), an authoring affordance, and the import
 * ships no photographs of the team.
 */

export const metadata: Metadata = {
  title: 'Meet the team',
  description:
    'A small team out of Boston University who got tired of study tools that did not know what they were studying.',
};

const MONO = "'JetBrains Mono',monospace";
const SERIF = "'Spectral',Georgia,serif";
const DISPLAY = "'Playfair Display',Georgia,serif";

const EYEBROW: React.CSSProperties = {
  display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em',
  textTransform: 'uppercase', color: '#2D8F5C',
};

export default function TeamPage() {
  return (
    <CompanionShell current="/team">
      <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: 880, margin: '0 auto', padding: '64px 32px', boxSizing: 'border-box', position: 'relative' }}>
        {/* two motes drifting at the page edges */}
        <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden' }}>
          <span style={{ position: 'absolute', right: '-2%', top: '8%', width: 8, height: 8, borderRadius: 99, background: '#2D8F5C', opacity: 0.28, animation: 'nodeDrift 14s ease-in-out -3s infinite' }} />
          <span style={{ position: 'absolute', left: '-3%', top: '46%', width: 6, height: 6, borderRadius: 99, background: '#1B6C42', opacity: 0.22, animation: 'nodeDrift 17s ease-in-out -8s infinite' }} />
        </div>

        <span style={{ display: 'block', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#6f6857', animation: 'fadeUp 600ms ease both' }}>
          The people
        </span>
        <h1 style={{ margin: '14px 0 0', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', color: '#1a1814', animation: 'fadeUp 700ms ease 60ms both' }}>
          Meet the team
        </h1>
        <p style={{ margin: '24px 0 0', fontFamily: SERIF, fontWeight: 400, fontSize: 16, lineHeight: 1.6, color: '#3f3b31', maxWidth: '62ch', animation: 'fadeUp 700ms ease 140ms both' }}>
          A small team out of Boston University who got tired of study tools that did not know what
          they were studying. We build Sapling between problem sets, and we use it for our own
          classes first.
        </p>

        <div style={{ marginTop: 44, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px,1fr))', gap: 20 }}>
          {TEAM_MEMBERS.map((m) => (
            <div key={m.name} style={{ display: 'flex', flexDirection: 'column', gap: 14, animation: 'fadeUp 700ms ease both', animationDelay: m.delay }}>
              <div style={{ position: 'relative', width: '100%', aspectRatio: '1 / 1', borderRadius: 14, overflow: 'hidden', background: '#ebe6dc', border: '1px solid rgba(42,39,31,0.10)' }} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                <span style={{ fontSize: 15.5, fontWeight: 600, color: '#1a1814', letterSpacing: '-0.01em' }}>{m.name}</span>
                <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C' }}>{m.role}</span>
                <span style={{ fontFamily: SERIF, fontSize: 14, lineHeight: 1.6, color: '#3f3b31' }}>{m.body}</span>
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 56, paddingTop: 32, borderTop: '1px solid rgba(42,39,31,0.10)' }}>
          <span style={EYEBROW}>How we work</span>
          <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {TEAM_WAYS.map((w) => (
              <div key={w} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <span style={{ color: '#2D8F5C', marginTop: 2, flex: '0 0 auto' }}>&bull;</span>
                <span style={{ fontFamily: SERIF, fontSize: 15, lineHeight: 1.6, color: '#3f3b31' }}>{w}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 48, paddingTop: 32, borderTop: '1px solid rgba(42,39,31,0.10)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 18, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: '#6f6857' }}>
            Built by Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez © 2026
          </span>
          <Link href="/#newsletter" style={{ fontSize: 13, fontWeight: 600, color: '#1B6C42' }}>
            Join the beta →
          </Link>
        </div>
      </div>
    </CompanionShell>
  );
}
