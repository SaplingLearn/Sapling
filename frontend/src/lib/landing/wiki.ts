import {
  WIKI_ACHIEVEMENT_TERMS, WIKI_CALENDAR_SPECS, WIKI_CLASS_TERMS, WIKI_DATA_FACTS,
  WIKI_FLASHCARD_NOTES, WIKI_FLASHCARD_RATINGS, WIKI_GRADE_NOTES, WIKI_GRAPH_TERMS,
  WIKI_GUIDE_SPECS, WIKI_LETTERS, WIKI_MASTERY_FORMULA, WIKI_MASTERY_MOVES, WIKI_MODES,
  WIKI_NOTE_SPECS, WIKI_ONBOARDING_SPECS, WIKI_PIPELINE, WIKI_PROGRESS_TERMS,
  WIKI_QUIZ_SPECS, WIKI_ROOM_SPECS, WIKI_TIERS, WIKI_UPLOAD_SPECS,
} from './companionContent';

/**
 * The wiki, one page per topic.
 *
 * It was one page of eighteen sections behind a scrollspy rail, which made
 * every definition a scroll away from every other and gave none of them an
 * address you could send someone. Each topic is now its own route at
 * /wiki/<slug>, and /wiki is the index of them.
 *
 * A page is data: a title, the group it files under, the sentence its index
 * card carries, and an ordered list of blocks. The blocks are the row shapes
 * the single page already had — `terms`, `specs`, `facts`, `steps` and plain
 * `prose` carry almost everything, and the rest are the handful of shapes
 * that need their own layout (a swatch, an equation, a three-column table).
 * Adding a topic should mean adding an entry here and picking shapes, not
 * writing a page.
 *
 * The content itself stays in companionContent.ts beside the other companion
 * pages' copy, with the source each value was checked against.
 */

export type WikiGroup = 'Learn' | 'Capture' | 'Semester' | 'Together' | 'You';

/** The order the index and the rail present the groups in, which is how the
 *  product is organised: learn, capture, the semester, the people, and you. */
export const WIKI_GROUPS: readonly WikiGroup[] = ['Learn', 'Capture', 'Semester', 'Together', 'You'];

type Rows<T> = readonly T[];

export type WikiBlock =
  | { kind: 'prose'; text: string }
  | { kind: 'terms'; rows: Rows<{ term: string; def: string }> }
  | { kind: 'specs'; rows: Rows<{ label: string; value: string; note: string }> }
  | { kind: 'facts'; items: Rows<string> }
  | { kind: 'steps'; rows: Rows<{ num: string; title: string; body: string }> }
  | { kind: 'tiers'; rows: Rows<{ name: string; range: string; dot: string; meaning: string }> }
  | { kind: 'formula'; text: string }
  | { kind: 'moves'; rows: Rows<{ source: string; value: string; note: string }> }
  | { kind: 'modes'; rows: Rows<{ name: string; def: string }> }
  | { kind: 'ratings'; rows: Rows<{ label: string; key: string; tone: string }> }
  | { kind: 'letters'; rows: Rows<{ letter: string; min: string }> }
  | { kind: 'dataFacts'; rows: Rows<{ fact: string; detail: string }> };

export interface WikiPage {
  slug: string;
  title: string;
  group: WikiGroup;
  /** One sentence for the index card and the page's meta description. */
  summary: string;
  /** The paragraph under the page title. */
  lede?: string;
  blocks: readonly WikiBlock[];
  /**
   * The section id this topic had on the single-page wiki, so an old
   * /wiki#<id> link still lands on the right page (see WikiIndex.tsx).
   */
  legacyId?: string;
}

