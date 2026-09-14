'use client';

/**
 * The eight feature-lab demos, keyed by `LabKind`.
 *
 * Ported from `FeatureLab.dc.html`, the separate design component the landing
 * page mounts inside the lab's right pane via `<dc-import>`. The source is one
 * class with ~20 state keys and eight `sc-if` branches; here each demo owns
 * its own state, so switching tools through the rail unmounts one and mounts
 * the next with a clean slate — which is what the source's shared-state
 * version only appeared to do.
 */

import type { LabKind } from '@/lib/landing/content';
import { CalendarDemo } from './CalendarDemo';
import { CardsDemo } from './CardsDemo';
import { GradesDemo } from './GradesDemo';
import { GuideDemo } from './GuideDemo';
import { LabShell } from './LabShell';
import { NotesDemo } from './NotesDemo';
import { QuizDemo } from './QuizDemo';
import { RoomsDemo } from './RoomsDemo';
import { TutorDemo } from './TutorDemo';

/** The fake address shown in the demo's chrome, per tool. */
const ROUTES: Record<LabKind, string> = {
  quiz: 'sapling.app / learn — quiz',
  cards: 'sapling.app / study — flashcards',
  notes: 'sapling.app / notetaker',
  guide: 'sapling.app / study — guide',
  rooms: 'sapling.app / social',
  grades: 'sapling.app / gradebook / MA 242',
  calendar: 'sapling.app / calendar',
  tutor: 'sapling.app / learn — tutor',
};

const DEMOS: Record<LabKind, () => React.JSX.Element> = {
  quiz: QuizDemo,
  cards: CardsDemo,
  notes: NotesDemo,
  guide: GuideDemo,
  rooms: RoomsDemo,
  grades: GradesDemo,
  calendar: CalendarDemo,
  tutor: TutorDemo,
};

export function FeatureLabDemo({ kind }: { kind: LabKind }) {
  const Demo = DEMOS[kind] ?? QuizDemo;
  return (
    // keyed so switching tools remounts rather than carrying state across
    <LabShell route={ROUTES[kind] ?? 'sapling.app'}>
      <Demo key={kind} />
    </LabShell>
  );
}
