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
      className="min-h-full bg-bg p-6"
    >
      <div className="max-w-270 my-0 mx-auto flex flex-col gap-3.5">
        <Skeleton width="38%" height={26} />
        <Skeleton width="100%" height={110} radius="var(--r-md)" />
        <div className="flex gap-3.5">
          <Skeleton width="50%" height={180} radius="var(--r-md)" />
          <Skeleton width="50%" height={180} radius="var(--r-md)" />
        </div>
      </div>
    </div>
  );
}
