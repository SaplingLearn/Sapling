// @vitest-environment jsdom
/**
 * The shell holds exactly one copy of a server-streamed page at every moment
 * (lib/streamedReveal.ts). e2e/upload.spec.ts intermittently found two
 * `library-upload` buttons on /library, one inside NavFeatureGate, one not:
 *
 * - React's streaming server renderer outlines the (shell) loading.tsx boundary
 *   around a big page: the fallback is sent in place and the page follows in a
 *   hidden `<div id="S:0">`, its reveal QUEUED (`$RC` → `$RB`; `$RV` runs on a
 *   later frame or ~300 ms after the first paint).
 * - React cannot hydrate a queued boundary. Right after hydration the shell's
 *   providers change their contexts and Next's layout router re-renders the
 *   segment above the page (InnerLayoutRouter's useDeferredValue), handing the
 *   loading boundary a fresh Suspense element. React gave up on the queued
 *   server HTML and rendered the page on the client — and the queued copy
 *   stayed in the document until the throttled reveal removed it.
 *
 * These tests stream the real shell (ShellFrame, NavFeatureGate, the (shell)
 * loading fallback) through react-dom/server, hydrate it with react-dom/client
 * through those updates, and count copies after every DOM change. React's
 * reveal timers fire only when a test runs them, as when hydration beats the
 * throttle.
 */
import React from "react";
import { act } from "@testing-library/react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToReadableStream } from "react-dom/server.browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/library", useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/useLayoutPref", () => ({ useLayoutPref: () => ["sidebar", () => {}] }));
vi.mock("./TopNav", () => ({ TopNav: () => <nav data-testid="top-nav" /> }));
vi.mock("./SideNav", () => ({ SideNav: () => <nav data-testid="side-nav" /> }));
vi.mock("./ShellActions", () => ({ ShellCornerActions: () => null }));
vi.mock("./FeedbackFlow", () => ({ FeedbackFlow: () => null }));
vi.mock("./SessionFeedbackGlobal", () => ({ SessionFeedbackGlobal: () => null }));
vi.mock("./AchievementUnlockWatcher", () => ({ AchievementUnlockWatcher: () => null }));

// The flags as FlagsProvider serves them: not ready on the server and through
// hydration, loaded afterwards. NavFeatureGate veils /library until they are.
const Flags = React.createContext({ flags: {} as Record<string, string>, ready: false });
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => React.useContext(Flags) }));

import ShellLoading from "@/app/(shell)/loading";
import { ShellFrame } from "./ShellFrame";
import { StreamedRevealGuard } from "./StreamedRevealGuard";

let loadFlags: () => void = () => {};
let rerenderSegment: () => void = () => {};

/** Flags load after hydration: in a mount effect (`onMount`), or on loadFlags(). */
function FlagsLoader({ onMount, children }: { onMount: boolean; children: React.ReactNode }) {
  const [ready, setReady] = React.useState(false);
  React.useEffect(() => {
    loadFlags = () => setReady(true);
    if (onMount) setReady(true);
  }, [onMount]);
  const value = React.useMemo(() => ({ flags: {}, ready }), [ready]);
  return <Flags.Provider value={value}>{children}</Flags.Provider>;
}

/** Next's layout router, reduced to what reaches the page's boundary: the
 *  segment router hands its child slot a fresh context object whenever it
 *  renders (InnerLayoutRouter's LayoutRouterContext), and the slot builds a new
 *  loading boundary when that changes (OuterLayoutRouter → LoadingBoundary).
 *  `deferred`: it re-renders once right after hydration, as InnerLayoutRouter's
 *  `useDeferredValue(rsc, prefetchRsc)` does; or on rerenderSegment(). */
const SegmentContext = React.createContext<object>({});

function SegmentRouter({ deferred, children }: { deferred: boolean; children: React.ReactNode }) {
  const [, setTick] = React.useState(0);
  React.useEffect(() => {
    rerenderSegment = () => setTick((t) => t + 1);
  }, []);
  const content = React.useDeferredValue(children, deferred ? children : undefined);
  return <SegmentContext.Provider value={{ segment: "(shell)" }}>{content}</SegmentContext.Provider>;
}

function LoadingBoundary({ children }: { children: React.ReactNode }) {
  React.useContext(SegmentContext);
  return <React.Suspense fallback={<ShellLoading />}>{children}</React.Suspense>;
}

/** A Library-sized page: past react-dom/server's 12.8 KB progressive chunk,
 *  so the boundary around it is outlined, as /library's is. */
function LibraryPage() {
  return (
    <div data-testid="library-page">
      <button data-testid="library-upload" disabled title="Enroll in a course first">Upload</button>
      {Array.from({ length: 120 }, (_, i) => (
        <article key={i}>
          <h3>{`document-${i}.pdf`}</h3>
          <p>Lecture notes covering vectors, matrices and linear transformations, auto-extracted.</p>
        </article>
      ))}
    </div>
  );
}

type Variant = { deferred: boolean; flagsOnMount: boolean };

function App({ deferred, flagsOnMount }: Variant) {
  return (
    <>
      <StreamedRevealGuard />
      <FlagsLoader onMount={flagsOnMount}>
        <SegmentRouter deferred={deferred}>
          <ShellFrame>
            <LoadingBoundary>
              <LibraryPage />
            </LoadingBoundary>
          </ShellFrame>
        </SegmentRouter>
      </FlagsLoader>
    </>
  );
}

