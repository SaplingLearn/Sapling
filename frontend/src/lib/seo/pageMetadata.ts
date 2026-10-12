import type { Metadata } from 'next';

/**
 * Per-route metadata for the public surface.
 *
 * Next merges metadata per top-level key, not deeply: a page that sets no
 * `alternates` inherits the root layout's `canonical: '/'`, and one that sets
 * no `openGraph` inherits the home page's og:url/title/description. Before
 * this helper, /faq, /gallery, /news and /wiki all shipped
 * `<link rel="canonical" href="https://saplinglearn.com">` — telling search
 * engines each was a duplicate of the home page — and every route shared the
 * home page's og:title.
 *
 * Because the merge is shallow, whatever this returns for `openGraph` and
 * `twitter` REPLACES the root's, so it restates the site name and the shared
 * image rather than relying on inheritance.
 */

export const SITE_NAME = 'Sapling';
export const DEFAULT_OG_IMAGE = {
  url: '/og.png',
  width: 1200,
  height: 630,
  alt: 'Sapling — learn through conversation',
};

interface PageMetadataInput {
  /** Bare page title; the root layout's template appends " · Sapling". */
  title: string;
  description: string;
  /** Site-relative path, e.g. `/faq`. Becomes the canonical and og:url. */
  path: string;
  /** Article pages pass their own type, dates and artwork. */
  openGraph?: {
    type?: 'website' | 'article';
    publishedTime?: string;
    modifiedTime?: string;
    image?: string;
  };
}

export function pageMetadata({ title, description, path, openGraph = {} }: PageMetadataInput): Metadata {
  const image = openGraph.image ? { url: openGraph.image } : DEFAULT_OG_IMAGE;
  const ogTitle = `${title} · ${SITE_NAME}`;
  const base = { siteName: SITE_NAME, title: ogTitle, description, url: path, images: [image] };
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph:
      openGraph.type === 'article'
        ? {
            ...base,
            type: 'article',
            publishedTime: openGraph.publishedTime,
            modifiedTime: openGraph.modifiedTime,
          }
        : { ...base, type: 'website' },
    twitter: {
      card: 'summary_large_image',
      title: ogTitle,
      description,
      images: [image.url],
    },
  };
}
