/**
 * Copy for the six companion pages.
 *
 * Lifted verbatim from the sibling `.dc.html` design components, where it
 * lives as plain JS object literals. Content only -- no markup, no styling.
 */

import {
  JOURNAL_ARTICLES,
  articleText,
  dateLabel,
  readTime,
} from './journalArticles';

export const ABOUT_DIFFERENTIATORS = [
        'Your knowledge graph is yours. It updates in real time based on your actual performance, not just what you\u2019ve clicked through.',
        'Three distinct teaching modes mean you\u2019re never locked into one way of learning.',
        'Study rooms let you learn alongside classmates and see how your mastery compares, anonymously and collaboratively.',
        'Everything from syllabus tracking to exam study guides is powered by Gemini, so the busywork of getting organized is handled for you.',
      ] as const;

export const ABOUT_AWARDS = [
        { delay: '440ms', title: 'Best AI Tutor in Education',
          org: 'Boston University Civic Hacks 2026 \u00b7 BU Spark! & Wheelock College of Education',
          body: 'Recognized among competing teams at BU\u2019s annual civic hackathon for building the most impactful AI-driven learning experience. Sapling was awarded for its approach to personalized, student-centered tutoring, bridging the gap between artificial intelligence and meaningful education.' },
        { delay: '520ms', title: 'Code & Tell Winner', org: 'BU Spark!',
          body: 'Selected by BU Spark! as a standout project at their Code & Tell showcase, where student builders present real-world applications to faculty, mentors, and industry judges. Sapling was chosen for its technical depth and its vision for the future of how students learn.' },
      ] as const;

export const TEAM_MEMBERS = [
        { name:'Andres Lopez', role:'Full stack', slot:'team-andres', hint:'Drop a photo of Andres',
          body:'Works end to end, from the database up through the screens, and keeps the two halves speaking the same language.', delay:'0ms' },
        { name:'Jack He', role:'AI architecture and new features', slot:'team-jack', hint:'Drop a photo of Jack',
          body:'Designs how the agents, the graph, and your own materials fit together, and builds what Sapling does next.', delay:'80ms' },
        { name:'Jose Gael Cruz-Lopez', role:'Frontend', slot:'team-jose', hint:'Drop a photo of Jose',
          body:'Builds the interface you actually study in, and the motion and layout that keep it out of your way.', delay:'160ms' },
        { name:'Luke Cooper', role:'API integration', slot:'team-luke', hint:'Drop a photo of Luke',
          body:'Wires Sapling to the services your course already lives in, so your calendar, grades, and files arrive on their own.', delay:'240ms' },
        { name:'Hang Nguyen', role:'Marketing intern', slot:'team-hang', hint:'Drop a photo of Hang',
          body:'Runs the social side and the short-form video, and carries Sapling to the student groups and classmates we would never reach on our own.', delay:'320ms' },
      ] as const;

export const TEAM_WAYS = [
        'We use Sapling for our own courses before anyone else sees a feature. If it does not help us pass, it does not ship.',
        'Every feature has to feed the graph. A tool that knows nothing about what you already understand is a tool we would not add.',
        'We read every piece of beta feedback ourselves. There is no support queue between you and the people who built it.',
      ] as const;