export const WIKI_PAGES: readonly WikiPage[] = [
  // ── Learn ────────────────────────────────────────────────────────────────
  {
    slug: 'knowledge-graph', title: 'Knowledge graph', group: 'Learn', legacyId: 'graph',
    summary: 'Nodes, edges and course roots: how your concepts are drawn and joined.',
    lede: 'One node per concept in a course, joined by an edge when the two are related. Each course anchors its own cluster, so a semester reads as a handful of constellations rather than one tangle.',
    blocks: [{ kind: 'terms', rows: WIKI_GRAPH_TERMS }],
  },
  {
    slug: 'mastery-tiers', title: 'Mastery tiers', group: 'Learn', legacyId: 'mastery',
    summary: 'The four tiers a 0.00 – 1.00 mastery score falls into, and what reads them.',
    lede: 'Every node carries a mastery score from 0.00 to 1.00, drawn as a ring around it. Four tiers are derived from that score, and they are what the tier filters, the dashboard counts, and the quiz generator all read.',
    blocks: [{ kind: 'tiers', rows: WIKI_TIERS }],
  },
  {
    slug: 'how-mastery-moves', title: 'How mastery moves', group: 'Learn', legacyId: 'deltas',
    summary: 'The arithmetic behind a mastery change, and the things that do not move it.',
    lede: 'Mastery moves on demonstrated understanding, not time spent, which means several things you might expect to move it do not. Every change is appended to your graph with a reason attached.',
    blocks: [
      { kind: 'formula', text: WIKI_MASTERY_FORMULA },
      { kind: 'prose', text: 'That is one quiz. Around seventeen correct answers in a row take a concept from nothing to mastered, roughly three or four full quizzes.' },
      { kind: 'moves', rows: WIKI_MASTERY_MOVES },
    ],
  },
  {
    slug: 'progress-stats', title: 'Progress stats', group: 'Learn', legacyId: 'progress',
    summary: 'Streaks, learning velocity and the other numbers that describe movement.',
    lede: 'The numbers around the app that describe your movement rather than your position.',
    blocks: [{ kind: 'terms', rows: WIKI_PROGRESS_TERMS }],
  },
  {
    slug: 'adaptive-quizzes', title: 'Adaptive quizzes', group: 'Learn', legacyId: 'quizzes',
    summary: 'Lengths, difficulties, limits and timeouts the quiz screen is built from.',
    lede: 'A quiz is written fresh each time from your graph, weighted toward the concepts you have mastered least. These are the values the quiz screen builds its selectors from, so it can never offer one the server refuses.',
    blocks: [{ kind: 'specs', rows: WIKI_QUIZ_SPECS }],
  },
  {
    slug: 'tutor-modes', title: 'Tutor modes', group: 'Learn', legacyId: 'tutor',
    summary: 'Socratic, Expository and TeachBack: three stances on the same concept.',
    lede: 'Three ways to work the same concept. You pick one per conversation, and it changes the tutor’s stance rather than its knowledge; all three read your graph and the documents you uploaded.',
    blocks: [{ kind: 'modes', rows: WIKI_MODES }],
  },

  // ── Capture ──────────────────────────────────────────────────────────────
  {
    slug: 'uploads', title: 'Uploads', group: 'Capture', legacyId: 'uploads',
    summary: 'The file types and sizes Sapling accepts, and how it reads them.',
    lede: 'What Sapling accepts, and what it does to read it.',
    blocks: [{ kind: 'specs', rows: WIKI_UPLOAD_SPECS }],
  },
  {
    slug: 'ingestion', title: 'Ingestion', group: 'Capture', legacyId: 'ingestion',
    summary: 'The steps a file goes through after you drop it in.',
    lede: 'What happens to a file after you drop it in. These steps stream to your screen as they run, so you can always see why a concept or a date exists.',
    blocks: [{ kind: 'steps', rows: WIKI_PIPELINE }],
  },
  {
    slug: 'notetaker', title: 'Notetaker', group: 'Capture', legacyId: 'notes',
    summary: 'Autosave, summaries, concept extraction and quizzes from your own notes.',
    lede: 'Your own writing, turned into concepts on the same tree everything else feeds.',
    blocks: [{ kind: 'specs', rows: WIKI_NOTE_SPECS }],
  },
  {
    slug: 'flashcards', title: 'Flashcards', group: 'Capture', legacyId: 'flashcards',
    summary: 'The three ratings, and what each one actually does.',
    lede: 'Flip a card and rate how it went. Three ratings, and what each one actually does.',
    blocks: [
      { kind: 'ratings', rows: WIKI_FLASHCARD_RATINGS },
      { kind: 'facts', items: WIKI_FLASHCARD_NOTES },
    ],
  },
  {
    slug: 'study-guide', title: 'Study guide', group: 'Capture', legacyId: 'guide',
    summary: 'One exam-ready review per course, built from what you uploaded.',
    lede: 'One exam-ready review per course, assembled from what you have already uploaded.',
    blocks: [{ kind: 'specs', rows: WIKI_GUIDE_SPECS }],
  },

  // ── Semester ─────────────────────────────────────────────────────────────
  {
    slug: 'syllabus-and-calendar', title: 'Syllabus and calendar', group: 'Semester', legacyId: 'calendar',
    summary: 'How one syllabus upload becomes assignments, dates and grade weights.',
    lede: 'The one document every course hands you, turned into a working plan. One upload shows up in three places.',
    blocks: [{ kind: 'specs', rows: WIKI_CALENDAR_SPECS }],
  },
  {
    slug: 'grade-scale', title: 'Grade scale', group: 'Semester', legacyId: 'grades',
    summary: 'The default letter bands, how a course grade is computed, and GPA.',
    lede: 'Your gradebook tracks the grade that goes on your transcript. These are the letter bands a percentage maps onto by default.',
    blocks: [
      { kind: 'letters', rows: WIKI_LETTERS },
      { kind: 'facts', items: WIKI_GRADE_NOTES },
    ],
  },

  // ── Together ─────────────────────────────────────────────────────────────
  {
    slug: 'study-rooms', title: 'Study rooms', group: 'Together', legacyId: 'rooms',
    summary: 'Joining, messaging, and exactly what a room sees of you.',
    lede: 'A chat scoped to the people studying the same thing, next to a comparison of where you each are.',
    blocks: [{ kind: 'specs', rows: WIKI_ROOM_SPECS }],
  },
  {
    slug: 'class-intelligence', title: 'Class intelligence', group: 'Together', legacyId: 'class',
    summary: 'The anonymised, class-wide layer, and how far it reaches today.',
    lede: 'The anonymised, class-wide layer. It is the least-finished thing in Sapling, so here is exactly how far it reaches.',
    blocks: [{ kind: 'terms', rows: WIKI_CLASS_TERMS }],
  },

  // ── You ──────────────────────────────────────────────────────────────────
  {
    slug: 'onboarding', title: 'Onboarding', group: 'You', legacyId: 'onboarding',
    summary: 'The short path from signed in to on the tree.',
    lede: 'The short path from signed in to on the tree.',
    blocks: [{ kind: 'specs', rows: WIKI_ONBOARDING_SPECS }],
  },
  {
    slug: 'achievements', title: 'Achievements', group: 'You', legacyId: 'achievements',
    summary: 'What you earn as you go, and the cosmetics it unlocks.',
    lede: 'What you earn as you go, and what it unlocks.',
    blocks: [{ kind: 'terms', rows: WIKI_ACHIEVEMENT_TERMS }],
  },
  {
    slug: 'your-data', title: 'Your data', group: 'You', legacyId: 'privacy',
    summary: 'What is encrypted, what is not, and how to export or delete it.',
    blocks: [{ kind: 'dataFacts', rows: WIKI_DATA_FACTS }],
  },
];

