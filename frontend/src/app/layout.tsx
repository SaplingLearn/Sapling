import type { Metadata } from 'next';
import React from 'react';
import { Spectral, DM_Sans, Playfair_Display, JetBrains_Mono } from 'next/font/google';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { UserProvider } from '@/context/UserContext';
import { ToastProvider } from '@/components/ToastProvider';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import './globals.css';

const spectral = Spectral({
  subsets: ['latin'],
  weight: ['200', '300', '400', '500', '600', '700', '800'],
  style: ['normal', 'italic'],
  variable: '--font-spectral',
  display: 'swap',
});

const dmSans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-dm-sans',
  display: 'swap',
});

const playfairDisplay = Playfair_Display({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800', '900'],
  style: ['normal', 'italic'],
  variable: '--font-playfair',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains',
  display: 'swap',
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
      className={`${spectral.variable} ${dmSans.variable} ${playfairDisplay.variable} ${jetbrainsMono.variable}`}
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
