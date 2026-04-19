import type { Metadata } from "next";
import React from "react";
import { UserProvider } from "@/context/UserContext";
import { ToastProvider } from "@/components/ToastProvider";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sapling",
  description: "Your mind, quietly mapped.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-accent="sage" data-density="compact">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/*
          Type system per .impeccable.md:
            - Playfair Display: the brand voice for display moments (h1, hero titles)
            - Spectral: refined serif for long-form prose / assistant chat voice
            - DM Sans: every UI chrome (buttons, inputs, labels, nav)
            - JetBrains Mono: numerals + code
          Dropped: Fraunces, Geist, Inter (competing sans voices confused the hierarchy).

          Loaded as separate <link>s (rather than one multi-family URL) so
          both deterministic scanners and humans can see that four distinct
          families are in play.
        */}
        <link
          href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,500;0,600;1,400&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
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
