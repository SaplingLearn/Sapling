"use client";
import React from "react";

export type SidebarLayout = "full" | "rail";

type Ctx = {
  layout: SidebarLayout;
  toggleLayout: () => void;
};

const SidebarContext = React.createContext<Ctx | null>(null);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [layout, setLayout] = React.useState<SidebarLayout>("full");
  const [hydrated, setHydrated] = React.useState(false);

  React.useEffect(() => {
    try {
      const v = localStorage.getItem("sapling-sidebar");
      if (v === "full" || v === "rail") setLayout(v);
    } catch {}
    setHydrated(true);
  }, []);

  React.useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem("sapling-sidebar", layout);
    } catch {}
  }, [layout, hydrated]);

  const toggleLayout = React.useCallback(() => {
    setLayout((l) => (l === "full" ? "rail" : "full"));
  }, []);

  return <SidebarContext.Provider value={{ layout, toggleLayout }}>{children}</SidebarContext.Provider>;
}

export function useSidebar(): Ctx {
  const ctx = React.useContext(SidebarContext);
  if (!ctx) throw new Error("useSidebar must be used within SidebarProvider");
  return ctx;
}
