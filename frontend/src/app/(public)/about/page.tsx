import type { Metadata } from 'next';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ABOUT_AWARDS, ABOUT_DIFFERENTIATORS } from '@/lib/landing/companionContent';
import { ACCENT, ARTICLE, DISPLAY, INK, MONO, MUTED, SERIF } from '@/lib/landing/companionType';

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
 * One right edge, and a spine to reach it.
 *
 * `PAGE_MAX` went to 960, which hands every companion page 896px of content.
 * The siblings absorb that in a key column they already had — /wiki's contents
 * rail, the clause titles on /terms and /privacy — but this page was a plain
 * single-column essay, and 896px of Spectral at 18px runs about 97 characters
 * a line (9.26px per character, measured off line boxes, not estimated). The
 * two ways out of that are both closed: raising the type is the one thing the
 * wider box was asked not to do, and capping the prose is the failure this
 * page already shipped once — a 640px paragraph pinned inside a 1116px frame
 * the h1 and the rules filled, hugging the left with a 476px void beside it.
 *
 * So the essay is built as rows instead, the way /terms builds its clauses: a
 * section label in a fixed key cell, the prose in the cell that grows, a
 * hairline per row. Nothing is capped, so the row rules, the masthead and the
 * byline share one right edge, and what is left for the text is 688px — a
 * measured max of 74 characters a line, median 71, counted off real line boxes
 * at 1707px with partial last lines excluded.
 *
 * The spine earns its place as a document, not only as a layout. Four labels
 * and a section name read down the left as the page's contents: what it is,
 * where it started, what is different, still building, Recognition. The
 * differentiator block is the one row with an empty key, and deliberately so:
 * its first line is "What makes Sapling different:", a colon-terminated
 * sentence that reads into its own bullets, so a label above it would restate
 * it and lifting it into the key cell would break the sentence away from the
 * list it introduces. The empty cell still holds the column, which is all the
 * column is being asked to do there.
 *
 * Recognition is the one block that is not running prose, and it is the block
 * the spine cost something. It used to key its own rows — award and org in a
 * 212px cell, citation in the rest (#604) — which was right when it was the
 * only keyed thing here, and is wrong now that the page has a spine: two key
 * columns 32px apart read as a misalignment, not as two systems. So the award
 * identity moves into the text cell above its citation and the key column goes
 * to the section, named once and held open by an empty cell on the second
 * award. The citation comes up from 15px to the essay body, since it is now on
 * the essay's measure rather than in a narrower cell.
 */

export const metadata: Metadata = {
  title: 'About',
  description:
    'The story behind Sapling: a student-built AI study partner from Boston University, recognized for reimagining how students learn through conversation and a living knowledge graph.',
  alternates: { canonical: '/about' },
};

/**
 * The spine: the key column every row opens with, and the gap after it.
 *
 * 180 rather than the 212 the award rows used to carry. The column is sized by
 * its widest tenant, and its widest tenant is now a mono label ("Where it
 * started", 16 characters at `ARTICLE.eyebrow`, one line here) rather than an
 * award title over a two-line org line. Narrowing it is also what puts the
 * prose on measure: measured both ways in a browser, 212 + 32 leaves a 652px
 * cell reading at a median 66 characters — under the 68 this page wants — and
 * 180 + 28 leaves 688px reading at 71. /wiki sizes its own key column at 164
 * for the same reason and by the same rule.
 */
const KEY_COL = 180;
const COL_GAP = 28;

const HAIRLINE = '1px solid rgba(42,39,31,0.10)';

/**
 * Vertical rhythm, re-derived for rows rather than for a stack.
 *
 * `PARA_GAP` is untouched — it is /news/[slug]'s paragraph rhythm at this
 * size, and paragraphs inside a text cell are still paragraphs. The rest come
 * down, because a hairline per row now does separating work that used to be
 * done by air alone: `BLOCK_GAP` 30 → 22 (/wiki's own value for the same
 * relation, an opening block down to the rows under it), `SECTION_GAP` 64 → 40
 * above Recognition, `BYLINE_GAP` 54 → 44 since `ROW_PAD` already leaves 26
 * under the last award. `MASTHEAD_GAP` is gone with the masthead's own border:
 * the first row carries a `borderTop`, so a masthead rule drew a second
 * hairline 38px above it — the two-stacked-lines trap /terms already fell
 * into. The masthead defers to the row rule and keeps only the space.
 */
const PARA_GAP = 18;
const BLOCK_GAP = 22;
const ROW_PAD = 26;
const SECTION_GAP = 40;
const MASTHEAD_PAD = 34;
const BYLINE_GAP = 44;
const BYLINE_PAD = 36;

/**
 * A section row.
 *
 * Wrapping flex rather than a grid so the two columns collapse to one on a
 * narrow screen: inline styles cannot carry a media query and these pages have
 * no stylesheet of their own. The text cell's 330px basis is the trigger —
 * below ~538px of content width there is no room for both.
 *
 * `rowGap` is set apart from `columnGap` because of the empty key cells. Once
 * wrapped, the gap is vertical, and a single value would spend the full 28px
 * of it on nothing above the two rows whose key is empty — the one place the
 * held-open column would read as a mistake instead of as a hold.
 */
const ROW: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start',
  columnGap: COL_GAP, rowGap: 12, padding: `${ROW_PAD}px 0`, borderTop: HAIRLINE,
};
/**
 * Both cells grow, but the text cell grows a thousand times harder. Side by
 * side that is invisible — the key takes 180.36px of the 896 rather than 180 —
 * and once the row wraps it is the whole point: each cell is alone on its line
 * and stretches to fill it, so a stacked label keeps the same right edge as
 * the prose under it instead of stopping 500px short.
 */
