import { pageMetadata } from '@/lib/seo/pageMetadata';
import GalleryClient from './GalleryClient';

// Server wrapper so the route owns its metadata; the filterable grid stays a
// client child. Without this the page inherited the home page's title and
// canonical.
export const metadata = pageMetadata({
  title: 'Gallery',
  description:
    'Every screen in Sapling as it actually looks: the knowledge graph, AI tutor, adaptive quizzes, flashcards, study guides, calendar, gradebook, and study rooms.',
  path: '/gallery',
});

export default function GalleryPage() {
  return <GalleryClient />;
}
