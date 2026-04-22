import type { Metadata } from 'next';
import React from 'react';
import { Spectral, DM_Sans, Inter, Playfair_Display, JetBrains_Mono } from 'next/font/google';
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

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

const playfairDisplay = Playfair_Display({
  subsets: ['latin'],
  variable: '--font-playfair',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Sapling',
  description: 'Learn through conversation. Watch your knowledge grow.',
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
      className={`${spectral.variable} ${dmSans.variable} ${inter.variable} ${playfairDisplay.variable} ${jetbrainsMono.variable}`}
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
