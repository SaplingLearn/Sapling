import React from "react";

// Wraps the public / pre-auth surface (landing + marketing/legal pages) in the
// .public-surface scope, which carries the Layer-2 marketing tokens defined in
// globals.css. This is the structural home for the marketing layer — it replaces
// the ad-hoc per-page class and mirrors the (shell) group for the signed-in app.
// The landing page supplies its own canvas through .landing-dc; the old
// .landing-page mesh-background scope went away with the page that wore it,
// and its rules were deleted from globals.css rather than left unreachable.
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <div className="public-surface">{children}</div>;
}
