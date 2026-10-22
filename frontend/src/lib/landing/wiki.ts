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
 * Adding a topic means adding an entry here and picking shapes, not writing
 * a page.
 *
 * The wiki promises "every value here is the one the product actually uses",
 * so every number below is copied from the code that serves it, not from a
 * product doc, and each page names the files it was checked against. A claim
 * that could only be sourced from a doc is not here: the page is worth less
 * with a wrong definition on it than with a missing one. That includes the
 * unflattering ones — where a control does less than its label says, the
 * wiki says what it does.
 *
 * Content last checked against main on 2026-10-22.
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

/** The tier swatches. Warmer than the landing's XTIER — these sit on the
 *  paper palette, not the dark act ground, so they are deliberately distinct
 *  values rather than a shared token. */
const TIER = { mastered: '#5a7834', learning: '#c89b5e', struggling: '#b25855', unexplored: '#9a9a9a' };

export const WIKI_PAGES: readonly WikiPage[] = [
  // ── Learn ────────────────────────────────────────────────────────────────

  /* services/graph_service.py (add_node, apply_graph_update, course roots);
     db/migrations/0023_graph_integrity.sql; lib/graph/nodeStyle.ts. */
  {
    slug: 'knowledge-graph', title: 'Knowledge graph', group: 'Learn', legacyId: 'graph',
    summary: 'Nodes, edges and course roots: how your concepts are drawn and joined.',
    lede: 'One node per concept in a course, joined by an edge when the two are related. Each course anchors its own cluster, so a semester reads as a handful of constellations rather than one tangle.',
    blocks: [
      { kind: 'terms', rows: [
        { term: 'Node', def: 'One concept in one course, carrying a mastery score from 0.00 to 1.00. Every concept you touch anywhere in Sapling resolves to a node.' },
        { term: 'Course root', def: 'The labelled hub at the centre of a course’s cluster, named with the course code and title. Every concept in the course wires back to it, and its score is the average of theirs.' },
        { term: 'Edge', def: 'A link between two concepts, drawn thicker the stronger it is. The only links Sapling writes today are “related” ones, made when you add a concept by hand while another is selected; uploads, notes and the tutor add concepts without linking them.' },
        { term: 'Dedup', def: '“Linear Regression”, “linear regression” and a double-spaced copy all resolve to one node within a course, so re-running an extract never splits a concept in two.' },
        { term: 'Scope', def: 'Your graph is yours, and it keys to the course rather than the term or section, so it carries across semesters.' },
      ] },
      { kind: 'facts', items: [
        'In the graph, colour is the course, size grows with mastery, and opacity marks the tier, with Unexplored the faintest.',
      ] },
    ],
  },

  /* components/screens/Tree.tsx; components/graph/KnowledgeGraph*.tsx;
     services/graph_service.py (add_node, delete_node). */
  {
    slug: 'using-the-tree', title: 'Using the tree', group: 'Learn',
    summary: 'Search, filter, inspect, add and delete concepts, and switch between 2D and 3D.',
    lede: 'The Tree screen is the full-size knowledge graph with tools around it: search, filters, a panel for any concept you select, and a way to add or remove concepts yourself.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Search', value: 'Concept and course names', note: 'Filters the graph as you type.' },
        { label: 'Filters', value: 'Tier · course', note: 'Links to a filtered-out concept are hidden along with it.' },
        { label: '2D / 3D', value: 'Toggle, top left', note: 'Remembered per browser and shared by every graph on screen. 3D needs WebGL2; without it the toggle is disabled and the graph stays 2D.' },
        { label: 'Zoom (2D)', value: '0.4× – 3×', note: 'Scroll to zoom towards the pointer and drag the background to pan. A dragged node rejoins the layout when you let go.' },
        { label: 'Fullscreen', value: 'Esc to exit', note: 'Picking a concept in fullscreen closes it and opens that concept’s panel.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Concept panel', def: 'Mastery as a whole percent, its tier, and when you last studied it.' },
        { term: 'Learn this', def: 'Opens the tutor on the concept in Socratic mode.' },
        { term: 'Quick quiz', def: 'A quiz on that concept that brings you back to this panel. On a course root it proposes concepts within the course.' },
        { term: 'Recent quizzes', def: 'Your last five completed quizzes on the concept, with score and mastery change. They cannot be reopened.' },
        { term: 'Sessions', def: 'Up to four tutor sessions whose topic matches the concept’s name, each one resumable.' },
      ] },
      { kind: 'facts', items: [
        'Add concept appears once one course is selected. A name you already have merges into that node; a new one starts Unexplored and links to the selected concept, or to the course root.',
        'Delete concept takes two clicks and removes the concept and every link to it. Course roots cannot be deleted.',
        'With one course selected, a Topic checklist button opens that course’s outline above the graph.',
      ] },
    ],
  },

  /* backend/config.py::get_mastery_tier — MASTERY_MASTERED_MIN 0.75 /
     MASTERY_LEARNING_MIN 0.45 / MASTERY_STRUGGLING_MIN 0.1. */
  {
    slug: 'mastery-tiers', title: 'Mastery tiers', group: 'Learn', legacyId: 'mastery',
    summary: 'The four tiers a 0.00 – 1.00 mastery score falls into, and what reads them.',
    lede: 'Every node carries a mastery score from 0.00 to 1.00. Four tiers are derived from that score, and they are what the tier filters, the dashboard counts and the topic checklist all read.',
    blocks: [
      { kind: 'tiers', rows: [
        { name: 'Mastered', range: '0.75 – 1.00', dot: `background:${TIER.mastered};`, meaning: 'The top tier. Achievements that count mastered concepts count these, and nothing decays a concept out of it with time.' },
        { name: 'Learning', range: '0.45 – 0.74', dot: `background:${TIER.learning};`, meaning: 'Partly there. Still eligible for the recommendations on your dashboard.' },
        { name: 'Struggling', range: '0.10 – 0.44', dot: `background:${TIER.struggling};`, meaning: 'Some evidence, not much yet. Every concept climbing from zero passes through here, so it does not only mean repeated misses.' },
        { name: 'Unexplored', range: '0.00 – 0.09', dot: `background:${TIER.unexplored};`, meaning: 'Planted but never demonstrated. Every new concept lands here at 0.00.' },
      ] },
      { kind: 'prose', text: 'The tutor’s map rail uses friendlier labels for the same four bands: Mastered, In progress, Needs work and Not started.' },
    ],
  },

  /* services/quiz_config.py MASTERY_DELTA_PER_CORRECT / _PER_WRONG;
     agents/tools/graph.py::MasteryUpdate.mastery_delta; routes/quiz.py submit. */
  {
    slug: 'how-mastery-moves', title: 'How mastery moves', group: 'Learn', legacyId: 'deltas',
    summary: 'The arithmetic behind a mastery change, and the things that do not move it.',
    lede: 'Mastery moves on demonstrated understanding, not time spent, which means several things you might expect to move it do not. Only two things move a score: submitting a quiz, and the tutor’s update after a turn.',
    blocks: [
      { kind: 'formula', text: 'after = clamp(before + correct × 0.03 − wrong × 0.02, 0, 1)' },
      { kind: 'prose', text: 'That is one quiz. Twenty-five correct answers take a new concept from 0.00 to Mastered: a perfect 3-question quiz adds 0.09, and 3 of 5 adds 0.05.' },
      { kind: 'moves', rows: [
        { source: 'Quiz answer', value: '+0.03 / −0.02', note: 'Summed over the quiz and applied once, when you submit it; a question left unanswered counts as wrong. Mastery is earned faster than it is lost.' },
        { source: 'Tutor turn', value: '−0.10 … +0.30', note: 'The range is enforced on each change the tutor proposes, so no single message can set a score outright. Good answers over several turns can still reach Mastered.' },
        { source: 'New concept', value: '0.00', note: 'Whatever planted it, a concept arrives unexplored. Extracting one you already have leaves its score alone.' },
        { source: 'Left or discarded quiz', value: 'no change', note: 'Mastery moves only on submit, and an abandoned or discarded attempt can never be submitted.' },
        { source: 'Notes and note chat', value: 'no change', note: 'They can plant new concepts at 0.00 but never move a score.' },
        { source: 'Flashcard rating', value: 'no change', note: 'Rating a card records the rating. It does not write to the concept the card tests.' },
        { source: 'Assignment score', value: 'no change', note: 'Your gradebook tracks the grade on your transcript. It runs alongside your graph rather than into it.' },
      ] },
    ],
  },

  /* services/streak_service.py; services/graph_service.py (mastery events,
     times_studied); lib/quiz/proposals.ts. */
  {
    slug: 'progress-stats', title: 'Progress stats', group: 'Learn', legacyId: 'progress',
    summary: 'Streaks, mastery history and the other numbers that describe movement.',
    lede: 'The numbers that describe your movement rather than your position.',
    blocks: [
      { kind: 'terms', rows: [
        { term: 'Streak', def: 'Consecutive UTC calendar days on which you submitted a quiz, ended a tutor session, or had the tutor move a concept’s mastery. Uploads, notes and flashcards do not count. Miss a day and it restarts at 1 the next time you study, though the old number shows until then.' },
        { term: 'Mastery event', def: 'Every quiz submit and tutor mastery change is appended as a timestamped change with a reason, never written over a running total. The full history is kept, though no screen shows it yet.' },
        { term: 'Times studied', def: 'How many times a quiz submit or a tutor update has touched a concept; one quiz counts once, whatever its length. It is what puts “not studied yet” on Quiz home.' },
      ] },
    ],
  },

  /* components/screens/Dashboard.tsx; routes/calendar.py upcoming;
     services/graph_service.py recommendations; lib/quiz/proposals.ts. */
  {
    slug: 'dashboard', title: 'Dashboard', group: 'Learn',
    summary: 'Your home screen: the whole graph, your streak, where you left off, and what is due.',
    lede: 'The dashboard is the first item in the nav. It shows your knowledge graph alongside your streak, recent tutor sessions, upcoming assignments and a way into the concepts that still need work. The Layout setting picks between two versions: the default sidebar layout, and a top-nav layout that adds a weekly strip and Learn next.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Graph', value: 'Every course, or one semester', note: 'Click a concept to open it in the tutor in Socratic mode. Fullscreen opens a larger copy, and Esc closes it.' },
        { label: 'Streak', value: 'Current run, in days', note: 'The Personal best line under it shows the current streak too; the dashboard does not track a longest one.' },
        { label: 'Where you left off', value: 'Last 3 tutor sessions', note: 'Each one resumes the session where it stopped.' },
        { label: 'Upcoming', value: 'Next 4 dated assignments', note: 'Due today or later, tagged in days, or in hours once under 24. Undated assignments are left off.' },
        { label: 'Review what’s due', value: 'Concepts not yet mastered', note: 'Due means Learning, Struggling or Unexplored, not a review schedule. It opens a queue of quizzes on your weakest five.' },
        { label: 'My courses', value: 'Mastered share per course', note: 'Mastered concepts over all of that course’s concepts, with the bar splitting the rest by tier.' },
        { label: 'Learn next', value: 'Up to 3 · top-nav layout', note: 'Your lowest-mastery concepts outside Mastered, so never-studied ones come first. Each opens the tutor in Socratic mode.' },
        { label: 'This week', value: 'Mon – Sun · top-nav layout', note: 'A day is marked when a concept was last studied on it, so studying the same concept again moves its mark to the newer day.' },
      ] },
      { kind: 'facts', items: [
        'The graph, the Mastered count and Learn next follow the semester chosen in Courses & Semesters. Upcoming and Where you left off always cover every course.',
      ] },
    ],
  },

  /* services/quiz_config.py (served at GET /api/quiz/config); routes/quiz.py;
     services/quiz_repetition.py; services/exam_proximity.py; lib/quiz/. */
  {
    slug: 'adaptive-quizzes', title: 'Adaptive quizzes', group: 'Learn', legacyId: 'quizzes',
    summary: 'Lengths, difficulties, limits and the rules a quiz is generated under.',
    lede: 'A quiz is written fresh for one concept each time, from your course material and your history on it. These are the values the quiz screen builds its selectors from, so it can never offer one the server refuses.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Scope', value: 'One concept per quiz', note: 'Practise a course, or Review what’s due, runs up to five single-concept quizzes in a row, weakest first.' },
        { label: 'Length', value: '3, 5, or 10', note: 'Ten is a hard ceiling. A practise-what-you-missed quiz is exactly as long as the number you missed.' },
        { label: 'Difficulty', value: 'Easy · Medium · Hard · Adaptive', note: 'Adaptive hands the choice to the generator, which picks each question’s level and reports back the mix it settled on.' },
        { label: 'Question format', value: 'Choice · Short · Numeric · Algebra · Mixed', note: 'Multiple choice is the default. No answer is marked by AI; see Answer formats for the rules.' },
        { label: 'Feedback', value: 'As you go · At the end', note: 'At the end is the default. Either way each answer is marked and saved as you move on.' },
        { label: 'Course grounding', value: 'Up to 5 passages', note: 'Matched to the concept from your course’s indexed material. Each question says whether it used course material, the catalog only, or general knowledge.' },
        { label: 'Repetition', value: 'Last 15 questions', note: 'Questions from your recent quizzes on the concept are named to the generator as ones not to repeat. That is an instruction, not a filter; only repeats inside one quiz are removed outright.' },
        { label: 'Exam nearby', value: 'Within 14 days', note: 'When an exam, midterm or final in the course is 14 days away or less, questions lean toward what an exam would test.' },
        { label: 'Short quizzes', value: 'Topped up once', note: 'Questions that fail checks are dropped, and if more than a third go, one retry refills them. A quiz that still comes up short says how many were ready.' },
        { label: 'Generation limit', value: '8 per 5 minutes', note: 'Sized for a person comparing difficulties or retaking a concept, not for a loop. A generation that fails on Sapling’s side gives the slot back.' },
        { label: 'Generation timeout', value: '90 seconds', note: 'Past this you are told to try again rather than left on a spinner.' },
        { label: 'Daily ceiling', value: 'Rolling 24 hours', note: 'There is a cap on AI usage per student, checked when a quiz needs generating. It frees up over the day rather than at midnight.' },
        { label: 'Abandoned after', value: '24 hours', note: 'Counted from your last answer. Discarding a quiz from Quiz home closes it at once.' },
      ] },
      { kind: 'facts', items: [
        'Practise what you missed re-serves the exact questions you got wrong on a finished quiz, with nothing new generated for them.',
        'Ask about this opens the tutor over a question you have answered, without ending the quiz. The conversation stays in your tutor sessions.',
        'After you submit, a short digest of your mistakes is updated in the background, and the next quiz on that concept reads it.',
        'Leaving keeps your answers; the quiz waits on Quiz home to be resumed.',
        'Marking a question as confusing shows only on your screen. It is not recorded or reported yet.',
      ] },
    ],
  },

  /* services/quiz_grading.py; services/quiz_algebra.py; agents/quiz.py;
     models/__init__.py (answer length). */
  {
    slug: 'answer-formats', title: 'Answer formats', group: 'Learn',
    summary: 'How each question format is answered, and the exact rules that mark it right.',
    lede: 'A quiz can ask for a choice, a word, a number or an expression. None of them is marked by AI: every answer is checked against the stored answer by fixed rules, the same way every time.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Multiple choice', value: '4 options, one correct', note: 'Marked by which option you chose, nothing else.' },
        { label: 'Short answer', value: 'Exact after tidying', note: 'Case, extra spaces, surrounding punctuation and one leading “a”, “an” or “the” are ignored. It must then match the answer or one of up to eight accepted alternatives; misspellings are not forgiven.' },
        { label: 'Numeric', value: 'Exact value', note: 'Fractions, decimals, mixed numbers (1 1/2), 1,000-style separators, percentages and scientific notation are read as numbers and compared exactly. Units are rejected, and 0.33 is not 1/3.' },
        { label: 'Algebra', value: 'Equivalent expression', note: 'Single-letter variables, + − * / ^, brackets and implicit multiplication, with whole powers from −8 to 8. 2(x + 1) and 2x + 2 both count.' },
        { label: 'Mixed', value: 'Choice and short answer', note: 'Numeric and algebra questions join the mix only where the course material supports maths.' },
        { label: 'Answer length', value: '2,000 characters', note: 'The most a written answer can hold.' },
      ] },
      { kind: 'facts', items: [
        'Your first answer to a question is the one that counts. Answering it again returns the original verdict.',
        'Percentages are read as fractions: 50% is 0.5, so “50%” does not match an answer of 50.',
        'Algebra does not accept functions, roots, equations or scientific notation. With single-letter variables, 2e+1 reads as 2·e + 1.',
        'A written question the generator produces with answer choices attached, or with a key that cannot be read, is dropped before you see it.',
      ] },
    ],
  },

  /* agents/chat_tutor.py; routes/learn.py; components/chat/. */
  {
    slug: 'tutor-modes', title: 'Tutor modes', group: 'Learn', legacyId: 'tutor',
    summary: 'Socratic, Expository and Teach-back: three stances on the same concept.',
    lede: 'Three ways to work the same concept. You pick one per conversation, and it changes the tutor’s stance rather than its knowledge: all three read the same course material and the same graph.',
    blocks: [
      { kind: 'modes', rows: [
        { name: 'Socratic', def: 'Asks one focused question a turn and holds hints back until you have tried; every reply ends with a question. The default, and the mode Learn this, the dashboard and a quiz’s Ask about this all open in.' },
        { name: 'Expository', def: 'Explains the concept directly: an overview, then the detail, then an example or worked problem.' },
        { name: 'Teach-back', def: 'You explain the concept and it listens, then says what was right, what was missing and any misconception, ending on one question at your weakest spot.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Graded work', def: 'No mode hands over the final answer to homework, problem sets, labs or take-home exams. Concepts, definitions and worked examples with different numbers are fair game.' },
        { term: 'Fast · Smart', def: 'Fast, the default, runs a lighter model; Smart runs a stronger one for harder reasoning, more slowly. The choice is remembered on this device.' },
        { term: 'Hint', def: 'Asks for a small clue without the answer.' },
        { term: 'I’m confused', def: 'Asks for a re-explanation with a different analogy.' },
        { term: 'Skip', def: 'Moves on to the next recommended concept.' },
        { term: 'Switching mode', def: 'Applies from your next message in the same session.' },
      ] },
    ],
  },

  /* routes/learn.py (context assembly); services/rag_service.py;
     services/graph_context.py; agents/tools/chat_context.py. */
  {
    slug: 'what-the-tutor-reads', title: 'What the tutor reads', group: 'Learn',
    summary: 'Exactly what the tutor is given each turn, what it can look up, and what it never sees.',
    lede: 'Every message you send arrives with context put together for that turn, and the tutor can look further on its own. All of it is scoped to you and to the course the session belongs to.',
    blocks: [
      { kind: 'steps', rows: [
        { num: '01', title: 'The conversation', body: 'The whole session so far is sent again with every message.' },
        { num: '02', title: 'The course catalog', body: 'The official catalog entry, when the course has a course code.' },
        { num: '03', title: 'Course material', body: 'Up to five passages that match what you just wrote, from the course’s shared material and your own private uploads.' },
        { num: '04', title: 'Your graph', body: 'Up to twelve of your concepts in the course with their scores and links: the ones your message mentions first, then your weakest.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Your documents', def: 'It can search the summaries and concept notes of your own uploads for the course, five at most. Documents you deleted are left out.' },
        { term: 'Your progress', def: 'How many of your concepts in the course sit in each tier, and your average.' },
        { term: 'Neighbourhood', def: 'Scores, tiers and links around a named concept, at most two such reads a turn.' },
      ] },
      { kind: 'facts', items: [
        'It never reads another student’s private uploads, or material from a different course.',
        'Your notes, flashcards, gradebook and past quizzes are not among its sources. Send to tutor from a note opens a session on the note’s title; the note’s text does not go with it.',
        'Mastery changes from a turn land on your tree while the reply is still streaming.',
      ] },
    ],
  },

  /* services/topic_checklist_service.py; agents/topic_checklist.py;
     components/TopicChecklistPanel.tsx. */
  {
    slug: 'topic-checklist', title: 'Topic checklist', group: 'Learn',
    summary: 'A course outline built from the catalog and your materials, with each topic’s status and what to review first.',
    lede: 'Pick one course on the Tree and open Topic checklist for an outline of what that course covers, built only from evidence Sapling holds for it. Each topic gets a status from your graph and your own checkmarks. Checking a topic records that you studied it; it never changes your mastery.',
    blocks: [
      { kind: 'steps', rows: [
        { num: '01', title: 'Gather evidence', body: 'The course description and catalog entry, your documents for that course and semester, its exams and quizzes, and the concepts and prerequisites already on your tree. Never another student’s uploads.' },
        { num: '02', title: 'Outline', body: 'Up to 60 topics and subtopics, each citing the sources behind it. The model is told to use only that evidence, not its memory of the course.' },
        { num: '03', title: 'Mark', body: 'Status and priority are worked out from your graph and checkmarks each time you open it, not by the model.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Not started', def: 'You have not checked it, and no studied concept on your tree matches its name.' },
        { term: 'In progress', def: 'Studied recently, and not yet at 0.75.' },
        { term: 'Needs review', def: 'Studied, but its concept is below 0.45, or it was last studied or checked 7 or more days ago.' },
        { term: 'Mastered', def: 'Studied recently, with its concept at 0.75 or above. A checkmark on its own never makes a topic Mastered.' },
        { term: 'Prioritize', def: 'Shown when a linked exam or quiz is due within 7 days and the topic is not mastered, when its mastery is weak, or when a prerequisite on your tree is weak and unchecked.' },
      ] },
      { kind: 'specs', rows: [
        { label: 'Evidence cap', value: '30 documents · 60,000 characters', note: 'Each source is cut at 10,000 characters. When anything is cut, the checklist warns that it may not cover every detail.' },
        { label: 'Upcoming', value: 'Next 30 days', note: 'Exams and quizzes due in that window are listed. One is linked to a topic only when your material explicitly ties them.' },
        { label: 'Rebuilds', value: 'When your evidence changes', note: 'A new upload, assessment or concept marks the outline stale and opening it rebuilds. A change in mastery alone does not.' },
        { label: 'Rebuild limit', value: '6 per minute', note: 'A build that runs past 60 seconds or fails keeps the previous outline and asks you to try again.' },
        { label: 'Semester', value: 'Current or most recent', note: 'Unless you pick one. Checkmarks are kept per semester, so taking the course again starts a fresh list.' },
      ] },
      { kind: 'facts', items: [
        'A topic matches a concept by name, ignoring case and spacing. Only a matched topic shows a mastery percentage.',
        'A checkmark restarts the topic’s 7-day review clock. Unchecking removes it.',
        'Prioritized topics sort first, then by the soonest linked due date, then by how central the topic is to the course.',
        'Only assignments typed Exam or Quiz count as assessments. Items a syllabus adds through the Library are typed Other, so they do not appear here.',
        'With no evidence at all there is no checklist; you are asked to upload course material.',
      ] },
    ],
  },

  // ── Capture ──────────────────────────────────────────────────────────────

  /* routes/documents.py ALLOWED_EXTENSIONS / MAX_FILE_SIZE;
     services/extraction_service.py; components/DocumentUploadModal.tsx. */
  {
    slug: 'uploads', title: 'Uploads', group: 'Capture', legacyId: 'uploads',
    summary: 'The file types and sizes Sapling accepts, and how it reads them.',
    lede: 'What Sapling accepts, and what it does to read it.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'File types', value: 'PDF · DOCX · PPTX', note: 'Anything else is refused at upload. Photos and images are not accepted here.' },
        { label: 'Size limit', value: '100 MB', note: 'Per file. A larger one is rejected before any processing starts.' },
        { label: 'Files at once', value: 'Up to 5', note: 'Each is processed on its own, under the course you pick for it. You can enrol in a course from the same dialog.' },
        { label: 'Text extraction', value: 'Text layer, then OCR', note: 'A PDF’s own text is used when it has any. Only one with almost none is OCR’d, by Docling with Tesseract as the fallback. Word and PowerPoint files are read directly.' },
        { label: 'Pages read', value: '50, or 20 by OCR', note: 'A PDF’s text layer is read for its first 50 pages; one that has to be OCR’d, for its first 20. Later pages are not read.' },
        { label: 'Time limit', value: '4 minutes', note: 'Past this the browser stops waiting and marks the file aborted, with a Retry button.' },
        { label: 'Retry, Re-analyze', value: 'Runs again', note: 'Both start a fresh request through the whole pipeline. A failed upload saved nothing; re-analysing a finished one adds a second copy to your library.' },
        { label: 'Category', value: 'Editable afterwards', note: 'Change it in the upload dialog once the file is done. It relabels the document and re-runs nothing.' },
        { label: 'Original file', value: 'Not kept', note: 'Sapling keeps the text it read, the summary and the concepts. There is no copy of the file to download or preview.' },
      ] },
    ],
  },

  /* routes/documents.py (the SSE progress events); agents/classifier.py,
     summary.py, concept_extraction.py; services/document_indexing.py,
     chunker.py, index_sweeper.py. */
  {
    slug: 'ingestion', title: 'Ingestion', group: 'Capture', legacyId: 'ingestion',
    summary: 'The steps a file goes through after you drop it in, and the indexing after.',
    lede: 'What happens to a file after you drop it in. The steps stream to your screen as they run, so you can always see why a concept or a date exists.',
    blocks: [
      { kind: 'steps', rows: [
        { num: '01', title: 'Extract text', body: 'Before progress starts, the file’s text is read: a PDF’s text layer if it has one, OCR if not. With under 50 readable characters the upload is refused as unreadable, and nothing is saved.' },
        { num: '02', title: 'Classify', body: 'Sapling decides what kind of document it is (syllabus, lecture notes, slides, reading, assignment, study guide or other), and whether it is course material, your own notes or your own work.' },
        { num: '03', title: 'Summarise and extract', body: 'Three jobs run side by side: a 3–5 sentence summary, up to 30 concepts each with a short note, and, for anything that reads as a syllabus, its assignments and grading breakdown.' },
        { num: '04', title: 'Update graph', body: 'The concepts are added to the course’s tree as unexplored nodes. One you already have is skipped and keeps its mastery.' },
        { num: '05', title: 'Save', body: 'The document lands in your library with its summary and concepts. A syllabus’s dated assignments go onto your calendar; undated ones are dropped.' },
      ] },
      { kind: 'prose', text: 'After the document is saved, its text is split into passages and indexed so the tutor and quiz generator can search it. This runs in the background: no progress is shown for it.' },
      { kind: 'specs', rows: [
        { label: 'Passage size', value: '50 – 400 words', note: 'Split at paragraph breaks. Readings, assignments and study guides are cut into overlapping 200-word windows instead.' },
        { label: 'Retries', value: '3 attempts', note: 'A failed attempt is retried in the background, about ten minutes apart. After the third it stops until it is re-indexed by hand.' },
        { label: 'Who can search it', value: 'Shared or private', note: 'Course material from a student who shares goes into the course’s pool; everything else is searched only for you. See Shared class material.' },
      ] },
    ],
  },

  /* components/screens/Library.tsx; routes/documents.py (list, scan,
     delete); agents/concept_scan.py. */
  {
    slug: 'library', title: 'Library', group: 'Capture',
    summary: 'Where your uploaded documents live, with their summaries, concepts and the concept scan.',
    lede: 'Every document you upload lands in your Library, filed under its course with the summary and concepts Sapling extracted. It holds what was read from the file, not the file itself.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Opening one', value: 'Summary and key concepts', note: 'Each concept with its note. The file itself is not kept, so there is nothing to open or download.' },
        { label: 'Search', value: 'File name and summary', note: 'The document’s own text is not searched.' },
        { label: 'Type filter', value: 'Six, plus All', note: 'Lecture notes, syllabus, reading, slides, study guide and assignment. A document classified as other appears only under All.' },
        { label: 'Courses', value: 'One row each, with a count', note: 'Uncategorized holds any document whose course could not be matched.' },
        { label: 'Semesters', value: 'All of them', note: 'The Library lists every document you have uploaded, whatever the term.' },
        { label: 'Upload', value: 'Needs a course', note: 'The button stays off until you are enrolled in at least one.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Scan', def: 'Reads one document’s summary and concepts and adds up to 15 concepts the course’s tree does not have yet, as unexplored nodes. It never removes or renames one.' },
        { term: 'Course scan', def: 'The same from the course name and the concepts already on your tree, with no document. It appears when one course is selected.' },
        { term: 'Delete', def: 'Takes two clicks. The document leaves your library, study guides, flashcards and checklist; see Your data for what stays.' },
      ] },
      { kind: 'facts', items: [
        'Scanned concepts are Title-Case ideas. Assignment titles, week labels, page numbers and admin items are left out.',
        'A scan that finds nothing new adds nothing and says so. A scan that fails also adds nothing.',
      ] },
    ],
  },

  /* routes/notes.py; agents/note_*.py; app/(shell)/notetaker/page.tsx;
     services/notes_service.py. */
  {
    slug: 'notetaker', title: 'Notetaker', group: 'Capture', legacyId: 'notes',
    summary: 'Autosave, summaries, concept extraction, quick questions and quizzes from your own notes.',
    lede: 'Your own writing, turned into concepts on the same tree everything else feeds.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Autosave', value: '800 ms', note: 'Typing settles, then the note saves. Switching notes or closing the tab flushes it immediately.' },
        { label: 'Summarise', value: '2 – 4 sentences', note: 'Faithful to what you wrote, including the questions you left yourself. The newest summary replaces the last.' },
        { label: 'Extract concepts', value: 'up to 15', note: 'Title-Case ideas only, not assignment titles or page numbers. Each is merged onto your graph and linked back to the note.' },
        { label: 'Concepts', value: 'On request', note: 'Nothing is picked up as you type. Concepts come from Extract concepts, or from linking one from your graph yourself.' },
        { label: 'Quick questions', value: 'One at a time', note: 'Answered from this note and your course material, without the earlier questions in the thread. Switching notes clears it, and nothing is saved.' },
        { label: 'Generate quiz', value: 'Weakest linked concept', note: 'Needs at least one linked concept, and brings you back to the note afterwards.' },
        { label: 'Send to tutor', value: 'Title as topic', note: 'Opens the tutor on the note’s course with its title as the topic. The note’s text does not go with it.' },
        { label: 'Delete', value: 'One click', note: 'There is no confirmation. The concepts the note planted stay on your graph.' },
      ] },
    ],
  },

  /* routes/flashcards.py::rate_card (writes times_reviewed, last_rating,
     last_reviewed_at and nothing else); components/screens/Study.tsx;
     components/flashcards/; services/flashcard_import_service.py. */
  {
    slug: 'flashcards', title: 'Flashcards', group: 'Capture', legacyId: 'flashcards',
    summary: 'The three ratings and what they do, generating cards, and importing a deck.',
    lede: 'Flip a card and rate how it went. Three ratings, and what each one actually does.',
    blocks: [
      { kind: 'ratings', rows: [
        { label: 'Forgot', key: '1', tone: `color:${TIER.struggling};` },
        { label: 'Hard', key: '2', tone: `color:${TIER.learning};` },
        { label: 'Easy', key: '3', tone: `color:${TIER.mastered};` },
      ] },
      { kind: 'facts', items: [
        'A rating is recorded against the card: your latest rating, the time, and one more on its review count.',
        'There is no review schedule yet. A card you forgot does not come back sooner than one you found easy; cards come newest first and loop back after the last.',
        'Rating needs the answer showing. Space flips the card; 1, 2 and 3 rate it and move on.',
        'Generate cards makes five at a time from your weakest concepts. Studying a card writes nothing back to them.',
      ] },
      { kind: 'specs', rows: [
        { label: 'Import from', value: 'Paste · File · URL · AI · Photo', note: 'Files can be .csv, .tsv, .txt, .json, .xlsx or Anki .apkg. A URL must be a public Quizlet set, which Quizlet sometimes blocks.' },
        { label: 'File limit', value: '5 MB', note: 'Per file, for uploads and photos.' },
        { label: 'AI cards', value: '10, 25 or 50', note: 'From pasted text or one library document, read through its summary and concept notes. Auto means 25.' },
        { label: 'AI limit', value: '5 per minute', note: 'Shared by AI cards, Clean up with AI and cloze cards.' },
        { label: 'Duplicates', value: 'Skipped', note: 'A card whose front is within three characters of one you already have in that course is left out, and the count is reported.' },
        { label: 'Reverse cards', value: 'Optional', note: 'Adds a back-to-front copy of every card.' },
      ] },
    ],
  },

  /* routes/study_guide.py; agents/study_guide.py; services/exam_proximity.py;
     routes/documents.py (guide invalidation on upload). */
  {
    slug: 'study-guide', title: 'Study guide', group: 'Capture', legacyId: 'guide',
    summary: 'One exam-ready review per course and exam, built from what you uploaded.',
    lede: 'One exam-ready review per exam, assembled from what you have already uploaded for the course.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Built from', value: 'Your document library', note: 'The summary and concept notes of each document you uploaded to that course for the semester in view, not the full text and not your notes. Not from your graph: a guide does not yet lean harder on your weak concepts.' },
        { label: 'Exams listed', value: 'Exam type or exam-like title', note: 'An assignment typed Exam, or one whose title contains exam, midterm, final or quiz, so “Final project” is listed too.' },
        { label: 'Contents', value: 'Overview, then topics', note: 'A 2–3 sentence overview of the exam, then topics, each with why it matters and 3–5 points to understand.' },
        { label: 'Scope', value: 'Per course, per exam', note: 'Saved once generated, so coming back to it is instant.' },
        { label: 'Regenerate', value: 'On demand', note: 'Rebuilds from scratch. Uploading to the course does this for you: its saved guides are cleared and rebuild the next time you open them.' },
        { label: 'No material', value: 'Generated anyway', note: 'With nothing uploaded for the course, the guide works from the exam’s title and date alone.' },
      ] },
    ],
  },

  // ── Semester ─────────────────────────────────────────────────────────────

  /* services/academics.py; services/graph_service.py (add/remove course);
     lib/useActiveSemester.ts; components/ManageCoursesModal.tsx. */
  {
    slug: 'semesters-and-courses', title: 'Semesters and courses', group: 'Semester',
    summary: 'How a course attaches to a term, what All semesters shows, and what removing a course takes with it.',
    lede: 'Every course you add belongs to one term. Your knowledge graph follows the course itself, while the gradebook and calendar belong to the term you take it in.',
    blocks: [
      { kind: 'terms', rows: [
        { term: 'Current term', def: 'The term whose dates include today. Between terms, the most recent one counts.' },
        { term: 'All semesters', def: 'The default. The dashboard and study screens show every course you have, from any term, until you pick one.' },
        { term: 'Picking a term', def: 'Choose one in Courses & Semesters and those screens narrow to it. The choice is kept in this browser, not on your account.' },
      ] },
      { kind: 'specs', rows: [
        { label: 'Adding a course', value: 'Into the selected term', note: 'Or into the current term under All semesters. Only terms you already have a course in appear to choose from.' },
        { label: 'Retaking', value: 'Not supported', note: 'A course you have in any term cannot be added again, and you are told which term it is in.' },
        { label: 'Removing a course', value: 'Gradebook goes, graph stays', note: 'Its gradebook categories and assignments go with it, off your calendar too. Its concepts stay on your tree.' },
        { label: 'Course planner', value: 'Coming soon', note: 'Planning future semesters and mapping prerequisites is not built yet, and the screen says so.' },
      ] },
    ],
  },

  /* routes/documents.py (syllabus save); services/calendar_service.py;
     services/assignment_dedupe.py; routes/calendar.py; routes/gradebook.py. */
  {
    slug: 'syllabus-and-calendar', title: 'Syllabus and calendar', group: 'Semester', legacyId: 'calendar',
    summary: 'How a syllabus upload becomes calendar dates and grade weights, and what Google Calendar gets.',
    lede: 'The one document every course hands you, turned into a working plan.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'From a syllabus', value: 'Dated deliverables', note: 'Every deliverable the syllabus gives a calendar date is saved straight to your calendar, up to 50. One given only as “Week 4” or “before the midterm” is left out rather than guessed.' },
        { label: 'Re-upload', value: 'Same title, same day', note: 'An assignment already on your calendar with the same title and due date is skipped. Rename or move one and the new syllabus adds it as a second entry.' },
        { label: 'Grading categories', value: 'Reviewed in the gradebook', note: 'Upload the syllabus from the gradebook and you check the weight buckets it found, such as Exams 40%, before saving. They must total 100%, and saving replaces the course’s categories.' },
        { label: 'Views', value: 'Month · Week · Day · Table', note: 'The table is where you edit an assignment’s title, date or type, delete it, or export rows as CSV.' },
        { label: 'Google Calendar', value: 'Push only', note: 'Sync and Export send assignments to Google as all-day events on the due date. Nothing comes back from Google, and an assignment edited after it was pushed is not updated there.' },
        { label: 'What Google gets', value: 'Title and notes', note: 'Each event is titled with the course code and assignment, with your notes as its description. Notes are encrypted in Sapling; the copy in Google is not.' },
        { label: 'Undated items', value: 'Kept, never pushed', note: 'An assignment with no date shows as “No date” in the table and is skipped by Sync and Export.' },
        { label: 'Connection', value: 'Asked at sign-in', note: 'Signing in with Google also asks for calendar access. Disconnect deletes the stored tokens; your next sign-in stores them again.' },
      ] },
    ],
  },

  /* services/gradebook_service.py::DEFAULT_LETTER_SCALE (all twelve bands),
     GPA table, curve; routes/gradebook.py. */
  {
    slug: 'grade-scale', title: 'Grade scale', group: 'Semester', legacyId: 'grades',
    summary: 'The default letter bands, how a course grade is computed, curves and GPA.',
    lede: 'Your gradebook tracks the grade that goes on your transcript. These are the letter bands a percentage maps onto by default.',
    blocks: [
      { kind: 'letters', rows: [
        { letter: 'A', min: '≥ 93' }, { letter: 'A−', min: '≥ 90' },
        { letter: 'B+', min: '≥ 87' }, { letter: 'B', min: '≥ 83' }, { letter: 'B−', min: '≥ 80' },
        { letter: 'C+', min: '≥ 77' }, { letter: 'C', min: '≥ 73' }, { letter: 'C−', min: '≥ 70' },
        { letter: 'D+', min: '≥ 67' }, { letter: 'D', min: '≥ 63' }, { letter: 'D−', min: '≥ 60' },
        { letter: 'F', min: '< 60' },
      ] },
      { kind: 'facts', items: [
        'A category scores as points earned over points possible, after any dropped lowest. Your course grade is the weighted average across categories.',
        'A category with nothing graded yet drops out, and the remaining weights are rescaled to cover the whole grade. Drop-lowest removes the items with the lowest percentage, not the lowest points.',
        'The bands above are the default. You can set your own per course, because your professor’s A− might start at 92.',
        'A curve moves your grade so the class average lands on a target, keeping your distance from the mean. It needs the class mean and standard deviation entered on assignments; with none entered it changes nothing.',
        'Letters roll up to the standard 4.0 scale: A and A+ are 4.0, A− 3.7, B+ 3.3, down to D− at 0.7 and F at 0.0. GPA is weighted by credits, and a course with no credit count counts as one.',
        'The gradebook shows a term GPA, and the transcript a cumulative one. A letter from your own scale that is not on the 4.0 table, such as P, is left out of GPA rather than counted as zero.',
      ] },
    ],
  },

  /* routes/gradescope.py; components/screens/ConnectedAccounts.tsx. */
  {
    slug: 'gradescope', title: 'Gradescope', group: 'Semester',
    summary: 'Pull your Gradescope scores into the gradebook for a linked course.',
    lede: 'Connect Gradescope once, link each Sapling course to its Gradescope course, and sync to bring titles, dates and scores into your gradebook.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Connect with', value: 'Password · cookies · BU sign-in', note: 'A Gradescope password, pasted session cookies, or BU sign-in with a Duo push. The login is stored encrypted; a BU password is held only for that request.' },
        { label: 'Sync', value: 'By hand', note: 'Per linked course, at most 10 syncs every 5 minutes. Nothing syncs on its own.' },
        { label: 'What it updates', value: 'Titles, dates, points', note: 'A missing score never overwrites one already synced.' },
        { label: 'New items', value: 'Auto-categorised by title', note: 'An item lands in the category whose name its title contains, otherwise uncategorised.' },
        { label: 'Where', value: 'Settings or the gradebook', note: 'Connect under Settings, Connected accounts; link and sync from a course’s gradebook.' },
      ] },
    ],
  },

  // ── Together ─────────────────────────────────────────────────────────────

  /* routes/social.py (rooms, messages, overview, match);
     services/matching_service.py; components/screens/Social.tsx. */
  {
    slug: 'study-rooms', title: 'Study rooms', group: 'Together', legacyId: 'rooms',
    summary: 'Joining, messaging, matching, and exactly what a room sees of you.',
    lede: 'A chat scoped to the people studying the same thing, next to a comparison of where you each are.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Joining', value: 'Invite code or public', note: 'A room is invite-only unless its creator marks it public. Invite-only rooms take a six-character code; public ones are listed for anyone signed in to join.' },
        { label: 'Messages', value: 'Reply, edit, delete, react', note: 'You can edit or delete only your own. A deleted message shows as deleted to everyone; it is flagged rather than erased.' },
        { label: 'Overview', value: 'Your whole graph', note: 'Every member can see each concept on your tree and its mastery, across all your courses, and the room summary names what each member has mastered and is struggling with. Your notes, documents and grades are not shown.' },
        { label: 'Matching', value: 'In-room', note: 'Compares you with each member on the concepts you both have: they can teach you one where they are above 0.70 and you are under 0.50, and the reverse. No AI is involved.' },
        { label: 'Images', value: 'Public link', note: 'Text messages are encrypted; an image you post is stored unencrypted at a link anyone holding it can open.' },
        { label: 'Owner', value: 'Can remove members', note: 'The creator owns the room and is the only one who can remove a member. A room cannot yet be handed on or deleted.' },
        { label: 'Leaving', value: 'Messages stay', note: 'Leaving removes you from the room. What you posted stays in it.' },
      ] },
    ],
  },

  /* routes/profile.py (visibility); routes/social.py (directory, friends);
     routes/gamification.py (leaderboards). */
  {
    slug: 'profiles-and-friends', title: 'Profiles and friends', group: 'Together',
    summary: 'What other students see of you, how the directory works, and how friends are made.',
    lede: 'Every student has a profile with their name, username, avatar, cosmetics, roles, bio and a line of counts. Your Profile visibility setting decides how much of it others see, and whether you appear in the directory and on leaderboards. Profiles are public by default.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Public', value: 'Full profile to anyone signed in', note: 'You are listed in the school directory and on every leaderboard.' },
        { label: 'School', value: 'Full profile to your school', note: 'Everyone else sees the private view. You still appear in the directory and on the Everyone leaderboard.' },
        { label: 'Private', value: 'Username, avatar, cosmetics, roles', note: 'Your name, year, majors, bio, featured achievements and counts are hidden. You leave the directory and the Everyone and School leaderboards, but friends still see you on theirs.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Profile counts', def: 'Streak, tutor sessions, documents and achievements earned. No mastery and no grades appear on a profile.' },
        { term: 'Featured', def: 'Up to five of the achievements you have earned, and one role, chosen by you.' },
        { term: 'Directory', def: 'Lists students at your school with up to three course names and their streak. It searches names and course names, and shows no mastery.' },
        { term: 'Friend request', def: 'Sent with Add friend on someone’s profile. They accept or decline it under Incoming, and a declined request can be sent again.' },
        { term: 'Friends list', def: 'Only you can see yours. Removing a friend takes you off their list too.' },
      ] },
      { kind: 'facts', items: [
        'Profiles can only be opened while signed in.',
        'Your school is worked out from the courses you are enrolled in.',
        'Your profile visibility does not reach into study rooms: room members see your graph whatever it is set to.',
      ] },
    ],
  },

  /* services/chunk_visibility.py (decide_visibility, MIN_SHARE_CONFIDENCE);
     agents/classifier.py; services/rag_service.py;
     db/migrations/20260920072705_course_chunk_visibility.sql. */
  {
    slug: 'shared-class-material', title: 'Shared class material', group: 'Together',
    summary: 'When a document you upload joins the pool your class’s tutor and quizzes draw on, and how to keep yours out.',
    lede: 'Course material students upload is pooled per course, so the tutor and quiz generator can draw on slides and readings a classmate uploaded as well as your own. Two checks decide whether a document of yours joins that pool: whether it is the course’s to share, and whether you agreed to share. Both must pass, and any unclear answer resolves to private.',
    blocks: [
      { kind: 'terms', rows: [
        { term: 'Course material', def: 'Produced by or for the course: syllabi, lecture notes, slides, assigned readings and blank assignment handouts. The only kind that can be shared.' },
        { term: 'Completed work', def: 'Your own answers: worked solutions, filled-in problem sets, submitted essays, anything carrying a grade or feedback. Always private, whatever your setting.' },
        { term: 'Personal notes', def: 'Your own study notes, plans and reminders, and anything that is neither of the others. Always private.' },
      ] },
      { kind: 'steps', rows: [
        { num: '01', title: 'Label', body: 'On upload, Sapling labels whose document it is. Where it could be read either way, it picks the more private label.' },
        { num: '02', title: 'Check confidence', body: 'Course material labelled with less than 0.6 confidence stays private, and so does a document that came back with no label.' },
        { num: '03', title: 'Check your setting', body: 'With Class intel off, the document stays private. If your setting cannot be read at that moment, it stays private too.' },
        { num: '04', title: 'Index', body: 'The text is split into passages and stored encrypted. Private passages are retrievable only for you, shared ones for anyone studying the course.' },
      ] },
      { kind: 'specs', rows: [
        { label: 'Pooled by', value: 'Course', note: 'One pool per course across every term and section, so material shared one semester is there the next.' },
        { label: 'Per question', value: 'Up to 5 passages', note: 'The five closest passages that pass a relevance bar, from the shared pool plus your private ones.' },
        { label: 'Attribution', value: 'None', note: 'A shared passage reaches the model without your name or the file name on it.' },
        { label: 'Duplicates', value: 'Stored once', note: 'Identical text from two students is one passage, and it stays shared while either of them still shares.' },
      ] },
      { kind: 'facts', items: [
        'Class intel is on for every account until you turn it off. The switch is in the tutor, and it is one setting for your account, not one per course.',
        'Turning it off makes your past shared passages private straight away, unless a classmate who still shares uploaded the same text.',
        'Turning it back on does not re-share what you uploaded while it was off.',
        'Turning it off does not stop your own tutor and quizzes reading passages your classmates shared.',
        'You cannot see or change a document’s label in the app.',
      ] },
    ],
  },

  /* services/course_context_service.py; agents/tools/graph_read.py;
     components/chat/SharedContextToggle.tsx; routes/profile.py. */
  {
    slug: 'class-intelligence', title: 'Class intelligence', group: 'Together', legacyId: 'class',
    summary: 'The anonymised, class-wide rollup of mastery and common mistakes, and how far it reaches.',
    lede: 'The anonymised, class-wide layer. It is the least-finished thing in Sapling, so here is exactly how far it reaches.',
    blocks: [
      { kind: 'terms', rows: [
        { term: 'What it is', def: 'A rollup for one course in one term: average mastery per concept, the share of students mastered or struggling, and the mistakes their quizzes recorded, with no names attached. There is no minimum class size, so in a small class a pattern can be one person’s.' },
        { term: 'Where it lands', def: 'Quiz generation reads it, and common misconceptions become the tempting wrong answers. That is the whole of its reach today.' },
        { term: 'What it is not', def: 'There is no screen that shows it. Its one control is the Class intel switch in the tutor, on by default.' },
        { term: 'Opting out', def: 'Turning Class intel off keeps your graph and quiz history out of the rollup, and every class you are in is recomputed straight away.' },
        { term: 'What off does not do', def: 'It does not stop your own quizzes using your classmates’ misconceptions, and it does not change what the tutor retrieves.' },
      ] },
    ],
  },

  // ── You ──────────────────────────────────────────────────────────────────

  /* routes/auth.py; routes/onboarding.py; components/screens/Onboarding.tsx. */
  {
    slug: 'onboarding', title: 'Onboarding', group: 'You', legacyId: 'onboarding',
    summary: 'The short path from signed in to on the tree.',
    lede: 'The short path from signed in to on the tree.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Sign-in', value: 'Google, domain-gated', note: 'Gated to a school email domain, bu.edu by default.' },
        { label: 'Waitlist', value: 'Approval first', note: 'A new account waits on a waitlist screen until Sapling approves it.' },
        { label: 'Asked once', value: 'Name, year, majors, learning style', note: 'Minors are optional. Learning style is stored, but nothing reads it yet: not the tutor, not quizzes.' },
        { label: 'Courses', value: 'From the catalog', note: 'Search by name or code and pick at least one; each is added to the current term.' },
        { label: 'Leaving early', value: 'Signs you out', note: 'Closing onboarding signs you out. Your answers so far are kept in this browser for next time.' },
      ] },
    ],
  },

  /* db/migrations/20260731194102_achievement_catalog.sql;
     services/achievement_service.py; routes/profile.py (cosmetics, featured). */
  {
    slug: 'achievements', title: 'Achievements', group: 'You', legacyId: 'achievements',
    summary: 'What you earn as you go, and the cosmetics it unlocks.',
    lede: 'What you earn as you go, and what it unlocks.',
    blocks: [
      { kind: 'terms', rows: [
        { term: 'Trigger', def: 'Each achievement watches one number, such as sessions, quizzes completed, cards reviewed, concepts mastered, streak, level, rooms or friends. A few watch a single session: two hours long, or finished early in the morning or late at night, in UTC.' },
        { term: 'Granted by hand', def: 'Four are awarded by Sapling rather than earned on a number: Mentor, Second Wind, Methuselah, and a secret one.' },
        { term: 'Cosmetics', def: 'Four equippable slots: avatar frame, banner, name colour and title. Each unlocks with the achievement it is linked to, which is the only way one unlocks today.' },
        { term: 'Featured', def: 'Choose up to five achievements and one role to show on your profile. A private profile hides them.' },
      ] },
    ],
  },

  /* db/migrations/20260731193214_gamification.sql (seed values, editable by
     admins); services/xp_service.py; services/growth.py; routes/gamification.py. */
  {
    slug: 'xp-and-levels', title: 'XP and levels', group: 'You',
    summary: 'What earns XP, the eleven growth stages, the daily goal and the weekly leaderboard.',
    lede: 'XP is a count of study actions, not a measure of mastery. These are the values Sapling ships with.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Study session', value: '25 XP', note: 'A tutor session you finish.' },
        { label: 'Quiz', value: '30 XP', note: 'A quiz you submit.' },
        { label: 'Upload', value: '15 XP', note: 'A document that finishes processing.' },
        { label: 'New note', value: '10 XP', note: 'Each one pays once.' },
        { label: 'Achievement', value: 'Its own reward', note: 'Each achievement carries an XP amount of its own.' },
        { label: 'Daily goal', value: '50 XP', note: 'Fixed; nothing lets you change it yet, and meeting it pays nothing extra today.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Levels', def: 'Eleven growth stages, from Bare Soil at level 1 to Old Growth at 50, each level costing more than the last: 50 XP early, 2,000 by the forties. Level 50 takes 30,000 XP in all.' },
        { term: 'Leaderboard', def: 'Ranks this week’s XP and resets Monday 00:00 UTC, for everyone, your school or your friends. Your own row always shows.' },
        { term: 'Activity', def: 'The last eight weeks of your XP.' },
      ] },
    ],
  },

  /* components/screens/Settings.tsx; routes/profile.py; lib/useLayoutPref.ts. */
  {
    slug: 'settings', title: 'Settings', group: 'You',
    summary: 'Every control in Settings, what it saves, and the few that are stored but do nothing yet.',
    lede: 'Settings has five tabs (Profile, Cosmetics, Preferences, Notifications and Data) and a link to Connected accounts. There is no Save button: text fields save when you leave them, and toggles and menus save as you change them.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Username', value: '3 – 24 characters', note: 'Lowercase letters, digits and underscores. Checked as you type and saved when you leave the field, only if it is free.' },
        { label: 'Avatar', value: 'Image, up to 5 MB', note: 'Shown at once, and put back to the old one if the upload fails.' },
        { label: 'Bio · Location · Website', value: 'Shown on your profile', note: 'Bio and location are stored encrypted.' },
        { label: 'Display name', value: 'Not editable yet', note: 'The field takes text but does not save it. Your name comes from sign-up.' },
      ] },
      { kind: 'terms', rows: [
        { term: 'Layout', def: 'Sidebar (the default) or top navigation, remembered per browser. A screen narrower than 768 px always gets the top bar.' },
        { term: 'Theme', def: 'Light is the only option today.' },
        { term: 'Font size', def: 'Small, medium or large is saved, but nothing reads it yet, so text size does not change.' },
        { term: 'Profile visibility', def: 'Public, School or Private. See Profiles and friends for what each shows.' },
        { term: 'Accent colour', def: 'Five swatches or any custom colour, for highlights and active states.' },
        { term: 'Notifications', def: 'Email, push, in-app and activity status are saved, but Sapling sends no notifications and shows no activity status yet.' },
        { term: 'Preview profile', def: 'Shows your own view, which is always complete, not what other students see.' },
      ] },
    ],
  },

  /* components/FloatingActions.tsx, ReportIssueFlow.tsx, FeedbackFlow.tsx,
     SessionFeedbackFlow.tsx; routes/feedback.py. */
  {
    slug: 'feedback-and-reports', title: 'Feedback and reports', group: 'You',
    summary: 'Reporting a problem, the screenshots you can attach, and the prompts that ask how it went.',
    lede: 'The Report button sits at the bottom right of every signed-in screen.',
    blocks: [
      { kind: 'specs', rows: [
        { label: 'Report types', value: 'Bug · Feature · Polish · Content · Other', note: 'A description is required.' },
        { label: 'Screenshots', value: 'Up to 5, 5 MB each', note: 'PNG, JPEG, WEBP or GIF.' },
        { label: 'Rating prompt', value: 'At most every 3 days', note: 'A 1–5 rating that opens 45 seconds into a visit. Dismissing it counts as a showing.' },
        { label: 'Session prompt', value: 'At most every 2 days', note: 'Opens when you leave the tutor: a 4-point scale, then what helped or got in the way, then a note.' },
      ] },
      { kind: 'facts', items: [
        'The topic and description of a report are stored encrypted.',
        'Both prompt cooldowns are kept per browser.',
      ] },
    ],
  },

  /* components/quiz/question/QuizQuestion.tsx; components/screens/Study.tsx;
     components/chat/ChatPanel.tsx. */
  {
    slug: 'keyboard-shortcuts', title: 'Keyboard shortcuts', group: 'You',
    summary: 'The keys each screen answers to.',
    lede: 'There is no global shortcut system; each screen has its own.',
    blocks: [
      { kind: 'terms', rows: [
        { term: 'Quiz', def: 'A–F or 1–6 pick an option, the arrow keys and Space move and choose, Enter is the footer action, and Esc leaves.' },
        { term: 'Flashcards', def: 'Space flips the card; 1, 2 and 3 rate it.' },
        { term: 'Tutor', def: 'Enter sends, Shift+Enter adds a new line.' },
        { term: 'Graphs', def: 'Esc exits fullscreen. In the add-concept box, Enter adds and Esc cancels.' },
        { term: 'Wiki search', def: 'Esc clears the search.' },
      ] },
    ],
  },

  /* services/encryption.py and the encrypted-column list in CLAUDE.md;
     routes/profile.py (export, delete_account); routes/documents.py
     (soft delete); privacy/page.tsx (processor). Stated precisely, per the
     brand guide's rule that privacy claims name what is true today. */
  {
    slug: 'your-data', title: 'Your data', group: 'You', legacyId: 'privacy',
    summary: 'What is encrypted, what is not, who processes it, and what export and delete do.',
    blocks: [
      { kind: 'dataFacts', rows: [
        { fact: 'Sensitive columns are encrypted at rest with AES-256-GCM, with a fresh random nonce for every value and a tag that makes tampering detectable.',
          detail: 'Encrypted: your name, bio and location, your email, your Google tokens and Gradescope login, tutor and study-room messages and session summaries, note titles, bodies and summaries, document summaries, concept notes and extracted text, the passages indexed for retrieval, assignment points and notes, quiz questions and answers, flashcards, study guides, and feedback you send.' },
        { fact: 'Some things are deliberately not encrypted, and you should know which.',
          detail: 'Concept names and mastery, assignment titles and due dates, gradebook categories, quiz scores, note tags, file names, your year and majors, your username and cosmetics are stored in plain form, and images posted in study rooms sit at a public link. Keep anything sensitive out of a tag or a title.' },
        { fact: 'Your material is processed by Google’s Gemini models to do the work, and it is never sold.',
          detail: 'Text is decrypted on Sapling’s server only to build a model request: a study action you asked for, or background work such as indexing your uploads and writing a study room’s summary.' },
        { fact: 'The file you upload is not kept.',
          detail: 'Sapling stores the text extracted from it, encrypted, with the summary and concepts drawn from it.' },
        { fact: 'Deleting a document removes it from your library, but not everything it produced.',
          detail: 'The concepts it planted stay on your tree, and its passages stay indexed for retrieval, including in your class’s shared pool if it was shared. Remove a concept from the tree itself, where a node can be deleted directly.' },
        { fact: 'Export and account deletion both live in Settings, and both do less than their names suggest today.',
          detail: 'Export downloads your profile, settings, roles, achievements and cosmetics, not your documents, notes, graph or messages. Deleting your account marks it deleted and signs you out, but erases nothing yet.' },
      ] },
    ],
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
