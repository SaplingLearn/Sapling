import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ABOUT_AWARDS, ABOUT_DIFFERENTIATORS } from '@/lib/landing/companionContent';

/**
 * About Sapling.
 *
 * Ported from `About Sapling.dc.html`. This page predates the design import
 * and the import was built from it — its script header reads "copy taken
 * verbatim from frontend/src/app/(public)/about/page.tsx" — so the prose here
 * is unchanged. What the port replaces is the chrome: the page used to carry
 * its own 52px bar (maxWidth 1280, hard border-bottom, a lone "Back to home"
 * link) and its own footer, neither of which matched any other public page.
 *
 * Unlike its siblings this page has no eyebrow above the h1; the source goes
 * straight to the title.
 */

export const metadata: Metadata = {
  title: 'About',
  description:
    'The story behind Sapling: a student-built AI study partner from Boston University, recognized for reimagining how students learn through conversation and a living knowledge graph.',
  alternates: { canonical: '/about' },
};

const MONO = "'JetBrains Mono',monospace";
const SERIF = "'Spectral',Georgia,serif";
const DISPLAY = "'Playfair Display',Georgia,serif";

/** Body copy shares one type ramp; only the stagger delay changes. */
const PROSE: React.CSSProperties = {
  margin: 0, fontFamily: SERIF, fontWeight: 400, fontSize: 16,
  lineHeight: 1.6, color: '#3f3b31',
};

export default function AboutPage() {
  return (
    <CompanionShell current="/about">
      <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: 880, margin: '0 auto', padding: '64px 32px', boxSizing: 'border-box' }}>
        <h1 style={{ margin: '0 0 32px', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', color: '#1a1814', animation: 'fadeUp 700ms ease both' }}>
          About Sapling
        </h1>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          <p style={{ ...PROSE, animation: 'fadeUp 700ms ease 80ms both' }}>
            <strong style={{ color: '#1a1814', fontWeight: 600 }}>Sapling</strong> is an
            AI-powered study companion built by students, for students. We believe that learning
            shouldn&#8217;t be passive. It should adapt to you, challenge you, and show you exactly
            where you stand.
          </p>

          <p style={{ ...PROSE, animation: 'fadeUp 700ms ease 140ms both' }}>
            At its core, Sapling maps your understanding as a live knowledge graph that grows with
            every session, quiz, and document you interact with. Paired with an AI tutor that can
            reason with you Socratically, explain concepts directly, or flip the table and have you
            teach back, Sapling meets you wherever you are in your learning journey.
          </p>

          <p style={{ ...PROSE, animation: 'fadeUp 700ms ease 200ms both' }}>
            Sapling was born out of a hackathon and built by a team of four students who were
            frustrated with static study tools that don&#8217;t actually know what you know. We
            wanted something that feels less like a flashcard app and more like a study partner
            who&#8217;s always prepared.
          </p>

          <div style={{ animation: 'fadeUp 700ms ease 260ms both' }}>
            <p style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 600, color: '#1a1814' }}>
              What makes Sapling different:
            </p>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {ABOUT_DIFFERENTIATORS.map((d) => (
                <li key={d} style={{ display: 'flex', gap: 12, fontFamily: SERIF, fontSize: 15, lineHeight: 1.6, color: '#3f3b31' }}>
                  <span style={{ color: '#2D8F5C', marginTop: 2, flex: '0 0 auto' }}>&#8226;</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>

          <p style={{ ...PROSE, animation: 'fadeUp 700ms ease 320ms both' }}>
            Sapling is actively developed and we&#8217;re always building. If something&#8217;s
            broken or you have an idea, there&#8217;s a feedback button in the navbar and we
            actually read those.
          </p>
        </div>

        <div style={{ marginTop: 56 }}>
          <p style={{ margin: '0 0 24px', fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C', animation: 'fadeUp 700ms ease 380ms both' }}>
            Recognition
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
            {ABOUT_AWARDS.map((a) => (
              <div key={a.title} style={{ animation: 'fadeUp 700ms ease both', animationDelay: a.delay }}>
                <p style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#1a1814' }}>{a.title}</p>
                <p style={{ margin: '2px 0 0', fontSize: 12, fontWeight: 500, color: '#2D8F5C' }}>{a.org}</p>
                <p style={{ margin: '8px 0 0', fontFamily: SERIF, fontSize: 14, lineHeight: 1.6, color: '#3f3b31' }}>{a.body}</p>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 48, paddingTop: 32, borderTop: '1px solid rgba(42,39,31,0.10)', fontSize: 13, color: '#6f6857' }}>
          Built by Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez &#169; 2026
        </div>
      </div>
    </CompanionShell>
  );
}
