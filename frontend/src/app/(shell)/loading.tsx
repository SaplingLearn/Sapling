import { Skeleton } from "@/components/Skeleton";

// Instant paint for every (shell) route transition (#188). This fallback
// mounts INSIDE ShellFrame's <main> — the real TopNav/SideNav are persistent
// chrome rendered around the children slot — so it must be content-only:
// a fabricated topbar here would stack under the real one.
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