export function getWikiPage(slug: string): WikiPage | undefined {
  return WIKI_PAGES.find((p) => p.slug === slug);
}

/** Pages filed under a group, in registry order. */
export function wikiPagesIn(group: WikiGroup): WikiPage[] {
  return WIKI_PAGES.filter((p) => p.group === group);
}

/**
 * Reading order: groups in `WIKI_GROUPS` order, pages in registry order
 * within each. The previous/next links follow this, so the wiki still reads
 * front to back for anyone who wants to.
 */
export const WIKI_ORDER: readonly WikiPage[] = WIKI_GROUPS.flatMap(wikiPagesIn);

export function wikiNeighbours(slug: string): { prev?: WikiPage; next?: WikiPage } {
  const i = WIKI_ORDER.findIndex((p) => p.slug === slug);
  if (i < 0) return {};
  return { prev: WIKI_ORDER[i - 1], next: WIKI_ORDER[i + 1] };
}

/** Old single-page section id → the page that topic lives on now. */
export function wikiSlugForLegacyId(id: string): string | undefined {
  return WIKI_PAGES.find((p) => p.legacyId === id)?.slug;
}

/**
 * Every word a page puts on screen, for the search.
 *
 * The single page searched its own rendered DOM. The other pages are not in
 * the document any more, so the text is taken from the blocks instead —
 * still one copy of the content, just read from the data rather than the
 * markup. `dot` and `tone` are CSS declarations, not words.
 */
export function wikiSearchText(page: WikiPage): string {
  const parts: string[] = [page.title, page.group, page.summary, page.lede ?? ''];
  const walk = (v: unknown, key?: string) => {
    if (key === 'dot' || key === 'tone' || key === 'kind') return;
    if (typeof v === 'string') parts.push(v);
    else if (Array.isArray(v)) v.forEach((x) => walk(x));
    else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) walk(x, k);
  };
  page.blocks.forEach((b) => walk(b));
  return parts.filter(Boolean).join(' ');
}

/** What the client-side search and contents need of a page: no blocks, just
 *  the words, so nothing but strings crosses the server/client boundary. */
export interface WikiEntry {
  slug: string;
  title: string;
  group: WikiGroup;
  summary: string;
  text: string;
}

export function wikiEntries(): WikiEntry[] {
  return WIKI_ORDER.map((p) => ({
    slug: p.slug, title: p.title, group: p.group, summary: p.summary, text: wikiSearchText(p),
  }));
}
