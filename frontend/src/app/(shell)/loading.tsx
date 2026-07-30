import { Skeleton } from "@/components/Skeleton";

// Instant paint for every (shell) route transition (#188): a neutral
// topbar + content skeleton shown while the segment's client bundle and
// first data fetches resolve. Screen-specific skeletons take over once the
// page component mounts.
export default function ShellLoading() {
  return (
    <div
      data-testid="shell-loading"
      aria-busy
      style={{ minHeight: "100vh", background: "var(--bg)", padding: "16px 24px" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 28 }}>
        <Skeleton width={26} height={26} circle />
        <Skeleton width={140} height={16} />
        <div style={{ flex: 1 }} />
        <Skeleton width={90} height={28} radius="var(--r-full)" />
      </div>
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
