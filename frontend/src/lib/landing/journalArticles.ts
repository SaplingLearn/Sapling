/**
 * The Sapling Journal — every post, and the only place one is described.
 *
 * This table is the source of truth for the whole journal: the landing cards
 * (`POSTS` in content.ts), the /news index (`NEWS_POSTS` in
 * companionContent.ts) and the article pages at /news/[slug] all derive from
 * it. Before #601 those three surfaces each carried their own hand-typed tag,
 * date and read time, and had already drifted apart.
 *
 * Two consequences worth knowing:
 *   - `publishedAt` is an ISO day and `dateLabel` is the one formatter. Never
 *     print a date any other way.
 *   - `time` is not a field. Read time is derived from the body by
 *     `readTime`, so it cannot disagree with the article it describes.
 *
 * Bodies are typed blocks rather than JSX so the article page owns all
 * presentation and the content stays greppable plain text — which is also
 * what lets /news search the prose, not just the excerpt.
 */

export type ArticleBlock =
  | { t: 'h2'; text: string }
  | { t: 'p'; text: string }
  | { t: 'ul'; items: string[] };

/** Motif illustrations live in components/journal/ArticleArt.tsx. */
export type ArtMotif = 'graph' | 'spacing' | 'teachback' | 'syllabus' | 'canopy';

/**
 * Every post has artwork. A post with no photograph gets a drawn motif
 * rather than the empty tinted panel /news used to render (#601).
 */
export type ArticleArt =
  | { kind: 'photo'; src: string }
  | { kind: 'motif'; motif: ArtMotif };

/** Filter bucket on /news. Must be a `NEWS_FILTERS` key. */
export type ArticleCategory = 'founding' | 'perspective' | 'product' | 'release';

export interface JournalArticle {
  slug: string;
  /** Display label on the card and article header. */
  tag: string;
  cat: ArticleCategory;
  /** ISO `YYYY-MM-DD`. Every rendered date derives from this. */
  publishedAt: string;
  art: ArticleArt;
  title: string;
  /** One-line standfirst under the title — the card excerpt, verbatim. */
  deck: string;
  body: ArticleBlock[];
}

