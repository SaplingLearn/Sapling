import { Skeleton } from "@/components/Skeleton";

// Instant paint for every (shell) route transition (#188). This fallback
// mounts INSIDE ShellFrame's <main> — the real TopNav/SideNav are persistent
// chrome rendered around the children slot — so it must be content-only:
// a fabricated topbar here would stack under the real one.
//
// On a full page load the server sends this fallback in place of a large page
// and the page after it, hidden, behind a queued reveal; the root layout's
// StreamedRevealGuard reveals it at hydration, so the page is never there
// twice (lib/streamedReveal.ts).
export default function ShellLoading() {
  return (
    <div
      data-testid="shell-loading"
      aria-busy
      style={{ minHeight: "100%", background: "var(--bg)", padding: "24px" }}
    >
      <div style={{ maxWidth: 1080, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
        <Skeleton width="38%" height={26} />
        <Skeleton width="100%" height={110} radius="var(--r-md)" />
        <div style={{ display: "flex", gap: 14 }}>
          <Skeleton width="50%" height={180} radius="var(--r-md)" />
          <Skeleton width="50%" height={180} radius="var(--r-md)" />
        </div>
      </div>
    </div>
  );
}
