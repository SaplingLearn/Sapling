import type { Metadata } from 'next';
import { Spectral, DM_Sans, Inter, Playfair_Display, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Suspense } from 'react';
import { UserProvider } from '@/context/UserContext';
import Navbar from '@/components/Navbar';
import ErrorBoundary from '@/components/ErrorBoundary';
import FeedbackFlow from '@/components/FeedbackFlow';
import SessionFeedbackGlobal from '@/components/SessionFeedbackGlobal';

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
    <html lang="en" className={`${spectral.variable} ${dmSans.variable} ${inter.variable} ${playfairDisplay.variable} ${jetbrainsMono.variable}`}>
      <body>
        <UserProvider>
          <div style={{ position: 'relative', zIndex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
            <Navbar />
            <main style={{ flex: 1 }}><ErrorBoundary>{children}</ErrorBoundary></main>
            <Suspense fallback={null}><FeedbackFlow /></Suspense>
            <Suspense fallback={null}><SessionFeedbackGlobal /></Suspense>
          </div>
        </UserProvider>
      </body>
    </html>
  );
}
