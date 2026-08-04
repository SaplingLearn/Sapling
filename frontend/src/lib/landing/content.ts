/**
 * Editorial content for the v4 landing page — gallery cards, FAQ, journal.
 *
 * Ported verbatim from `Sapling Landing v4.dc.html`. Copy is treated as
 * fixed: the gallery `num` values continue the numbering the acts start,
 * and each card's `kind` selects both its bespoke miniature animation and
 * the feature-lab panel it expands into.
 */

/** Character set the hero text scrambles through before it settles. */
export const SCRAMBLE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!<>-_\\/[]{}=+*^?#_';

/** Gallery card kind → the feature-lab panel it opens. */
export const LAB_KIND = {
  quiz: 'quiz',
  flashcards: 'cards',
  notetaker: 'notes',
  guide: 'guide',
  rooms: 'rooms',
  gradebook: 'grades',
  calendar: 'calendar',
  tutor: 'tutor',
} as const;

export type GalleryKind = keyof typeof LAB_KIND;
export type LabKind = (typeof LAB_KIND)[GalleryKind];

export interface GalleryCard {
  kind: GalleryKind;
  /** Two-digit index shown on the card. Continues from the acts. */
  num: string;
  kicker: string;
  title: string;
  desc: string;
  bullets: { t: string }[];
}

export const GAL: GalleryCard[] = [
  {
    kind: 'quiz',
    num: '04',
    kicker: 'Assessment',
    title: 'Quizzes that meet you where you struggle.',
    desc: "Questions re-tune to your level after every answer, pressing where you're strong, slowing down where you're not.",
    bullets: [
      { t: 'Difficulty re-tunes after every single answer.' },
      { t: 'Missed concepts come back right before you’d forget them.' },
      { t: 'Every question is grounded in your own course materials.' },
    ],
  },
  {
    kind: 'flashcards',
    num: '05',
    kicker: 'Recall',
    title: 'Cards that know when you’ll forget.',
    desc: 'Generate decks per course, or bring your own from anywhere. Spaced repetition schedules each card for the moment it matters.',
    bullets: [
      { t: 'Import from paste, CSV, Anki, a URL, even a photo of notes.' },
      { t: 'Again / good / easy ratings set each card’s return date.' },
      { t: 'Every rating feeds mastery back into your graph.' },
    ],
  },
  {
    kind: 'notetaker',
    num: '06',
    kicker: 'Notes',
    title: 'Notes that feed the graph.',
    desc: 'Write like you always do. Sapling extracts the concepts, links them back to the note, and can quiz you on the weakest one.',
    bullets: [
      { t: 'Autosaves while you type. No save button.' },
      { t: 'Concepts are extracted and mapped as you write.' },
      { t: 'Ask questions answered from your own notes.' },
    ],
  },
  {
    kind: 'guide',
    num: '07',
    kicker: 'Exam prep',
    title: 'A study guide built from your gaps.',
    desc: 'Before each exam, Sapling assembles a guide from your own uploaded materials, weighted toward the concepts you keep missing.',
    bullets: [
      { t: 'Generated per exam, from your actual uploads.' },
      { t: 'Weighted by your miss history, not chapter order.' },
      { t: 'Every section links back to its source.' },
    ],
  },
  {
    kind: 'rooms',
    num: '08',
    kicker: 'Together',
    title: 'Learn next to your classmates.',
    desc: 'Invite your class, compare knowledge graphs side by side, and keep each other honest. The library table, without the library hours.',
    bullets: [
      { t: 'Live rooms with real-time chat.' },
      { t: 'Graphs side by side. See who’s solid where.' },
      { t: 'Turn any gap into a shared quiz in one click.' },
    ],
  },
  {
    kind: 'gradebook',
    num: '09',
    kicker: 'Reality check',
    title: 'Your real grade, always current.',
    desc: 'Categories and weights straight from your syllabus, per-assignment scores, and a live course grade that never lies to you.',
    bullets: [
      { t: 'Weights parsed from your syllabus automatically.' },
      { t: 'Link Gradescope once. New scores pull themselves in.' },
      { t: '“What do I need on the final” math, built in.' },
    ],
  },
  {
    kind: 'calendar',
    num: '10',
    kicker: 'Deadlines',
    title: 'Paste a syllabus. Get a semester.',
    desc: 'Every problem set, quiz, and midterm extracted from the syllabus and placed on your calendar automatically, before week one is over.',
    bullets: [
      { t: 'Whole-semester extraction from one paste.' },
      { t: 'Assignments, exams, and office hours, all placed.' },
      { t: 'Study blocks suggested around your weakest concepts.' },
    ],
  },
  {
    kind: 'tutor',
    num: '11',
    kicker: 'AI tutor',
    title: 'It asks. You answer.',
    desc: 'Three modes on the same concept. Socratic questions you toward it, expository explains it from your own materials, teachback makes you do the explaining.',
    bullets: [
      { t: 'Never hands over the solution, by design.' },
      { t: 'Grounded in your uploads, with the sources shown.' },
      { t: 'Teachback finds the gap you did not know you had.' },
    ],
  },
];

