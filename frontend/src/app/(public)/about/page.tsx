import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import {
  ABOUT_AWARDS,
  ABOUT_DIFFERENTIATORS,
  TEAM_MEMBERS,
  TEAM_WAYS,
} from '@/lib/landing/companionContent';

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

export default function AboutPage() {
  return (
    <CompanionShell current="/about">
      <div>
        <h1 className="mt-0 mx-0 mb-8 font-display font-medium text-[48px] leading-[1.15] tracking-[-0.015em] text-ink-800 [animation:fadeUp_700ms_ease_both]">
          About Sapling
        </h1>

        <div className="flex flex-col gap-6">
          <p className="m-0 font-serif font-normal text-lg leading-[1.6] text-ink-600 [animation:fadeUp_700ms_ease_80ms_both]">
            {/* Explicit space: the literal one that used to sit after </strong>
                was on the line's leading edge and did not survive the JSX text
                trim, so the sentence rendered as "Saplingis an". */}
            <strong className="text-ink-800 font-semibold">Sapling</strong>{' '}
            is an AI-powered study companion built by students, for students. We believe that
            learning
            shouldn&#8217;t be passive. It should adapt to you, challenge you, and show you exactly
            where you stand.
          </p>

          <p className="m-0 font-serif font-normal text-lg leading-[1.6] text-ink-600 [animation:fadeUp_700ms_ease_140ms_both]">
            At its core, Sapling maps your understanding as a live knowledge graph that grows with
            every session, quiz, and document you interact with. Paired with an AI tutor that can
            reason with you Socratically, explain concepts directly, or flip the table and have you
            teach back, Sapling meets you wherever you are in your learning journey.
          </p>

          <p className="m-0 font-serif font-normal text-lg leading-[1.6] text-ink-600 [animation:fadeUp_700ms_ease_200ms_both]">
            Sapling was born out of a hackathon and built by a team of four students who were
            frustrated with static study tools that don&#8217;t actually know what you know. We
            wanted something that feels less like a flashcard app and more like a study partner
            who&#8217;s always prepared.
          </p>

          <div className="[animation:fadeUp_700ms_ease_260ms_both]">
            <p className="mt-0 mx-0 mb-3 text-[15px] font-semibold text-ink-800">
              What makes Sapling different:
            </p>
            <ul className="list-none p-0 m-0 flex flex-col gap-2">
              {ABOUT_DIFFERENTIATORS.map((d) => (
                <li key={d} className="flex gap-3 font-serif text-[15px] leading-[1.6] text-ink-600">
                  <span className="text-brand-forest-bright mt-0.5 flex-[0_0_auto]">&#8226;</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>

          <p className="m-0 font-serif font-normal text-lg leading-[1.6] text-ink-600 [animation:fadeUp_700ms_ease_320ms_both]">
            Sapling is actively developed and we&#8217;re always building. If something&#8217;s
            broken or you have an idea, there&#8217;s a feedback button in the navbar and we
            actually read those.
          </p>
        </div>

        <div className="mt-14">
          <h2 className="mt-0 mx-0 mb-6 font-display font-medium text-4xl leading-[1.2] tracking-[-0.015em] text-ink-800 [animation:fadeUp_700ms_ease_380ms_both]">
            Meet the team
          </h2>

          <p className="font-serif font-normal text-lg leading-[1.6] text-ink-600 mt-0 mx-0 mb-8 [animation:fadeUp_700ms_ease_420ms_both]">
            A small team out of Boston University who got tired of study tools that did not know
            what they were studying. We build Sapling between problem sets, and we use it for our
            own classes first.
          </p>

          {/* Two-up where there is room, one column where there is not. The
              portrait tiles this grid used to caption are gone, so the cells
              are text only and can be narrower than /team's 230px. */}
          <div className="grid grid-cols-[repeat(auto-fit,_minmax(260px,1fr))] gap-y-7 gap-x-8">
            {TEAM_MEMBERS.map((m, i) => (
              <div
                key={m.name}
                className="flex flex-col gap-[5px] [animation:fadeUp_700ms_ease_both]" style={{ animationDelay: `${460 + i * 50}ms` }}
              >
                <span className="text-[15.5px] font-semibold text-ink-800 tracking-[-0.01em]">{m.name}</span>
                <span className="font-sans text-sm text-brand-forest-bright">{m.role}</span>
                <span className="font-serif text-base leading-[1.6] text-ink-600">{m.body}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-14">
          <h2 className="mt-0 mx-0 mb-6 font-display font-medium text-4xl leading-[1.2] tracking-[-0.015em] text-ink-800 [animation:fadeUp_700ms_ease_720ms_both]">
            How we work
          </h2>
          <div className="flex flex-col gap-3.5">
            {TEAM_WAYS.map((w, i) => (
              <div
                key={w}
                className="flex gap-3 items-start [animation:fadeUp_700ms_ease_both]" style={{ animationDelay: `${760 + i * 50}ms` }}
              >
                <span className="text-brand-forest-bright mt-0.5 flex-[0_0_auto]">&#8226;</span>
                <span className="font-serif text-[15px] leading-[1.6] text-ink-600">{w}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-14">
          <h2 className="mt-0 mx-0 mb-6 font-display font-medium text-4xl leading-[1.2] tracking-[-0.015em] text-ink-800 [animation:fadeUp_700ms_ease_920ms_both]">
            Recognition
          </h2>
          <div className="flex flex-col gap-8">
            {ABOUT_AWARDS.map((a, i) => (
              <div key={a.title} className="[animation:fadeUp_700ms_ease_both]" style={{ animationDelay: `${960 + i * 60}ms` }}>
                <p className="m-0 text-lg font-semibold text-ink-800">{a.title}</p>
                <p className="mt-0.5 mx-0 mb-0 text-sm font-medium text-brand-forest-bright">{a.org}</p>
                <p className="mt-2 mx-0 mb-0 font-serif text-base leading-[1.6] text-ink-600">{a.body}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-12 pt-8 border-t border-t-[rgba(42,39,31,0.10)] text-md text-text-muted">
          Built by Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez &#169; 2026
        </div>
      </div>
    </CompanionShell>
  );
}
