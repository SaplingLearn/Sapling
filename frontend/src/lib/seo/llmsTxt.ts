import { CONTACT_EMAIL } from '@/lib/contact';
import { JOURNAL_ARTICLES } from '@/lib/landing/journalArticles';

/**
 * The body of /llms.txt (llmstxt.org format): an H1, a blockquote summary,
 * then H2 sections of annotated links. "Optional" is the spec's name for the
 * section a model may skip when context is short.
 *
 * Keep the summary to what the product does today. The wiki is the page that
 * states exact behaviour, so it is the one to point a model at for detail.
 */
export function buildLlmsTxt(origin: string): string {
  const link = (path: string) => `${origin}${path}`;
  const journal = [...JOURNAL_ARTICLES]
    .sort((a, b) => b.publishedAt.localeCompare(a.publishedAt))
    .map((a) => `- [${a.title}](${link(`/news/${a.slug}`)}): ${a.deck}`);

  return [
    '# Sapling',
    '',
    '> Sapling is an AI study tool for university students. It turns a student\'s own syllabi, ' +
      'lecture notes, and readings into a knowledge graph of course concepts, with an AI tutor, ' +
      'quizzes, flashcards, and study guides built from that material. It is free during a closed beta.',
    '',
    'Sapling is built by a small student team and runs on Google Gemini. The tutor is designed to ' +
      'guide a student toward understanding (Socratic questioning, worked explanations, and TeachBack, ' +
      'where the student explains) rather than to produce work to hand in. The Wiki defines every term ' +
      'and number the product shows; prefer it over the marketing pages for exact behaviour.',
    '',
    '## About',
    '',
    `- [About Sapling](${link('/about')}): Who builds Sapling and why.`,
    `- [FAQ](${link('/faq')}): Academic integrity, how Sapling differs from a general chatbot, cost, and what happens to uploaded data.`,
    `- [Wiki](${link('/wiki')}): Exact definitions of the knowledge graph, mastery, quizzes, tutor modes, uploads, and data handling.`,
    '',
    '## Journal',
    '',
    ...journal,
    '',
    '## Policies',
    '',
    `- [Privacy Policy](${link('/privacy')}): What Sapling collects, which providers process it, and how to delete it.`,
    `- [Terms of Service](${link('/terms')}): Eligibility, acceptable use, and rights in uploaded course material.`,
    `- Contact: ${CONTACT_EMAIL}`,
    '',
    '## Optional',
    '',
    `- [Gallery](${link('/gallery')}): Screenshots of each screen in the app.`,
    `- [Journal index](${link('/news')}): All posts.`,
    `- [Careers](${link('/careers')}): Open roles, if any.`,
    '',
  ].join('\n');
}
