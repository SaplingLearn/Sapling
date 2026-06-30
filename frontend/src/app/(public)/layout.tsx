import React from "react";

// Wraps the public / pre-auth surface (landing + marketing/legal pages) in the
// .public-surface scope, which carries the Layer-2 marketing tokens defined in
// globals.css. This is the structural home for the marketing layer — it replaces
// the ad-hoc per-page class and mirrors the (shell) group for the signed-in app.
// The landing page keeps its own .landing-page class for the mesh-background visual.
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <div className="public-surface">{children}</div>;
}
