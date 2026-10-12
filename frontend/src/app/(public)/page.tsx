import { JsonLd } from '@/components/seo/JsonLd';
import { CONTACT_EMAIL } from '@/lib/contact';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { FAQS } from '@/lib/landing/content';
import { faqPageLd, organizationLd, websiteLd } from '@/lib/seo/structuredData';
import LandingPage from './LandingPage';

/**
 * Server entry for `/`.
 *
 * The landing itself is a client component (`LandingPage.tsx`) — a scroll
 * cinema driven by one engine hook. This wrapper exists so the route can emit
 * its structured data from the server: the Organization and WebSite identity,
 * and FAQPage over the same `FAQS` rows the landing's FAQ section renders.
 * Title, description and canonical come from the root layout's metadata,
 * which already describes the home page.
 */
export default function Page() {
  const origin = resolveSiteUrl(process.env);
  return (
    <>
      <JsonLd
        data={[organizationLd(origin, CONTACT_EMAIL), websiteLd(origin), faqPageLd(origin, '/', FAQS)]}
      />
      <LandingPage />
    </>
  );
}
