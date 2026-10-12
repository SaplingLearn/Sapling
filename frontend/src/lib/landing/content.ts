/**
 * Editorial content for the v4 landing page — gallery cards, FAQ, journal.
 *
 * Ported verbatim from `Sapling Landing v4.dc.html`. Copy is treated as
 * fixed: the gallery `num` values continue the numbering the acts start,
 * and each card's `kind` selects both its bespoke miniature animation and
 * the feature-lab panel it expands into.
 */

import {
  JOURNAL_ARTICLES,
  dateLabel,
  readTime,
  type ArticleArt,
} from './journalArticles';

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
    desc: "Questions come from the concepts you're weakest on, at a difficulty you pick or one set from your mastery.",
    bullets: [
      { t: 'Choose a difficulty, or let it adapt to your mastery.' },
      { t: 'Every result writes mastery back to your graph.' },
      { t: 'Every question is grounded in your own course materials.' },
    ],
  },
  {
    kind: 'flashcards',
    num: '05',
    kicker: 'Recall',
    title: 'Cards from your own material.',
    desc: 'Generate decks per course, or bring your own from anywhere, then review them with a quick recall rating.',
    bullets: [
      { t: 'Import from paste, CSV, Anki, a URL, even a photo of notes.' },
      { t: 'Rate each card Forgot, Hard, or Easy as you review.' },
      { t: 'Generated from the documents in your library.' },
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
      { t: 'Extract a note’s concepts into your graph in one click.' },
      { t: 'Ask questions answered from your own notes.' },
    ],
  },
  {
    kind: 'guide',
    num: '07',
    kicker: 'Exam Prep',
    title: 'A study guide built from your materials.',
    desc: 'Before each exam, Sapling assembles a guide from your own uploaded materials, organized for review.',
    bullets: [
      { t: 'Generated per exam, from your actual uploads.' },
      { t: 'Laid out in sections you can work through.' },
      { t: 'Rebuilt when you upload new material.' },
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
      { t: 'See which concepts the room has not locked down.' },
    ],
  },
  {
    kind: 'gradebook',
    num: '09',
    kicker: 'Grade Calculator',
    title: 'Your real grade, always current.',
    desc: 'Categories and weights straight from your syllabus, per-assignment scores, and a live course grade.',
    bullets: [
      { t: 'Weights parsed from your syllabus automatically.' },
      { t: 'Link Gradescope and sync your scores in one click.' },
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
      { t: 'Assignments, quizzes, and exams, all placed.' },
      { t: 'Study blocks suggested around upcoming due dates.' },
    ],
  },
  {
    kind: 'tutor',
    num: '11',
    kicker: 'AI Tutor',
    title: 'It asks. You answer.',
    desc: 'Three modes on the same concept. Socratic questions you toward it, expository explains it from your own materials, teachback makes you do the explaining.',
    bullets: [
      { t: 'Built to guide you, not to hand over the solution.' },
      { t: 'Grounded in your uploaded course materials.' },
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
    a: 'Not the way Sapling is built. It is designed to guide you toward the understanding rather than hand you the answer: Socratic questioning, explanations you have to apply yourself, and TeachBack, where you do the explaining. Using Sapling is like having a tutor, not a ghostwriter. The work, and the learning, is still yours.',
  },
  {
    q: 'Will it just do my homework for me?',
    a: "It's designed not to. Answer engines hand over the solution; Sapling walks you through the process and adapts to how you learn. If you paste a homework problem, expect guiding questions rather than a finished answer to copy.",
  },
  {
    q: 'How is this different from just using ChatGPT?',
    a: "A general chatbot forgets you the moment you close the tab. Sapling maps what you know, remembers what you struggled with, and grounds itself in your actual course materials. It's a study system, not a conversation.",
  },
  {
    q: 'Won’t I become dependent on the AI?',
    a: 'We built Sapling to make you less dependent over time. Mastery only turns green when you can demonstrate understanding, and TeachBack literally requires you to explain concepts yourself. The goal is that you walk into the exam without us.',
  },
  {
    q: 'What happens to my notes and documents?',
    a: "They stay yours. Document text, notes, and messages are encrypted at rest (AES-256-GCM). Sapling's AI runs on Google Gemini, and your content is never sold or used to train AI models. If Class Intel is on, passages from documents identified as course material can help answer classmates in the same course; your own work and notes stay private, and you can turn sharing off. Delete a document and its text and search data go with it.",
  },
  {
    q: 'Are tools like Sapling allowed in my classes?',
    a: "Sapling is a study aid, the same category as flashcards, tutoring, or a study group. It's built for studying, not for producing work to hand in. Every course sets its own rules on AI, so check your syllabus and follow it; our stance on academic integrity is in the Journal.",
  },
  {
    q: 'What does it cost?',
    a: "Nothing during beta. Beta testers get every feature free while we build, and a say in what we build next. Join the list below and you're in line.",
  },
  {
    q: 'What if the AI gets something wrong?',
    a: 'It can. Sapling grounds answers in your uploaded course materials, but AI output can still be wrong, so check it against your notes and slides. You stay the judge: tell the tutor what looks wrong and it will work through it with you, or report it with the feedback button.',
  },
];

/**
 * Float delays for the three landing journal cards, paired positionally with
 * POSTS. Negative delays desynchronise the cards' float loops.
 *
 * Everything else the cards render — tag, date, read time, artwork — comes
 * from the article table via POSTS. The old PostMeta carried an image path,
 * a photo/graph flag and hardcoded comment and like counts (12/84, 31/126,
 * 8/57) with nothing behind them; #601 removed the counts and moved artwork
 * onto the post.
 */
export const POST_FLOAT_DELAYS = ['0s', '-2.5s', '-5s'];

export interface Post {
  tag: string;
  /** Formatted by `dateLabel` — never hand-typed. */
  date: string;
  title: string;
  /** Derived from the article body by `readTime`. */
  time: string;
  excerpt: string;
  art: ArticleArt;
  /** /news/[slug] article this card opens. */
  slug: string;
}

/**
 * The three most recent articles, as landing cards.
 *
 * Derived rather than transcribed: the landing used to hold its own copy of
 * this metadata and had drifted (it tagged the graph post `Under the hood`
 * while every other surface said `Product`). Pulling the article table in
 * here also ships the article prose in the landing bundle — a few KiB of
 * text next to the landing's scroll rig, and the price of one source of
 * truth for read time, which cannot be computed without the body.
 */
export const POSTS: Post[] = JOURNAL_ARTICLES.slice(0, 3).map((article) => ({
  tag: article.tag,
  date: dateLabel(article.publishedAt),
  title: article.title,
  time: readTime(article.body),
  excerpt: article.deck,
  art: article.art,
  slug: article.slug,
}));
