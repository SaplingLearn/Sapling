import type { Metadata } from "next";
import React from "react";
import { SidebarProvider } from "@/lib/sidebar";
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
    <html lang="en" data-accent="sage" data-type="humanist" data-density="compact">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Geist:wght@400;500;600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <ErrorBoundary>
          <ToastProvider>
            <SidebarProvider>
              <UserProvider>{children}</UserProvider>
            </SidebarProvider>
          </ToastProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