const copies = () => document.querySelectorAll('[data-testid="library-upload"]').length;
const shells = () => document.querySelectorAll('[data-testid="app-shell"]').length;
const serverCopy = () => document.getElementById("S:0");

async function serverHtml(variant: Variant): Promise<string> {
  const stream = await renderToReadableStream(<App {...variant} />);
  await stream.allReady;
  return await new Response(stream).text();
}

/** The streamed HTML as the browser lays it out: the shell in the root
 *  container, then — as the stream arrives — the outlined content after it in
 *  <body> and React's inline runtime, run in the page's global (here the
 *  test's: the guard reads `window.$RB`). `arrive()` delivers the next part of
 *  the stream; with `until`, only up to the part `until` accepts. */
function streamDocument(html: string) {
  const parsed = document.createElement("template");
  parsed.innerHTML = html;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const [shell, ...rest] = Array.from(parsed.content.childNodes);
  container.appendChild(shell);
  const arrive = (until?: (node: Node) => boolean) => {
    while (rest.length > 0 && !(until?.(rest[0]) ?? false)) {
      const node = rest.shift()!;
      if (node instanceof HTMLScriptElement) (0, eval)(node.textContent ?? "");
      else document.body.appendChild(node);
    }
  };
  return { container, arrive };
}

const isOutlinedContent = (node: Node) => node instanceof HTMLElement && node.id === "S:0";

/** The copy count after every DOM change. */
function watchCopies(): { counts: number[]; stop: () => void } {
  const counts: number[] = [];
  const observer = new MutationObserver(() => counts.push(copies()));
  observer.observe(document, { childList: true, subtree: true, characterData: true });
  return { counts, stop: () => observer.disconnect() };
}

const RUNTIME_GLOBALS = ["$RB", "$RV", "$RC", "$RT", "$RX", "$RS", "$RR", "$RM"];
let root: Root | null = null;
let readyState: DocumentReadyState = "complete";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "setTimeout", "clearTimeout"] });
  readyState = "complete";
  Object.defineProperty(document, "readyState", { configurable: true, get: () => readyState });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = "";
  for (const key of RUNTIME_GLOBALS) delete (window as unknown as Record<string, unknown>)[key];
  delete (document as unknown as Record<string, unknown>).readyState;
  vi.useRealTimers();
});

describe("ShellFrame: one copy of a server-streamed page", () => {
  it("hydrates a page whose reveal is still queued when the router and the flags update after hydration", async () => {
    const variant = { deferred: true, flagsOnMount: true };
    const html = await serverHtml(variant);
    // The e2e state: the page outlined behind a reveal that is queued, not run.
    expect(html).toContain('<div hidden id="S:0">');
    expect(html).toContain('$RC("B:0","S:0")');
    const { container, arrive } = streamDocument(html);
    arrive();
    expect(document.body.innerHTML).toContain("<!--$~-->");
    expect(serverCopy()).not.toBeNull();
    expect(copies()).toBe(1);
    const serverButton = document.querySelector('[data-testid="library-upload"]');

    const watch = watchCopies();
    await act(async () => {
      root = hydrateRoot(container, <App {...variant} />);
    });
    await act(async () => {
      vi.runAllTimers(); // React's own reveal timer, and its retry
    });
    watch.stop();

    expect(watch.counts.length).toBeGreaterThan(0);
    expect(Math.max(...watch.counts)).toBe(1);
    expect(copies()).toBe(1);
    expect(shells()).toBe(1);
    expect(serverCopy()).toBeNull();
    const gate = document.querySelector('[data-testid="nav-feature-gate"]');
    expect(gate?.querySelector('[data-testid="library-upload"]')).not.toBeNull();
    expect(gate?.getAttribute("data-veiled")).toBeNull(); // the flags loaded
    // The server's copy was hydrated, not replaced by a client render.
    expect(document.querySelector('[data-testid="library-upload"]')).toBe(serverButton);
  });

  it("reveals a page that streams in after hydration before an update can render it again", async () => {
    const variant = { deferred: false, flagsOnMount: false };
    const html = await serverHtml(variant);
    readyState = "loading"; // the document is still streaming in
    const { container, arrive } = streamDocument(html);
    arrive(isOutlinedContent); // the shell, its fallback and the runtime so far

    const watch = watchCopies();
    await act(async () => {
      root = hydrateRoot(container, <App {...variant} />);
    });
    expect(copies()).toBe(0); // the page has not arrived: only the fallback
    await act(async () => {
      arrive(); // the outlined page, and its reveal queued behind a timer
    });
    expect(copies()).toBe(1);
    const serverButton = document.querySelector('[data-testid="library-upload"]');
    await act(async () => {
      loadFlags(); // updates while a throttled reveal would still be waiting
      rerenderSegment();
    });
    readyState = "complete";
    await act(async () => {
      vi.runAllTimers();
    });
    watch.stop();

    expect(Math.max(...watch.counts)).toBe(1);
    expect(copies()).toBe(1);
    expect(shells()).toBe(1);
    expect(serverCopy()).toBeNull();
    const button = document.querySelector('[data-testid="library-upload"]');
    expect(button?.closest('[data-testid="nav-feature-gate"]')).not.toBeNull();
    expect(button).toBe(serverButton); // hydrated, not rendered again on the client
  });
});