export const JOURNAL_ARTICLES: JournalArticle[] = [
  {
    slug: 'the-map-we-keep-for-ourselves',
    tag: 'Perspective',
    cat: 'perspective',
    publishedAt: '2026-09-03',
    art: { kind: 'motif', motif: 'canopy' },
    title: 'The map we keep for ourselves',
    deck:
      'Sapling maps what you know so nothing important falls out of your head between weeks. It turns out the four people building it had exactly the same problem.',
    body: [
      {
        t: 'p',
        text:
          'Sapling exists because things fall out of your head between weeks. You understood recursion in week three; by the midterm it is in there somewhere and you cannot find the door. Our answer is a map — every concept in your course, what you have actually shown you know, and honest holes where you have not.',
      },
      {
        t: 'p',
        text:
          'Building it, we hit the same problem from the other side. There are four of us, working in parallel on different parts of one codebase, often with an AI agent doing a share of the typing. Someone settles a question on a Tuesday — why the tutor cites the slide it drew from, why mastery is allowed to go down — and by Thursday the person who needs that reasoning is three files away and it is gone. Not disputed. Just gone.',
      },
      { t: 'h2', text: 'So we built ourselves one' },
      {
        t: 'p',
        text:
          'It is called Canopy, which is not an accident: a sapling grows up into one. It holds the team’s docs, the decisions we have settled, the roadmap, and a running log of what each of us shipped — one place, and everyone reads it. The habit around it is the same one we ask of you. Orient before you start: pull what the team already knows about the thing you are about to touch. Record when you learn something: write back what the work actually changed, not what you remember of it a week later.',
      },
      {
        t: 'p',
        text:
          'The part we did not expect to carry the most weight is that every entry says how settled it is. Anyone can propose — the agents propose constantly — but only a person can promote. So the map can hold work in progress without work in progress quietly becoming fact.',
      },
      {
        t: 'ul',
        items: [
          'Live — settled. Build on it.',
          'Staged — proposed by whoever just did the work, waiting on a human to confirm it.',
          'Draft — a question we have argued about and not yet closed.',
        ],
      },
      { t: 'h2', text: 'The version that did not work' },
      {
        t: 'p',
        text:
          'Our first attempt was the obvious one: notes in a folder in the repo. It failed in the most ordinary way — nobody updated them. Months on, half of what they claimed was wrong: bugs written up as open that we had already fixed, fixes written up as shipped that never landed. A stale map is worse than no map, because you trust it. We lost a day re-checking every line before admitting the real bug was that writing things down had been optional.',
      },
      {
        t: 'p',
        text:
          'So we are not asking you to take on faith a habit we do not keep ourselves. Reading the map before you start and writing to it the moment you learn something beats trusting that you will remember having understood. We do it every day on our own work. Sapling is that same habit pointed at your courses, with the writing part done for you.',
      },
    ],
  },
  {
    slug: 'why-we-built-sapling',
    tag: 'Founding',
    cat: 'founding',
    publishedAt: '2026-06-12',
    art: { kind: 'photo', src: '/journal-founding.png' },
    title: 'Why we built Sapling',
    deck:
      'Four students, one library table, and a nagging question: what if AI made you understand more, not less? The origin story, missteps included.',
    body: [
      {
        t: 'p',
        text:
          'There is a table on the third floor of the library that the four of us kept ending up at. Different majors, different courses, same ritual: laptops open, a chatbot in one tab, slides in another, and a quiet feeling that we were getting worse at learning while looking more productive than ever.',
      },
      {
        t: 'p',
        text:
          'The question that started Sapling was not "how do we use AI to study faster." It was uglier and more honest: why did handing in good work feel so different from actually knowing anything? One of us aced a problem set and then could not explain a single answer at that table two days later. The tools were doing the understanding, and we were doing the submitting.',
      },
      { t: 'h2', text: 'The missteps' },
      {
        t: 'p',
        text:
          'Our first build, over a hackathon weekend, was exactly what you would guess: a wrapper around a chat model with a nicer prompt. It answered questions about your course. It was also useless in the way that matters — it knew nothing about you, so it explained eigenvalues the same way on day one and day ninety, whether you were lost or bored.',
      },
      {
        t: 'p',
        text:
          'The second attempt was a flashcard app with AI-generated cards. Better, but it had the same hole in the middle: it tracked what you had seen, not what you understood. A deck does not know that your trouble with recursion is really trouble with the call stack, one concept upstream.',
      },
      {
        t: 'p',
        text:
          'The thing that finally felt right was embarrassingly simple to say out loud: model the course as a graph of concepts, watch how a student actually performs against each one, and let everything else — quizzes, review, tutoring — read and write that one shared map. Not a feature. The spine everything hangs off.',
      },
      { t: 'h2', text: 'What Sapling became' },
      {
        t: 'p',
        text:
          'Today you drop in your course materials — the syllabus, the slides, your notes — and Sapling builds that map. Every quiz answer, every flashcard rating, every tutoring exchange moves a mastery score on a real concept. The tutor asks before it tells, cites the slide it drew from, and never just hands over the solution. When you upload, your whole class benefits: one person’s lecture notes fill gaps in another’s slides.',
      },
      {
        t: 'p',
        text:
          'We built it from our own frustration, for courses we were actually taking, and we tested every mechanic on ourselves first. Some of what we shipped came straight from getting it wrong — TeachBack exists because explaining things badly at that library table turned out to be the fastest way to find out what we did not know.',
      },
      { t: 'h2', text: 'Where it goes from here' },
      {
        t: 'p',
        text:
          'Sapling is in beta, free, and currently exclusive to Boston University students while we get the foundations right. The journal you are reading is where we will keep thinking in public — about the product, about what we are learning about learning, and about the missteps still to come. There will be some. That is rather the point.',
      },
    ],
  },
  {
    slug: 'ai-shouldnt-do-your-homework',
    tag: 'Perspective',
    cat: 'perspective',
    publishedAt: '2026-05-04',
    art: { kind: 'photo', src: '/journal-ai-homework.png' },
    title: 'AI shouldn’t do your homework',
    deck:
      'Our line in the sand on AI and education: guidance over answers, process over shortcuts, and why "just give me the solution" is the wrong deal.',
    body: [
      {
        t: 'p',
        text:
          'Every AI study tool eventually faces the same request: just give me the answer. It is the easiest feature in the world to ship and the most corrosive. We want to be plain about where we stand, because the whole product is built on this line.',
      },
      {
        t: 'p',
        text:
          'The deal on offer from answer-machines looks great and is terrible. You trade the struggle — the only part of an assignment that changes you — for the artifact, which changes nothing. The problem set was never the point. The version of you who could do the problem set was the point. Skip the first and you simply do not get the second, and no transcript line will cover for that in an interview, a lab, or the exam room where the chatbot cannot follow.',
      },
      { t: 'h2', text: 'Incentives, not lectures' },
      {
        t: 'p',
        text:
          'We are not interested in moralizing at students; we are students. The honest framing is incentives. Tools that print answers are optimized for tonight’s deadline. Learning compounds on a different timescale, and a tool that actually serves you has to be loyal to the longer one — even when that is less satisfying at 1 a.m.',
      },
      { t: 'h2', text: 'What that means in the product' },
      {
        t: 'ul',
        items: [
          'The tutor guides instead of solving. In Socratic mode it asks the question that gets you to the answer; it will not shortcut the arrival.',
          'Everything is grounded in your course. Answers cite the slide or page they came from, so you can check the source instead of trusting a vibe.',
          'TeachBack inverts the desk entirely: you explain, and Sapling’s job is to find the step you skipped.',
          'Mastery moves on demonstrated understanding — quiz performance, explanations, recall over time. Reading something twice does not make the graph greener.',
        ],
      },
      {
        t: 'p',
        text:
          'None of this makes us the fun tool on the night before a deadline. We can live with that. The bet behind Sapling is that understanding compounds, that students actually want it, and that software can be on the side of the longer timescale without pretending the deadline does not exist. Guidance over answers. Process over shortcuts. That is the deal we think is worth taking.',
      },
    ],
  },
  {
    slug: 'how-the-knowledge-graph-works',
    tag: 'Product',
    cat: 'product',
    publishedAt: '2026-04-18',
    art: { kind: 'motif', motif: 'graph' },
    title: 'How the knowledge graph works',
    deck:
      'Nodes, edges, and mastery scores: how a semester of studying becomes a living map, and why the cross-unit edges matter most.',
    body: [
      {
        t: 'p',
        text:
          'Ask your transcript what you know and it answers with five letters. Ask Sapling and it answers with a map: every concept in your course as a node, every relationship as an edge, and a mastery score on each node that moves as you study. This is how that map actually gets built.',
      },
      { t: 'h2', text: 'Nodes come from your materials' },
      {
        t: 'p',
        text:
          'When you upload a syllabus, slides, or notes, Sapling reads them and extracts the concepts your professor actually teaches — not a generic textbook ontology. A data structures course yields nodes like binary search trees, rotations, hashing, dynamic programming; each node keeps pointers back to the documents it came from. That grounding is why the tutor can cite the exact slide behind an answer.',
      },
      { t: 'h2', text: 'Edges come from structure — and from you' },
      {
        t: 'p',
        text:
          'Some edges are in the material itself: rotations rest on binary search trees, memoization rests on recursion. Others are drawn from behavior — when a quiz question exercises two concepts, when a note links ideas, when the tutor walks you from one topic into its neighbor. The graph you end the semester with is partly the course’s anatomy and partly a record of how you moved through it.',
      },
      {
        t: 'p',
        text:
          'The edges we care about most cross unit boundaries. Courses are taught in chapters, but understanding is not chaptered — the moment hashing connects to complexity analysis in your head is a genuine event in your learning, and it deserves to be a genuine edge in your map. Those cross-unit links are the difference between a table of contents and a mental model.',
      },
      { t: 'h2', text: 'Mastery is the color' },
      {
        t: 'p',
        text:
          'Every node carries a mastery score from 0 to 100, rendered as a tier: mastered, learning, struggling, unexplored. The score moves on evidence — a quiz answer, a flashcard rating, a TeachBack explanation — and every change is kept as an append-only event, so your history is a trail, not a single overwritten number. Mastery can go down. Discovering a gap is information, and the map should say so.',
      },
      { t: 'h2', text: 'What the graph drives' },
      {
        t: 'ul',
        items: [
          'Quiz targeting: questions aim at the concepts where mastery is low or stale, and every answer writes a delta back to the node it tested.',
          'Review scheduling: spaced repetition draws cards from the lowest-mastery concepts first, walking edges to catch the upstream ideas a weak node depends on.',
          'Tutoring: a session on one concept pulls its neighbors into context, so explanations meet you where your actual gaps are.',
          'Study guides: pick an exam, and the guide assembles from your own library, weighted toward your weakest reachable nodes.',
        ],
      },
      {
        t: 'p',
        text:
          'One map, read and written by everything. That is the whole architecture, and it is the reason a semester of studying in Sapling leaves you with something your transcript never captures: not a grade, but the shape of what you know — including the honest holes in it.',
      },
    ],
  },
  {
    slug: 'teachback-is-live',
    tag: 'Release',
    cat: 'release',
    publishedAt: '2026-03-22',
    art: { kind: 'motif', motif: 'teachback' },
    title: 'TeachBack is live',
    deck:
      'The mode that flips the desk. You explain the concept, Sapling names the step you skipped, and mastery counts for more than reading.',
    body: [
      {
        t: 'p',
        text:
          'There is an old finding that survives every replication fight: explaining something is a brutally honest test of whether you understand it. Reading feels like knowing. Explaining exposes the seams. TeachBack, live for everyone today, is that test as a tutor mode.',
      },
      { t: 'h2', text: 'How it works' },
      {
        t: 'p',
        text:
          'Pick a concept and explain it — as if to a classmate who missed the lecture. Sapling maps your explanation against the concept’s actual pieces and comes back with a verdict per piece: what you covered correctly, what stayed vague, and what went missing entirely. Explaining an AVL rotation, you might nail the direction, wave at subtree reattachment, and skip which node becomes the new root. It will tell you exactly that, and then ask you to re-explain.',
      },
      {
        t: 'p',
        text:
          'Mastery moves on the result — and yes, it can move down. If your explanation reveals a gap the graph did not know about, the honest response is a lower score and a review card, not a participation trophy. A gap found in TeachBack is a gap that will not find you in the exam.',
      },
      {
        t: 'p',
        text:
          'TeachBack joins Socratic and Expository as the third way to work with the tutor. Same graph, same grounding in your course materials, opposite direction of travel: this time, you are the one doing the teaching. It is the mode we use most ourselves, and the fastest one at turning "I read it" into "I know it."',
      },
    ],
  },
  {
    slug: 'what-spacing-actually-buys-you',
    tag: 'Research',
    cat: 'product',
    publishedAt: '2026-02-09',
    art: { kind: 'motif', motif: 'spacing' },
    title: 'What spacing actually buys you',
    deck:
      'Why ten minutes, one day, and four days are the intervals we shipped, and what happened when we tested longer gaps on our own courses.',
    body: [
      {
        t: 'p',
        text:
          'Spaced repetition has a century of evidence behind it and a dirty secret in practice: the schedule that maximizes retention per review is not the schedule real students keep. This is the story of how we picked Sapling’s intervals — ten minutes, one day, four days — and what we learned running the alternatives on our own coursework first.',
      },
      { t: 'h2', text: 'The theory, briefly' },
      {
        t: 'p',
        text:
          'Memory decays along a forgetting curve, and each successful recall at the edge of forgetting flattens the next decay. Classic algorithms chase that edge with expanding intervals that quickly stretch to weeks. Mathematically elegant; the per-review payoff is real.',
      },
      { t: 'h2', text: 'What happened when we tried it' },
      {
        t: 'p',
        text:
          'We ran long-interval scheduling against our own courses for a stretch of the fall. Retention per review was better, exactly as the literature promises. Everything around it was worse. Three-week gaps drifted past exam dates, queues went stale and then intimidating, and a stale queue does not get opened — the best interval in the world buys nothing at zero reviews. Semesters are fourteen weeks; the schedule has to live inside that shape.',
      },
      {
        t: 'p',
        text:
          'So the shipped intervals map to the three honest answers you can give a card. Forgot: ten minutes, because a failed recall wants another attempt while the correction is fresh. Hard: one day, long enough to force real retrieval, short enough that a shaky concept stays warm. Easy: four days, near the practical edge of forgetting inside a course schedule with exams on it.',
      },
      { t: 'h2', text: 'Spacing with a map' },
      {
        t: 'p',
        text:
          'The part classic flashcard apps cannot do: Sapling schedules against the graph, not just the clock. Review draws from your lowest-mastery concepts first and walks edges to pull in the upstream ideas a weak node depends on — because re-drilling memoization is wasted motion if the actual hole is recursion. Spacing decides when you see a card; the graph decides which card deserves the slot.',
      },
      {
        t: 'p',
        text:
          'Ten minutes, a day, four days. Not the intervals of a lab study — the intervals of a semester someone actually finishes. Sapling schedules; you show up.',
      },
    ],
  },
  {
    slug: 'syllabus-to-semester-in-one-upload',
    tag: 'Release',
    cat: 'release',
    publishedAt: '2026-01-06',
    art: { kind: 'motif', motif: 'syllabus' },
    title: 'Syllabus to semester in one upload',
    deck:
      'Calendar extraction went from a manual paste to a single drop. Every exam, pset, and quiz dated and synced before week one is over.',
    body: [
      {
        t: 'p',
        text:
          'Until now, getting your semester into Sapling meant pasting syllabus sections by hand and fixing the dates it guessed wrong. As of this release: drop the syllabus in once, and the semester assembles itself.',
      },
      {
        t: 'p',
        text:
          'Sapling reads the document, finds every dated commitment — exams, problem sets, quizzes, project milestones — and puts each one on your calendar with the right date, synced to Google Calendar if you have it connected. Grading weights come along for the ride: the same pass reads how your grade is composed, so the gradebook’s categories are ready before your first score exists.',
      },
      {
        t: 'p',
        text:
          'One upload also seeds the rest: concepts extracted for your knowledge graph, the document indexed for the tutor to cite. The version of week one where you transcribe a PDF into three different apps is over. Drop it once, get the semester back.',
      },
    ],
  },
];

export function getArticle(slug: string): JournalArticle | undefined {
  return JOURNAL_ARTICLES.find((a) => a.slug === slug);
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

/**
 * The one date format: `12 JUN 2026`.
 *
 * Reads the ISO string directly instead of going through `Date`, which parses
 * a bare `YYYY-MM-DD` as UTC midnight and would print the previous day for
 * anyone west of Greenwich.
 */
export function dateLabel(publishedAt: string): string {
  const [year, month, day] = publishedAt.split('-');
  return `${day} ${MONTHS[Number(month) - 1]} ${year}`;
}

/** Every block flattened to prose — read-time input, and what /news searches. */
export function articleText(body: ArticleBlock[]): string {
  return body.map((block) => (block.t === 'ul' ? block.items.join(' ') : block.text)).join(' ');
}

const WORDS_PER_MINUTE = 200;

/** Read time derived from the article itself, floored at a minute. */
export function readTime(body: ArticleBlock[]): string {
  const words = articleText(body).split(/\s+/).filter(Boolean).length;
  return `${Math.max(1, Math.round(words / WORDS_PER_MINUTE))} MIN`;
}
