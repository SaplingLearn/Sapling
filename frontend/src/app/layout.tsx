import type { Metadata } from 'next';
import React from 'react';
import localFont from 'next/font/local';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { UserProvider } from '@/context/UserContext';
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
 * The woff2 files in ./fonts are the latin subset Google serves for exactly
 * the weights and styles declared below, committed so the build never needs
 * the network to be typeset correctly. Spectral is static per weight;
 * the other three are variable, one file spanning their whole range.
 *
 * All four are SIL Open Font License 1.1, which permits redistribution.
 */
const spectral = localFont({
  src: [
    { path: './fonts/Spectral-200.woff2', weight: '200', style: 'normal' },
    { path: './fonts/Spectral-300.woff2', weight: '300', style: 'normal' },
    { path: './fonts/Spectral-400.woff2', weight: '400', style: 'normal' },
    { path: './fonts/Spectral-500.woff2', weight: '500', style: 'normal' },
    { path: './fonts/Spectral-600.woff2', weight: '600', style: 'normal' },
    { path: './fonts/Spectral-700.woff2', weight: '700', style: 'normal' },
    { path: './fonts/Spectral-800.woff2', weight: '800', style: 'normal' },
    { path: './fonts/Spectral-200-italic.woff2', weight: '200', style: 'italic' },
    { path: './fonts/Spectral-300-italic.woff2', weight: '300', style: 'italic' },
    { path: './fonts/Spectral-400-italic.woff2', weight: '400', style: 'italic' },
    { path: './fonts/Spectral-500-italic.woff2', weight: '500', style: 'italic' },
    { path: './fonts/Spectral-600-italic.woff2', weight: '600', style: 'italic' },
    { path: './fonts/Spectral-700-italic.woff2', weight: '700', style: 'italic' },
    { path: './fonts/Spectral-800-italic.woff2', weight: '800', style: 'italic' },
  ],
  variable: '--font-spectral',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
  adjustFontFallback: 'Times New Roman',
});

const dmSans = localFont({
  src: './fonts/DM_Sans-variable.woff2',
  weight: '100 1000',
  variable: '--font-dm-sans',
  display: 'swap',
  fallback: ['system-ui', 'sans-serif'],
});

const playfairDisplay = localFont({
  src: [
    { path: './fonts/Playfair_Display-variable.woff2', weight: '400 900', style: 'normal' },
    { path: './fonts/Playfair_Display-variable-italic.woff2', weight: '400 900', style: 'italic' },
  ],
  variable: '--font-playfair',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
  adjustFontFallback: 'Times New Roman',
});

const jetbrainsMono = localFont({
  src: './fonts/JetBrains_Mono-variable.woff2',
  weight: '100 800',
  variable: '--font-jetbrains',
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
      className={`${spectral.variable} ${dmSans.variable} ${playfairDisplay.variable} ${jetbrainsMono.variable} ${caveat.variable}`}
    >
      <body>
        <ErrorBoundary>
          <ToastProvider>
            <UserProvider>{children}</UserProvider>
          </ToastProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
