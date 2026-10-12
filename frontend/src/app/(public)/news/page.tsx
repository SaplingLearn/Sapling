import { pageMetadata } from '@/lib/seo/pageMetadata';
import NewsIndex from './NewsIndex';

// Server wrapper so the route owns its metadata; the search and category
// filter stay a client child. Without this the page inherited the home
// page's title and canonical.
export const metadata = pageMetadata({
  title: 'News — The Sapling Journal',
  description:
    'Releases, decisions, and what we are learning about learning. Notes from the team building Sapling.',
  path: '/news',
});

export default function NewsPage() {
  return <NewsIndex />;
}
