import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import {
  ABOUT_AWARDS,
  ABOUT_DIFFERENTIATORS,
  TEAM_MEMBERS,
  TEAM_WAYS,
} from '@/lib/landing/companionContent';
import { DISPLAY, MONO, SERIF } from '@/lib/landing/companionType';

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
 *
 * /team is folded in here. It was a separate page — portrait tiles over a "How
 * we work" list — that never published: its five frames were empty, so it shipped
 * noindexed and unlinked from both footers, waiting on photographs that had not
 * arrived. The tiles are what is dropped in the merge; the writing is what was
 * actually finished, and it belongs on the page people already reach. Members
 * read as name, role and bio, which is the tile's caption without the empty
 * square above it. If photographs arrive, the frame markup is in this file's
 * history at team/page.tsx — restore the tiles here rather than the page.
 *
 * Section order follows the reader, not the merge: what Sapling is, then who
 * built it, then how they work, then what it has won. "How we work" sits after
 * the team because its three lines are that team's own commitments and read as
 * theirs; Recognition stays last because it closes on the byline.
 */

export const metadata: Metadata = {
  title: 'About',
  description:
    'The story behind Sapling: a student-built AI study partner from Boston University, recognized for reimagining how students learn through conversation and a living knowledge graph.',
  alternates: { canonical: '/about' },
};

/**
 * Body copy shares one type ramp; only the stagger delay changes.
 *
 * No `maxWidth`. The page used to cap every passage at the shared prose
 * measure ('80ch', which computes to exactly 640px in Spectral) while the h1
 * and the closing byline ran the full 1116px content box — so each paragraph
 * sat in the left 640 with a 476px void beside it. The passages fill the box
 * instead, giving the page one right edge.
 */
const PROSE: React.CSSProperties = {
  margin: 0, fontFamily: SERIF, fontWeight: 400, fontSize: 16,
  lineHeight: 1.6, color: '#3f3b31',
};

/**
 * Section heading. The original page inlined these values once, for
 * Recognition; the merge gives the page three sections, so the one copy
 * becomes a constant rather than three.
 *
 * They are display type at 30px, not the 10px mono eyebrow the page used to
 * set them in. An eyebrow works when a page has one section and the h1 is
 * doing the dividing; with three sections it is the heading that has to be
 * findable while scrolling, and 10px uppercase in accent green is a label on
 * the section rather than a title of it. 30 against the 48px h1 keeps the
 * hierarchy unambiguous at a glance.
 *
 * They are `h2` for the same reason they are large — the page now has a real
 * outline, and it should be one a screen reader can navigate.
 */
const SECTION_HEADING: React.CSSProperties = {
  margin: '0 0 24px', fontFamily: DISPLAY, fontWeight: 500, fontSize: 30,
  lineHeight: 1.2, letterSpacing: '-0.015em', color: '#1a1814',
};

export default function AboutPage() {
  return (
    <CompanionShell current="/about">
      <div>
        <h1 style={{ margin: '0 0 32px', fontFamily: DISPLAY, fontWeight: 500, fontSize: 48, lineHeight: 1.15, letterSpacing: '-0.015em', color: '#1a1814', animation: 'fadeUp 700ms ease both' }}>
          About Sapling
        </h1>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          <p style={{ ...PROSE, animation: 'fadeUp 700ms ease 80ms both' }}>
            {/* Explicit space: the literal one that used to sit after </strong>
                was on the line's leading edge and did not survive the JSX text
                trim, so the sentence rendered as "Saplingis an". */}
            <strong style={{ color: '#1a1814', fontWeight: 600 }}>Sapling</strong>{' '}
            is an AI-powered study companion built by students, for students. We believe that
            learning
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
          <h2 style={{ ...SECTION_HEADING, animation: 'fadeUp 700ms ease 380ms both' }}>
            Meet the team
          </h2>

          <p style={{ ...PROSE, margin: '0 0 32px', animation: 'fadeUp 700ms ease 420ms both' }}>
            A small team out of Boston University who got tired of study tools that did not know
            what they were studying. We build Sapling between problem sets, and we use it for our
            own classes first.
          </p>

          {/* Two-up where there is room, one column where there is not. The
              portrait tiles this grid used to caption are gone, so the cells
              are text only and can be narrower than /team's 230px. */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px,1fr))', gap: '28px 32px' }}>
            {TEAM_MEMBERS.map((m, i) => (
              <div
                key={m.name}
                style={{ display: 'flex', flexDirection: 'column', gap: 5, animation: 'fadeUp 700ms ease both', animationDelay: `${460 + i * 50}ms` }}
              >
                <span style={{ fontSize: 15.5, fontWeight: 600, color: '#1a1814', letterSpacing: '-0.01em' }}>{m.name}</span>
                <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#2D8F5C' }}>{m.role}</span>
                <span style={{ fontFamily: SERIF, fontSize: 14, lineHeight: 1.6, color: '#3f3b31' }}>{m.body}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 56 }}>
          <h2 style={{ ...SECTION_HEADING, animation: 'fadeUp 700ms ease 720ms both' }}>
            How we work
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {TEAM_WAYS.map((w, i) => (
              <div
                key={w}
                style={{ display: 'flex', gap: 12, alignItems: 'flex-start', animation: 'fadeUp 700ms ease both', animationDelay: `${760 + i * 50}ms` }}
              >
                <span style={{ color: '#2D8F5C', marginTop: 2, flex: '0 0 auto' }}>&#8226;</span>
                <span style={{ fontFamily: SERIF, fontSize: 15, lineHeight: 1.6, color: '#3f3b31' }}>{w}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 56 }}>
          <h2 style={{ ...SECTION_HEADING, animation: 'fadeUp 700ms ease 920ms both' }}>
            Recognition
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
            {ABOUT_AWARDS.map((a, i) => (
              <div key={a.title} style={{ animation: 'fadeUp 700ms ease both', animationDelay: `${960 + i * 60}ms` }}>
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
