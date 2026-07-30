/**
 * B8 SEO surface (#169 #170 #171 #187): root + per-page metadata, robots,
 * sitemap, manifest, and the careers-slug hard 404.
 *
 * These import the App Router special files directly and assert on their
 * exported values — no rendering. layout.tsx pulls next/font/google, which
 * has no runtime outside the Next build, so it is mocked to inert variables.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

vi.mock('next/font/google', () => {
  const font = () => ({ variable: '', className: '' });
  return {
    Spectral: font,
    DM_Sans: font,
    Playfair_Display: font,
    JetBrains_Mono: font,
  };
});

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
  it('gives each public page a distinct title', () => {
    const titles = [aboutMetadata, privacyMetadata, termsMetadata, careersMetadata].map(
      m => m.title,
    );
    expect(new Set(titles).size).toBe(4);
    for (const m of [aboutMetadata, privacyMetadata, termsMetadata, careersMetadata]) {
      expect(m.title).toBeTruthy();
      expect(m.description).toBeTruthy();
      expect(m.alternates?.canonical).toBeTruthy();
    }
  });

  it('derives the job page title from the job', async () => {
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

  it('renders for a known slug', async () => {
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
    for (const p of ['', '/about', '/careers', '/privacy', '/terms']) {
      expect(urls).toContain(p ? `${base}${p}` : `${base}/`);
    }
    for (const job of JOBS) {
      expect(urls).toContain(`${base}/careers/${job.slug}`);
    }
    // Nothing private leaks into the sitemap.
    expect(urls.some(u => u.includes('/dashboard'))).toBe(false);
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
