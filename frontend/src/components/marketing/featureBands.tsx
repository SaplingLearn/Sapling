/**
 * The three feature bands' content (#344 step 2).
 *
 * Lives here rather than in `(public)/page.tsx` — that file is already ~860
 * lines and owns the hero's canvas, three RAF loops and two modals; three
 * paragraphs of marketing copy do not belong in it. `page.tsx` mounts these by
 * index.
 *
 * The three bands are ONE arc — material in → practice → retention — not three
 * disconnected pitches, and band 3 is the closing claim that runs into the CTA.
 * Reordering them breaks the argument, so the order here is load-bearing.
 *
 * `surfaceSide` is DERIVED from position rather than written down per band.
 * The spec's requirement is "surfaces alternate sides"; encoding that as an
 * invariant means inserting or removing a band cannot silently produce two
 * bands with their surface on the same side, and it gives the unit test
 * something real to assert instead of three restated literals.
 */
import type { FeatureBandProps } from './FeatureBand';
import QuizSurface from './surfaces/QuizSurface';
import ReviewSurface from './surfaces/ReviewSurface';
import UploadSurface from './surfaces/UploadSurface';

const CONTENT: Array<Omit<FeatureBandProps, 'surfaceSide'>> = [
  {
    id: 'upload',
    eyebrow: 'Universal Upload',
    headline: 'Drop in syllabi, textbooks, or notes.',
    body: 'Sapling reads them, pulls out every concept, and maps them onto your graph — you do not tag anything.',
    surface: <UploadSurface />,
  },
  {
    id: 'quiz',
    eyebrow: 'Adaptive Quizzes',
    headline: 'Questions that re-tune to your level, in real time.',
    body: 'They press where you are strong and meet you where you struggle, so the next question is always the one worth asking.',
    surface: <QuizSurface />,
  },
  {
    id: 'review',
    eyebrow: 'Spaced Repetition',
    headline: 'Knows what to review, and when.',
    body: 'Spacing your reviews is what moves a concept from short-term to long-term memory. Sapling handles the scheduling; you just show up.',
    surface: <ReviewSurface />,
  },
];

/**
 * Band `i` puts its surface on the left for even `i`, the right for odd — so
 * the eye crosses the page between bands instead of running down one gutter.
 */
export const FEATURE_BANDS: FeatureBandProps[] = CONTENT.map((band, i) => ({
  ...band,
  surfaceSide: i % 2 === 0 ? 'left' : 'right',
}));
