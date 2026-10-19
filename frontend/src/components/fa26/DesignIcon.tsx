import React from "react";

/** Compact botanical marks used by the FA26 navigation. */
export function DesignIcon({ name, size = 22 }: { name: string; size?: number }) {
  const artwork: Record<string, React.ReactNode> = {
    home: <path d="M2 11 12 2l10 9h-4v10h-5v-6h-3v6H6V11Z" />,
    library: <><rect x="2" y="2" width="8" height="8" rx="2" /><path d="M13 10C12 4 17 1 23 2c0 6-4 9-10 8M10 13c1 6-4 10-9 9 0-6 4-10 9-9" /><rect x="13" y="13" width="8" height="8" rx="2" /></>,
    study: <><path d="m3 16 11-12 6 5L9 21H3Zm12-13 2-2 6 5-2 2Z" /><path d="M2 23h20" stroke="currentColor" strokeWidth="2" /></>,
    clov: <><path d="M12 2c3-3 7 0 6 4 5-1 7 4 3 7 3 4-1 8-5 6-1 5-7 5-8 0-4 2-8-2-5-6-4-3-2-8 3-7-1-4 3-7 6-4Z" /><circle cx="12" cy="11" r="3" fill="var(--fa26-sage)" /></>,
    tree: <><path d="M10 23V12C3 12 0 6 1 1c7 0 11 3 11 9C12 3 17 0 23 0c1 7-3 12-10 12v11Z" /><path d="M6 23h12" stroke="currentColor" strokeWidth="2" /></>,
    calendar: <><path d="M3 5h18v17H3Z" /><path d="M7 1v7m10-7v7M3 10h18" stroke="var(--fa26-sage)" strokeWidth="2" /><path d="m8 15 3 3 5-5" fill="none" stroke="var(--fa26-sage)" strokeWidth="2" /></>,
    notes: <><path d="M7 3h15v15H7Z" /><path d="M2 7h3v15h13v2H2Z" /><path d="M10 7h9m-9 4h9m-9 4h6" stroke="var(--fa26-sage)" strokeWidth="1.5" /></>,
    bell: <><path d="M4 17h16l-3-5V8a5 5 0 0 0-10 0v4Zm5 2h6a3 3 0 0 1-6 0" /><circle cx="12" cy="2" r="2" /></>,
    settings: <><path d="m9 1 1 3h4l1-3 4 3-1 3 3 3 3 1-1 5-4 1-2 3-1 4-5-1-1-3-4-2-3 1-2-5 3-2V8L1 6l3-4 3 1Z" /><circle cx="12" cy="12" r="4" fill="var(--fa26-paper)" /></>,
    report: <><path d="m12 1 11 20H1Z" /><path d="M12 7v7m0 3v1" stroke="var(--fa26-paper)" strokeWidth="2" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">{artwork[name] ?? artwork.tree}</svg>;
}

export function DesignSprout() {
  return <svg viewBox="0 0 46 72" width="46" height="72" fill="currentColor" aria-hidden="true" focusable="false">
    <path d="M22 37C7 36 0 23 1 8c14 0 24 7 24 20C25 10 35 2 45 0c3 20-5 32-18 36l-1 16 9 5-2 5-9-3-3 7 8 3-2 3H12l-2-4 7-5 1-14-9-7 3-5 9 6Z" />
  </svg>;
}