const KEY_CELL: React.CSSProperties = { flex: `1 1 ${KEY_COL}px`, maxWidth: '100%', minWidth: 0 };
const TEXT_CELL: React.CSSProperties = { flex: '999 1 330px', minWidth: 0 };

/**
 * The label a row is filed under. The `paddingTop` is measured, not guessed:
 * it is what puts an 11px mono cap on the same baseline as the 18px serif line
 * beside it (probe spans in both cells, baselines 0.3px apart).
 */
const KEY_LABEL: React.CSSProperties = {
  ...ARTICLE.eyebrow, display: 'block', color: ACCENT,
  letterSpacing: '0.16em', lineHeight: 1.5, paddingTop: 7,
};

const P: React.CSSProperties = { ...ARTICLE.body, margin: 0 };

const AWARD_TITLE: React.CSSProperties = {
  margin: 0, fontFamily: DISPLAY, fontWeight: 500, fontSize: 20,
  lineHeight: 1.25, letterSpacing: '-0.01em', color: INK,
};
/**
 * Muted rather than the accent it wore in the key cell: the green now belongs
 * to the spine, and an org line competing with the label two cells over reads
 * as a second heading rather than as the byline of the award above it.
 */
const AWARD_ORG: React.CSSProperties = {
  margin: '10px 0 0', fontFamily: MONO, fontSize: 11, lineHeight: 1.55,
  letterSpacing: '0.04em', color: MUTED,
};

function Row({ label, delay, gap, children }: {
  label?: string;
  delay: string;
  /** Extra air above the rule, for the one place a section starts. */
  gap?: number;
  children: React.ReactNode;
}) {
  return (
    <div style={{ ...ROW, marginTop: gap, animation: 'fadeUp 700ms ease both', animationDelay: delay }}>
      <div style={KEY_CELL}>{label ? <span style={KEY_LABEL}>{label}</span> : null}</div>
      <div style={TEXT_CELL}>{children}</div>
    </div>
  );
}

export default function AboutPage() {
  return (
    <CompanionShell current="/about">
      <div>
        <header style={{ paddingBottom: MASTHEAD_PAD }}>
          <h1 style={{ ...ARTICLE.title, margin: 0, animation: 'fadeUp 700ms ease both' }}>
            About Sapling
          </h1>
        </header>

        <Row label="What it is" delay="80ms">
          <div style={{ display: 'flex', flexDirection: 'column', gap: PARA_GAP }}>
            <p style={P}>
              <strong style={{ color: '#1a1814', fontWeight: 600 }}>Sapling</strong>{' '}
              is an AI-powered study companion built by students, for students. We believe that learning
              shouldn&#8217;t be passive. It should adapt to you, challenge you, and show you exactly
              where you stand.
            </p>

            <p style={P}>
              At its core, Sapling maps your understanding as a live knowledge graph that grows with
              every session, quiz, and document you interact with. Paired with an AI tutor that can
              reason with you Socratically, explain concepts directly, or flip the table and have you
              teach back, Sapling meets you wherever you are in your learning journey.
            </p>
          </div>
        </Row>

        <Row label="Where it started" delay="160ms">
          <p style={P}>
            Sapling was born out of a hackathon and built by a team of four students who were
            frustrated with static study tools that don&#8217;t actually know what you know. We
            wanted something that feels less like a flashcard app and more like a study partner
            who&#8217;s always prepared.
          </p>
        </Row>

        {/* The lead-in keeps its colon, so it is set as a sentence at the
            scaled weight rather than promoted to a display heading — and it
            stays in the text cell for the same reason, reading into the
            bullets it introduces rather than standing off to the side of them. */}
        <Row delay="240ms">
          <p style={{ margin: 0, fontFamily: SERIF, fontSize: 17, lineHeight: 1.45, fontWeight: 600, color: INK }}>
            What makes Sapling different:
          </p>
          <ul style={{ listStyle: 'none', padding: 0, margin: `${BLOCK_GAP}px 0 0`, display: 'flex', flexDirection: 'column', gap: 13 }}>
            {ABOUT_DIFFERENTIATORS.map((d) => (
              <li key={d} style={{ ...P, display: 'flex', gap: 12 }}>
                <span style={{ color: ACCENT, flex: '0 0 auto' }}>&#8226;</span>
                <span>{d}</span>
              </li>
            ))}
          </ul>
        </Row>

        <Row label="Still building" delay="320ms">
          <p style={P}>
            Sapling is actively developed and we&#8217;re always building. If something&#8217;s
            broken or you have an idea, there&#8217;s a feedback button in the navbar and we
            actually read those.
          </p>
        </Row>

        {ABOUT_AWARDS.map((a, i) => (
          <Row
            key={a.title}
            label={i === 0 ? 'Recognition' : undefined}
            delay={a.delay}
            gap={i === 0 ? SECTION_GAP : undefined}
          >
            <p style={AWARD_TITLE}>{a.title}</p>
            <p style={AWARD_ORG}>{a.org}</p>
            <p style={{ ...P, marginTop: PARA_GAP }}>{a.body}</p>
          </Row>
        ))}

        <div style={{ marginTop: BYLINE_GAP, paddingTop: BYLINE_PAD, borderTop: HAIRLINE, fontSize: 13, lineHeight: 1.6, color: MUTED }}>
          Built by Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez &#169; 2026
        </div>
      </div>
    </CompanionShell>
  );
}
