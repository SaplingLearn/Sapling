import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Sapling — learn through conversation',
    short_name: 'Sapling',
    description:
      'Sapling turns your syllabi, lecture notes, and readings into a living ' +
      'knowledge graph — with an AI tutor, quizzes, and study guides that grow with you.',
    start_url: '/',
    display: 'standalone',
    // --ink-0 / --brand-forest from globals.css.
    background_color: '#faf8f3',
    theme_color: '#1B6C42',
    icons: [{ src: '/sapling-icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
  };
}
