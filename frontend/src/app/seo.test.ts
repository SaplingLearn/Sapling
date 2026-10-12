/**
 * B8 SEO surface (#169 #170 #171 #187): root + per-page metadata, robots,
 * sitemap, manifest, and the careers-slug hard 404.
 *
 * These import the App Router special files directly and assert on their
 * exported values — no rendering. layout.tsx pulls next/font/local, which
 * has no runtime outside the Next build, so it is mocked to inert variables.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// `next/font/local` is a default export taking one options object, where
// `next/font/google` was a named export per family. The fonts moved local so
// a build with no network reach still typesets correctly — see layout.tsx.
vi.mock('next/font/local', () => ({
  default: () => ({ variable: '', className: '' }),
}));

// notFound() throws in real Next; mirror that so the slug page's control flow
// is observable.
const NOT_FOUND = new Error('NEXT_NOT_FOUND');
vi.mock('next/navigation', () => ({
  notFound: vi.fn(() => {
    throw NOT_FOUND;
  }),
}));

import { metadata as rootMetadata } from './layout';
import { metadata as aboutMetadata } from './(public)/about/page';
import { metadata as privacyMetadata } from './(public)/privacy/page';
import { metadata as termsMetadata } from './(public)/terms/page';
import { metadata as careersMetadata } from './(public)/careers/page';
import { metadata as faqMetadata } from './(public)/faq/page';
import { metadata as newsMetadata } from './(public)/news/page';
import { metadata as galleryMetadata } from './(public)/gallery/page';
import { metadata as wikiMetadata } from './(public)/wiki/page';
import { generateMetadata as articleMetadata } from './(public)/news/[slug]/page';
import { JOURNAL_ARTICLES } from '@/lib/landing/journalArticles';
import { FAQS } from '@/lib/landing/content';
import { FAQ_ITEMS } from '@/lib/landing/companionContent';
import { LEGAL_LAST_UPDATED, legalDateLabel } from '@/lib/legal';
import { buildLlmsTxt } from '@/lib/seo/llmsTxt';
import { articleLd, faqPageLd, organizationLd, websiteLd } from '@/lib/seo/structuredData';
import SlugPage, { generateMetadata as slugMetadata } from './(public)/careers/[slug]/page';
import { JOBS } from './(public)/careers/jobs';
import robots from './robots';
import sitemap from './sitemap';
import manifest from './manifest';
import { checkFrontendDeployEnv, resolveSiteUrl } from '@/lib/deployGuard';

const ENV_KEYS = ['DEPLOY_ENV', 'NEXT_PUBLIC_SITE_URL'] as const;
const saved: Record<string, string | undefined> = {};
beforeEach(() => {
  for (const k of ENV_KEYS) {
    saved[k] = process.env[k];
    delete process.env[k];
  }
});
afterEach(() => {
  for (const k of ENV_KEYS) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
});

describe('#169 root metadata', () => {
  it('sets metadataBase, OG, twitter, canonical', () => {
    expect(rootMetadata.metadataBase).toBeInstanceOf(URL);
    expect(String(rootMetadata.metadataBase)).toContain('saplinglearn.com');
    const og = rootMetadata.openGraph!;
    expect(og.siteName).toBe('Sapling');
    expect(og.images).toBeTruthy();
    expect(rootMetadata.twitter).toMatchObject({ card: 'summary_large_image' });
    expect(rootMetadata.alternates?.canonical).toBe('/');
    expect(rootMetadata.description).toBeTruthy();
  });

  it('uses a title template so per-page titles compose', () => {
    expect(rootMetadata.title).toMatchObject({
      default: expect.stringContaining('Sapling'),
      template: expect.stringContaining('%s'),
    });
  });

  it('ships the OG image referenced by the metadata', () => {
    // metadataBase resolves relative image URLs against the deploy host, so
    // the file itself must exist in public/.
    expect(fs.existsSync(path.join(__dirname, '../../public/og.png'))).toBe(true);
  });
});

describe('#171 per-page metadata', () => {
  const PAGES = {
    '/about': aboutMetadata,
    '/privacy': privacyMetadata,
    '/terms': termsMetadata,
    '/careers': careersMetadata,
    '/faq': faqMetadata,
    '/news': newsMetadata,
    '/gallery': galleryMetadata,
    '/wiki': wikiMetadata,
  };

  it('gives each public page a distinct title', () => {
    const titles = Object.values(PAGES).map(m => m.title);
    expect(new Set(titles).size).toBe(titles.length);
    for (const m of Object.values(PAGES)) {
      expect(m.title).toBeTruthy();
      expect(m.description).toBeTruthy();
    }
  });

  // Metadata merges shallowly: a page without its own `alternates` inherits
  // the root's canonical '/', which declared /faq, /gallery, /news and /wiki
  // duplicates of the home page. Same for og:url via `openGraph`.
  it('gives each public page its own canonical and og:url', () => {
    for (const [path, m] of Object.entries(PAGES)) {
      expect(m.alternates?.canonical, path).toBe(path);
      expect((m.openGraph as { url?: string } | undefined)?.url, path).toBe(path);
      expect((m.openGraph as { images?: unknown[] } | undefined)?.images?.length, path).toBeGreaterThan(0);
    }
  });

  it('marks journal posts as articles with their publish date', async () => {
    const article = JOURNAL_ARTICLES[0];
    const meta = await articleMetadata({ params: Promise.resolve({ slug: article.slug }) });
    expect(meta.alternates?.canonical).toBe(`/news/${article.slug}`);
    expect(meta.openGraph).toMatchObject({ type: 'article', publishedTime: article.publishedAt });
  });

  // Skipped while JOBS is empty (no open roles) rather than deleted: the
  // assertion is still the one we want the moment a role goes back in.
  it.skipIf(JOBS.length === 0)('derives the job page title from the job', async () => {
    const job = JOBS[0];
    const meta = await slugMetadata({ params: Promise.resolve({ slug: job.slug }) });
    expect(String(meta.title)).toContain(job.title);
    expect(meta.description).toBeTruthy();
  });

  it('returns neutral metadata for an unknown slug', async () => {
    const meta = await slugMetadata({ params: Promise.resolve({ slug: 'does-not-exist' }) });
    expect(String(meta.title ?? '')).not.toContain('undefined');
  });
});

describe('#187 careers hard 404', () => {
  it('calls notFound() for an unknown slug', async () => {
    await expect(
      SlugPage({ params: Promise.resolve({ slug: 'does-not-exist' }) }),
    ).rejects.toBe(NOT_FOUND);
  });

  it.skipIf(JOBS.length === 0)('renders for a known slug', async () => {
    const el = await SlugPage({ params: Promise.resolve({ slug: JOBS[0].slug }) });
    expect(el).toBeTruthy();
  });
});

describe('#170 robots / sitemap / manifest', () => {
  it('robots allows the public surface and blocks the app shell', () => {
    const r = robots();
    const rules = Array.isArray(r.rules) ? r.rules : [r.rules];
    const flat = rules.flatMap(rule => {
      const d = rule?.disallow;
      return Array.isArray(d) ? d : d ? [d] : [];
    });
    for (const p of ['/dashboard', '/api/', '/auth/', '/settings']) {
      expect(flat.some(x => x.startsWith(p))).toBe(true);
    }
    expect(r.sitemap).toContain('/sitemap.xml');
  });

  it('robots blocks everything on staging', () => {
    process.env.DEPLOY_ENV = 'staging';
    const r = robots();
    const rules = Array.isArray(r.rules) ? r.rules : [r.rules];
    expect(rules[0]?.disallow).toBe('/');
    expect(rules.every(rule => !rule?.allow)).toBe(true);
  });

  it('sitemap enumerates every public route including job slugs', () => {
    const urls = sitemap().map(e => e.url);
    const base = resolveSiteUrl(process.env);
    for (const p of ['', '/about', '/faq', '/wiki', '/gallery', '/news', '/careers', '/privacy', '/terms']) {
      expect(urls).toContain(p ? `${base}${p}` : `${base}/`);
    }
    for (const job of JOBS) {
      expect(urls).toContain(`${base}/careers/${job.slug}`);
    }
    // Nothing private leaks into the sitemap.
    expect(urls.some(u => u.includes('/dashboard'))).toBe(false);
  });

  it('sitemap lists every journal post with its date as lastmod', () => {
    const entries = sitemap();
    const base = resolveSiteUrl(process.env);
    for (const article of JOURNAL_ARTICLES) {
      const entry = entries.find(e => e.url === `${base}/news/${article.slug}`);
      expect(entry?.lastModified).toBe(article.updatedAt ?? article.publishedAt);
    }
    const newest = JOURNAL_ARTICLES.map(a => a.updatedAt ?? a.publishedAt).sort().at(-1);
    expect(entries.find(e => e.url === `${base}/news`)?.lastModified).toBe(newest);
    expect(entries.find(e => e.url === `${base}/privacy`)?.lastModified).toBe(LEGAL_LAST_UPDATED);
  });

  // The sitemap is hand-listed, so pin it against the routes that exist: a
  // new public page fails here until it is listed, and a listed page that is
  // deleted fails the "every URL resolves" e2e.
  it('sitemap covers every static public route on disk', () => {
    const publicDir = path.join(__dirname, '(public)');
    const routes = fs
      .readdirSync(publicDir, { withFileTypes: true })
      .filter(d => d.isDirectory() && fs.existsSync(path.join(publicDir, d.name, 'page.tsx')))
      .map(d => `/${d.name}`);
    const urls = sitemap().map(e => new URL(e.url).pathname);
    for (const route of routes) expect(urls, route).toContain(route);
  });

  it('robots leaves the public surface open to AI search and user-agent fetchers', () => {
    // Only one `*` group exists, so OAI-SearchBot, ChatGPT-User, PerplexityBot,
    // Claude-SearchBot and Claude-User all fall to it. If a per-bot group is
    // ever added, it must not disallow '/'.
    const r = robots();
    const rules = Array.isArray(r.rules) ? r.rules : [r.rules];
    for (const rule of rules) {
      const d = rule?.disallow;
      const list = Array.isArray(d) ? d : d ? [d] : [];
      expect(list).not.toContain('/');
      for (const p of ['/faq', '/wiki', '/news', '/about', '/llms.txt']) {
        expect(list.some(x => p.startsWith(x))).toBe(false);
      }
    }
  });

  it('manifest carries identity, colors and icons', () => {
    const m = manifest();
    expect(m.name).toContain('Sapling');
    expect(m.short_name).toBeTruthy();
    expect(m.start_url).toBe('/');
    expect(m.theme_color).toMatch(/^#/);
    expect(m.background_color).toMatch(/^#/);
    expect(m.icons?.length).toBeGreaterThan(0);
  });
});

describe('resolveSiteUrl', () => {
  it('defaults to production', () => {
    expect(resolveSiteUrl({})).toBe('https://saplinglearn.com');
  });
  it('derives staging from DEPLOY_ENV', () => {
    expect(resolveSiteUrl({ DEPLOY_ENV: 'staging' })).toBe('https://staging.saplinglearn.com');
  });
  it('falls back to NEXT_PUBLIC_SITE_URL only when DEPLOY_ENV is unset (local/preview)', () => {
    expect(resolveSiteUrl({ NEXT_PUBLIC_SITE_URL: 'http://localhost:3000/' })).toBe(
      'http://localhost:3000',
    );
  });
  it('DEPLOY_ENV beats a stray NEXT_PUBLIC_SITE_URL (ADR-0022 single knob)', () => {
    expect(
      resolveSiteUrl({
        DEPLOY_ENV: 'production',
        NEXT_PUBLIC_SITE_URL: 'https://staging.saplinglearn.com',
      }),
    ).toBe('https://saplinglearn.com');
  });
  it('the build-time explicit lock flags a cross-env NEXT_PUBLIC_SITE_URL', () => {
    const problems = checkFrontendDeployEnv({
      DEPLOY_ENV: 'production',
      NEXT_PUBLIC_SITE_URL: 'https://staging.saplinglearn.com',
    });
    expect(problems.some(p => p.includes('NEXT_PUBLIC_SITE_URL'))).toBe(true);
    expect(checkFrontendDeployEnv({ DEPLOY_ENV: 'production' })).toEqual([]);
  });
});

describe('structured data', () => {
  const origin = 'https://saplinglearn.com';

  it('FAQPage mirrors the rendered FAQ rows exactly', () => {
    const home = faqPageLd(origin, '/', FAQS) as { mainEntity: { name: string; acceptedAnswer: { text: string } }[] };
    expect(home.mainEntity).toHaveLength(FAQS.length);
    expect(home.mainEntity[0]).toMatchObject({ name: FAQS[0].q, acceptedAnswer: { text: FAQS[0].a } });
    const faq = faqPageLd(origin, '/faq', FAQ_ITEMS) as { mainEntity: unknown[]; url: string };
    expect(faq.mainEntity).toHaveLength(FAQ_ITEMS.length);
    expect(faq.url).toBe(`${origin}/faq`);
  });

  it('Organization and WebSite link by @id', () => {
    const org = organizationLd(origin, 'x@example.com');
    const site = websiteLd(origin) as { publisher: { '@id': string } };
    expect(org['@type']).toBe('Organization');
    expect(site.publisher['@id']).toBe(org['@id']);
  });

  it('BlogPosting carries absolute URLs and the publish date', () => {
    const a = JOURNAL_ARTICLES[0];
    const ld = articleLd(origin, a) as { '@type': string; url: string; datePublished: string; image: string[] };
    expect(ld['@type']).toBe('BlogPosting');
    expect(ld.url).toBe(`${origin}/news/${a.slug}`);
    expect(ld.datePublished).toBe(a.publishedAt);
    expect(ld.image[0].startsWith(origin)).toBe(true);
  });
});

describe('llms.txt', () => {
  const body = buildLlmsTxt('https://saplinglearn.com');

  it('follows the llmstxt.org shape: H1, blockquote summary, H2 link sections', () => {
    const lines = body.split('\n');
    expect(lines[0]).toBe('# Sapling');
    expect(lines.find(l => l.startsWith('> '))).toBeTruthy();
    expect(body).toMatch(/^## About$/m);
    expect(body).toMatch(/^## Journal$/m);
    expect(body).toMatch(/^## Optional$/m);
  });

  it('links About, FAQ, Wiki and every journal post', () => {
    for (const p of ['/about', '/faq', '/wiki']) expect(body).toContain(`(https://saplinglearn.com${p})`);
    for (const a of JOURNAL_ARTICLES) expect(body).toContain(`/news/${a.slug})`);
  });
});

describe('legal date', () => {
  it('formats the ISO day without a timezone shift', () => {
    expect(legalDateLabel('2026-05-03')).toBe('May 3, 2026');
  });
});
