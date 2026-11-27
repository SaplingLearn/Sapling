import { Skeleton } from "@/components/Skeleton";
import styles from "./loading.module.css";

// Instant paint for every (shell) route transition (#188). This fallback
// mounts INSIDE ShellFrame's <main> — the real TopNav/SideNav are persistent
// chrome rendered around the children slot — so it must be content-only:
// a fabricated topbar here would stack under the real one.
//
// On a full page load the server sends this fallback in place of a large page
// and the page after it, hidden, behind a queued reveal; the root layout's
// StreamedRevealGuard reveals it at hydration, so the page is never there
// twice (lib/streamedReveal.ts).

/** Placeholder heights (px): a screen title, a hero block, a card. */
const TITLE_H = 26;
const HERO_H = 110;
const CARD_H = 180;
const CARD_RADIUS = "var(--r-md)";

export default function ShellLoading() {
  return (
    <div data-testid="shell-loading" aria-busy className={styles.root}>
      <div className={styles.column}>
        <Skeleton width="38%" height={TITLE_H} />
        <Skeleton width="100%" height={HERO_H} radius={CARD_RADIUS} />
        <div className={styles.row}>
          <Skeleton width="50%" height={CARD_H} radius={CARD_RADIUS} />
          <Skeleton width="50%" height={CARD_H} radius={CARD_RADIUS} />
        </div>
      </div>
    </div>
  );
}