export interface Faq {
  q: string;
  a: string;
}

export const FAQS: Faq[] = [
  {
    q: 'Isn’t using AI to study just cheating?',
    a: 'No, because Sapling never hands you the answer. It guides you toward the understanding: Socratic questioning, explanations you have to apply yourself, and TeachBack, where you do the explaining. Using Sapling is like having a tutor, not a ghostwriter. The work, and the learning, is still yours.',
  },
  {
    q: 'Will it just do my homework for me?',
    a: "It won't, by design. Answer engines hand over the solution; Sapling walks you through the process and adapts to how you learn. If you paste a homework problem, expect guiding questions, not a finished answer to copy.",
  },
  {
    q: 'How is this different from just using ChatGPT?',
    a: "A general chatbot forgets you the moment you close the tab. Sapling maps what you know, remembers what you struggled with, schedules reviews before you forget, and grounds itself in your actual course materials. It's a study system, not a conversation.",
  },
  {
    q: 'Won’t I become dependent on the AI?',
    a: 'We built Sapling to make you less dependent over time. Mastery only turns green when you can demonstrate understanding, and TeachBack literally requires you to explain concepts yourself. The goal is that you walk into the exam without us.',
  },
  {
    q: 'What happens to my notes and documents?',
    a: 'They stay yours. Uploads, notes, and messages are encrypted at rest (AES-256), used only to build your graph and study materials, and never sold or used to train outside models. Delete a document and its data goes with it.',
  },
  {
    q: 'Are tools like Sapling allowed in my classes?',
    a: "Sapling is a study aid, the same category as flashcards, tutoring, or a study group. It doesn't produce submittable work. That said, every course sets its own rules, so check your syllabus; our stance on academic integrity is in the Journal.",
  },
  {
    q: 'What does it cost?',
    a: "Nothing during beta. Beta testers get every feature free while we build, and a say in what we build next. Join the list below and you're in line.",
  },
  {
    q: 'What if the AI gets something wrong?',
    a: 'It can, which is why Sapling grounds answers in your uploaded course materials and shows its reasoning instead of just a verdict. You stay the judge. Spot an error? Flag it in one click and the tutor corrects course.',
  },
];

export interface PostMeta {
  /** Image-slot persistence key. Must stay distinct per slot. */
  slot: string;
  /** Public-dir path, or '' when the card renders a graph instead. */
  src: string;
  slotHint: string;
  isPhoto: boolean;
  isGraph: boolean;
  comments: number;
  likes: number;
  /** Negative delays desynchronise the three cards' float loops. */
  floatDelay: string;
}

/**
 * Presentation metadata paired positionally with POSTS.
 *
 * NOTE: `journal-founding.png` and `journal-ai-homework.png` are not in
 * `public/` yet — both exceed the design API's 256 KiB read cap, so they
 * ship with the project export alongside the rest of the source.
 */
export const POST_META: PostMeta[] = [
  {
    slot: 'journal-1',
    src: '/journal-founding.png',
    slotHint: 'Drop the founding photo',
    isPhoto: true,
    isGraph: false,
    comments: 12,
    likes: 84,
    floatDelay: '0s',
  },
  {
    slot: 'journal-2',
    src: '/journal-ai-homework.png',
    slotHint: 'Drop an image for this essay',
    isPhoto: true,
    isGraph: false,
    comments: 31,
    likes: 126,
    floatDelay: '-2.5s',
  },
  {
    slot: 'journal-3',
    src: '',
    slotHint: '',
    isPhoto: false,
    isGraph: true,
    comments: 8,
    likes: 57,
    floatDelay: '-5s',
  },
];

export interface Post {
  tag: string;
  date: string;
  title: string;
  time: string;
  excerpt: string;
}

export const POSTS: Post[] = [
  {
    tag: 'Founding',
    date: 'JUN 2026',
    title: 'Why we built Sapling',
    time: '6 MIN',
    excerpt:
      'Four students, one library table, and a nagging question: what if AI made you understand more, not less? The origin story, missteps included.',
  },
  {
    tag: 'Perspective',
    date: 'MAY 2026',
    title: 'AI shouldn’t do your homework',
    time: '4 MIN',
    excerpt:
      'Our line in the sand on AI and education: guidance over answers, process over shortcuts, and why "just give me the solution" is the wrong deal.',
  },
  {
    tag: 'Under the hood',
    date: 'APR 2026',
    title: 'How the knowledge graph works',
    time: '7 MIN',
    excerpt:
      'Nodes, edges, and mastery scores: how a semester of studying becomes a living map, and what your graph knows that your transcript doesn’t.',
  },
];