export const FAQ_GROUPS = [
  { label: 'Academic integrity', items: [
    { q:"Isn\u2019t using AI to study just cheating?", a:"No, because Sapling never hands you the answer. It guides you toward the understanding: Socratic questioning, explanations you have to apply yourself, and TeachBack, where you do the explaining. Using Sapling is like having a tutor, not a ghostwriter. The work, and the learning, is still yours." },
    { q:"Will it just do my homework for me?", a:"It won't, by design. Answer engines hand over the solution; Sapling walks you through the process and adapts to how you learn. If you paste a homework problem, expect guiding questions, not a finished answer to copy." },
    { q:"Are tools like Sapling allowed in my classes?", a:"Sapling is a study aid, the same category as flashcards, tutoring, or a study group. It doesn't produce submittable work. That said, every course sets its own rules, so check your syllabus." },
    { q:"Won\u2019t I become dependent on the AI?", a:"We built Sapling to make you less dependent over time. Mastery only turns green when you can demonstrate understanding, and TeachBack literally requires you to explain concepts yourself. The goal is that you walk into the exam without us." },
  ]},
  { label: 'How it differs', items: [
    { q:"How is this different from just using ChatGPT?", a:"A general chatbot forgets you the moment you close the tab. Sapling maps what you know, remembers what you struggled with, schedules reviews before you forget, and grounds itself in your actual course materials. It's a study system, not a conversation." },
    { q:"What if the AI gets something wrong?", a:"It can, which is why Sapling grounds answers in your uploaded course materials and shows its reasoning instead of just a verdict. You stay the judge. Spot an error and flag it in one click, and the tutor corrects course." },
    { q:"Do I have to upload anything to get value?", a:"You can start with a single syllabus and still get a full semester of dates plus a first pass at the concept graph. The more of your own material you add, the more the quizzes and guides look like your course rather than a generic one." },
    { q:"Does it work for every subject?", a:"It works wherever your course has readable material and named concepts, which covers most lecture-based courses. Heavily studio or performance-based courses get less out of it, and we would rather say that than oversell." },
  ]},
  { label: 'Access and data', items: [
    { q:"What does it cost?", a:"Nothing during beta. Beta testers get every feature free while we build, and a say in what we build next. Join the list and you're in line." },
    { q:"What happens to my notes and documents?", a:"They stay yours. Uploads, notes, and messages are encrypted at rest with AES-256, used to build your graph and study materials, and never sold. The wiki’s Your data page lists exactly what is and is not encrypted, and what deleting a document leaves behind." },
    { q:"Can I study with people from my class?", a:"Yes. Study rooms put a live chat next to a shared graph, so the room can see which concepts nobody has locked down and turn any gap into a quiz everyone takes." },
    { q:"When does the beta open?", a:"We are onboarding in small groups so we can actually read the feedback. Sign up and we will tell you which group you are in rather than leaving you on a silent list." },
  ]},
] as const;

export const GALLERY_SHOTS = [
  { slot:'shot-tree', route:'/tree', group:'Learn', cat:'learn', title:'Knowledge graph',
    body:'The whole course as nodes and edges, each ring showing mastery. Click any concept to see what it feeds.' },
  { slot:'shot-learn', route:'/learn', group:'Learn', cat:'learn', title:'AI tutor',
    body:'Socratic, expository, and TeachBack on the same concept, grounded in the documents you uploaded.' },
  { slot:'shot-quiz', route:'/quiz', group:'Learn', cat:'learn', title:'Adaptive quiz',
    body:'Difficulty re-tunes after every answer, and each result writes back to the concept it tested.' },
  { slot:'shot-study', route:'/study', group:'Study', cat:'study', title:'Flashcard review',
    body:'Rate your recall and the interval sets itself: ten minutes, one day, or four days.' },
  { slot:'shot-guide', route:'/study', group:'Study', cat:'study', title:'Study guide',
    body:'Assembled from your own library for one exam, weighted toward the concepts you keep missing.' },
  { slot:'shot-notetaker', route:'/notetaker', group:'Study', cat:'study', title:'Notetaker',
    body:'Write normally. Sapling summarizes, extracts the concepts, and links them into your graph.' },
  { slot:'shot-library', route:'/library', group:'Study', cat:'study', title:'Library',
    body:'Everything you have dropped in, with the concepts, cards, and dates each document produced.' },
  { slot:'shot-social', route:'/social', group:'Together', cat:'together', title:'Study rooms',
    body:'Live chat beside a shared graph, so the room can see exactly who is solid where.' },
  { slot:'shot-achievements', route:'/achievements', group:'Together', cat:'together', title:'Achievements',
    body:'Streaks and milestones that track demonstrated understanding rather than time logged.' },
  { slot:'shot-calendar', route:'/calendar', group:'Semester', cat:'semester', title:'Calendar',
    body:'One syllabus upload becomes every exam, pset, and quiz, dated and synced to Google Calendar.' },
  { slot:'shot-gradebook', route:'/gradebook', group:'Semester', cat:'semester', title:'Gradebook',
    body:'Syllabus weights become categories, and every score rolls into a live grade and letter.' },
  { slot:'shot-planner', route:'/course-planner', group:'Semester', cat:'semester', title:'Course planner',
    body:'Map the degree, not just the term. Prerequisites carry across semesters.' },
] as const;

export const GALLERY_FILTERS = [
  { key:'all', label:'All screens' },
  { key:'learn', label:'Learn' },
  { key:'study', label:'Study' },
  { key:'together', label:'Together' },
  { key:'semester', label:'Semester' },
] as const;

