"use client";

import { useEffect, useState } from "react";

export type LayoutPref = "topnav" | "sidebar";
export const LAYOUT_STORAGE_KEY = "sapling_layout";
const DEFAULT: LayoutPref = "topnav";

function read(): LayoutPref {
  if (typeof window === "undefined") return DEFAULT;
  const v = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
  return v === "sidebar" || v === "topnav" ? v : DEFAULT;
}

export function useLayoutPref(): [LayoutPref, (v: LayoutPref) => void] {
  const [pref, setPref] = useState<LayoutPref>(DEFAULT);

  useEffect(() => {
    setPref(read());
    const onStorage = (e: StorageEvent) => {
      if (e.key === LAYOUT_STORAGE_KEY) setPref(read());
    };
    const onCustom = () => setPref(read());
    window.addEventListener("storage", onStorage);
    window.addEventListener("sapling-layout-change", onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("sapling-layout-change", onCustom);
    };
  }, []);

  const update = (v: LayoutPref) => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, v);
    setPref(v);
    window.dispatchEvent(new Event("sapling-layout-change"));
  };

  return [pref, update];
}
