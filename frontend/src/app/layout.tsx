import type { Metadata } from 'next';
import React from 'react';
import localFont from 'next/font/local';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { UserProvider } from '@/context/UserContext';
import { FlagsProvider } from '@/context/FlagsContext';
import { ToastProvider } from '@/components/ToastProvider';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import './globals.css';

/*
 * Self-hosted, not `next/font/google`.
 *
 * `next/font/google` downloads at build time, and when that fetch fails it
 * does not fail the build — it emits a metric-adjusted fallback and carries
 * on. This project shipped a whole session that way: every face on the site
 * was Times New Roman or Arial wearing the real font's metrics, close enough
 * that layout looked right and only the letterforms were wrong. The warning
 * for it sits in the dev log, which nobody reads while the page renders.
 *
 * The type is the approved Pen set from the redesign (#728): Aleo for
 * headings and long-form, SUSE for UI, IBM Plex Mono for numerals and code.
 * Each woff2 in ./fonts is a lossless conversion of the official
 * google/fonts binary (ttf SHA-256 62b6cb49… Aleo, 9b4c074d… Aleo Italic,
 * 16bda691… SUSE, 6a3412f0… / a9b4c49b… / d3c38e55… / ac27abd6… Plex Mono
 * 400/500/600/700), committed so the build never needs the network to be
 * typeset correctly. Aleo and SUSE are variable, one file spanning their
 * whole range; Plex Mono is static per weight.
 *
 * All three are SIL Open Font License 1.1 (the text sits beside each family
 * in ./fonts), which permits redistribution.
 */
const aleo = localFont({
  src: [
    { path: './fonts/Aleo-variable.woff2', weight: '100 900', style: 'normal' },
    { path: './fonts/Aleo-variable-italic.woff2', weight: '100 900', style: 'italic' },
  ],
  variable: '--font-aleo',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
  adjustFontFallback: 'Times New Roman',
});

const suse = localFont({
  src: './fonts/SUSE-variable.woff2',
  weight: '100 900',
  variable: '--font-suse',
  display: 'swap',
  fallback: ['system-ui', 'sans-serif'],
});

const plexMono = localFont({
  src: [
    { path: './fonts/IBM_Plex_Mono-400.woff2', weight: '400', style: 'normal' },
    { path: './fonts/IBM_Plex_Mono-500.woff2', weight: '500', style: 'normal' },
    { path: './fonts/IBM_Plex_Mono-600.woff2', weight: '600', style: 'normal' },
    { path: './fonts/IBM_Plex_Mono-700.woff2', weight: '700', style: 'normal' },
  ],
  variable: '--font-plex-mono',
  display: 'swap',
  fallback: ['ui-monospace', 'monospace'],
});

/*
 * The annotation hand. One use today — the landing gallery's "click to demo
 * the features!" note — and deliberately not wired into any token role, so it
 * stays a voice rather than becoming a fifth body face.
 *
 * `adjustFontFallback` is off: the system `cursive` behind this is Comic Sans
 * on Windows and Apple Chancery on macOS, faces whose metrics have nothing in
 * common with each other or with Caveat. Letting Next metric-match one of them
 * would reflow the note into whichever shape the swap happened to pick, and a
 * rotated scrawl beside an arrow is exactly where that shows.
 */
const caveat = localFont({
  src: './fonts/Caveat-variable.woff2',
  weight: '400 700',
  variable: '--font-caveat',
  display: 'swap',
  fallback: ['cursive'],
  adjustFontFallback: false,
});

const DESCRIPTION =
  'Sapling turns your syllabi, lecture notes, and readings into a living ' +
  'knowledge graph — with an AI tutor, quizzes, and study guides that grow with you.';

export const metadata: Metadata = {
  metadataBase: new URL(resolveSiteUrl(process.env)),
  title: {
    default: 'Sapling — learn through conversation',
    template: '%s · Sapling',
  },
  description: DESCRIPTION,
  alternates: { canonical: '/' },
  openGraph: {
    type: 'website',
    siteName: 'Sapling',
    title: 'Sapling — learn through conversation',
    description: DESCRIPTION,
    url: '/',
    images: [
      { url: '/og.png', width: 1200, height: 630, alt: 'Sapling — learn through conversation' },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Sapling — learn through conversation',
    description: DESCRIPTION,
    images: ['/og.png'],
  },
  icons: {
    icon: '/sapling-icon.svg',
    shortcut: '/sapling-icon.svg',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-accent="sage"
      data-density="compact"
      className={`${aleo.variable} ${suse.variable} ${plexMono.variable} ${caveat.variable}`}
    >
      <body>
        <ErrorBoundary>
          <ToastProvider>
            <UserProvider>
              <FlagsProvider>{children}</FlagsProvider>
            </UserProvider>
          </ToastProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
