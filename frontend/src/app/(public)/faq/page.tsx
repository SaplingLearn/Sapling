import { JsonLd } from '@/components/seo/JsonLd';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { FAQ_ITEMS } from '@/lib/landing/companionContent';
import { pageMetadata } from '@/lib/seo/pageMetadata';
import { faqPageLd } from '@/lib/seo/structuredData';
import FaqClient from './FaqClient';

// Server wrapper so the route owns its metadata and FAQPage schema; the
// accordion stays a client child. The schema reads FAQ_ITEMS, the same rows
// the accordion renders, so the two cannot drift.
export const metadata = pageMetadata({
  title: 'FAQ',
  description:
    'Straight answers about Sapling: academic integrity, how it differs from a general chatbot, what it costs, and what happens to your notes and documents.',
  path: '/faq',
});

export default function FaqPage() {
  return (
    <>
      <JsonLd data={faqPageLd(resolveSiteUrl(process.env), '/faq', FAQ_ITEMS)} />
      <FaqClient />
    </>
  );
}
