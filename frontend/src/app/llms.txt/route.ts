import { resolveSiteUrl } from '@/lib/deployGuard';
import { buildLlmsTxt } from '@/lib/seo/llmsTxt';

/**
 * /llms.txt — the llmstxt.org index of the public site for language models.
 *
 * Generated rather than a file in public/ so the Journal list is the same
 * JOURNAL_ARTICLES table the sitemap and /news read, and a new post cannot be
 * missing here. Static at build time like robots.txt and sitemap.xml.
 */
export const dynamic = 'force-static';

export function GET() {
  return new Response(buildLlmsTxt(resolveSiteUrl(process.env)), {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