/**
 * The /news index cards.
 *
 * Derived from the article table (#601): these used to be six hand-typed
 * literals carrying their own tag, `6/12/2026`-style date, read time and an
 * `assets/...` image path that /news had to remap. `body` rides along so the
 * search box can match the prose, not just the excerpt.
 */
export const NEWS_POSTS = JOURNAL_ARTICLES.map((article) => ({
  cat: article.cat,
  tag: article.tag,
  date: dateLabel(article.publishedAt),
  time: readTime(article.body),
  art: article.art,
  slug: article.slug,
  title: article.title,
  excerpt: article.deck,
  text: articleText(article.body),
}));

export const NEWS_FILTERS = [
  { key:'all', label:'All articles' },
  { key:'release', label:'Releases' },
  { key:'product', label:'Product' },
  { key:'perspective', label:'Perspective' },
  { key:'founding', label:'Founding' },
] as const;


/* ── Wiki ────────────────────────────────────────────────────────────────
 * The topics themselves live in lib/landing/wiki.ts; the screenshots each
 * page borrows from the gallery stay here beside GALLERY_SHOTS.
 */

/**
 * Product screenshots, keyed by wiki page slug (lib/landing/wiki.ts).
 *
 * The files are the twelve `/gallery/<slot>.png` captures at 1440x900 — the
 * same set the gallery uses, so this page borrows them rather than owning
 * any. Nothing new goes in `public/gallery/`: the orphan check in
 * gallery.test.ts pins that directory to exactly the GALLERY_SHOTS slots.
 *
 * `title` names the screen: it heads the expanded view and becomes the alt
 * on the expanded image, which has no caption beside it. The names are
 * GALLERY_SHOTS' verbatim, so a screen is called the same thing on both
 * surfaces.
 *
 * `caption` is rendered as a visible figcaption and the thumbnail carries
 * `alt=""`, the same split the gallery uses. That is what keeps a capture
 * that has not landed yet from painting alt text and a broken-image glyph
 * across the panel.
 *
 * Two slots have no row here on purpose. `shot-tree` would otherwise appear
 * twice on adjacent pages, which reads as a mistake rather than a
 * reference; it stays on the graph page, and mastery tiers goes without.
 * `shot-planner` is a screenshot of a "Coming soon" panel — a reference page
 * has nothing to define about a screen that does not exist yet.
 */
export const WIKI_SHOTS: Record<string, { slot: string; route: string; title: string; caption: string }> = {
  'knowledge-graph': { slot:'shot-tree', route:'/tree', title:'Knowledge graph',
    caption:'The knowledge tree: concept nodes joined by edges, each ringed to show its mastery.' },
  'adaptive-quizzes': { slot:'shot-quiz', route:'/quiz', title:'Adaptive quiz',
    caption:'An adaptive quiz mid-session, showing a multiple-choice question and its difficulty.' },
  'tutor-modes': { slot:'shot-learn', route:'/learn', title:'AI tutor',
    caption:'The tutor answering in Socratic mode, leading with a question rather than an answer.' },
  library: { slot:'shot-library', route:'/library', title:'Library',
    caption:'The document library, listing uploads beside the summary and concepts each produced.' },
  notetaker: { slot:'shot-notetaker', route:'/notetaker', title:'Notetaker',
    caption:'The notetaker with a note open and its generated summary in the side rail.' },
  flashcards: { slot:'shot-study', route:'/study', title:'Flashcard review',
    caption:'A flashcard mid-review with its three rating buttons.' },
  'study-guide': { slot:'shot-guide', route:'/study', title:'Study guide',
    caption:'A generated study guide for one course, laid out in sections.' },
  'syllabus-and-calendar': { slot:'shot-calendar', route:'/calendar', title:'Calendar',
    caption:'The calendar, showing assignments and dates extracted from a syllabus.' },
  'grade-scale': { slot:'shot-gradebook', route:'/gradebook', title:'Gradebook',
    caption:'A course gradebook showing weighted categories and the resulting letter grade.' },
  'study-rooms': { slot:'shot-social', route:'/social', title:'Study rooms',
    caption:'A study room with its chat thread beside the room member list.' },
  achievements: { slot:'shot-achievements', route:'/achievements', title:'Achievements',
    caption:'The achievements screen showing earned milestones and a study streak.' },
};
