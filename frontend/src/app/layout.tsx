import type { Metadata } from 'next';
import React from 'react';
import { resolveSiteUrl } from '@/lib/deployGuard';
import { GUMMI_BOOT_SCRIPT } from '@/lib/licensedFonts';
import { UserProvider } from '@/context/UserContext';
import { FlagsProvider } from '@/context/FlagsContext';
import { ToastProvider } from '@/components/ToastProvider';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { fontVariables } from './fonts';
import './globals.css';


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
      className={fontVariables}
    >
      <head>
        {/* Before first paint, so a licensed host never flashes Aleo for long. */}
        <script dangerouslySetInnerHTML={{ __html: GUMMI_BOOT_SCRIPT }} />
      </head>
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
