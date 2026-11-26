// @vitest-environment jsdom
/**
 * Crossing the mobile breakpoint swaps the shell's nav (TopNav ↔ SideNav) but
 * must keep the page mounted: a remount drops a screen's in-memory state — a
 * quiz's results, a streaming tutor turn, unsaved input. The two layouts used
 * to place <main> at different element paths, so a window resize or a tablet
 * rotation reset the page (caught by e2e/quiz-written.spec.ts).
 */
import React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let mobile = true;
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => mobile }));
vi.mock("@/lib/useLayoutPref", () => ({ useLayoutPref: () => ["sidebar", () => {}] }));
vi.mock("./TopNav", () => ({ TopNav: () => <nav data-testid="top-nav" /> }));
vi.mock("./SideNav", () => ({ SideNav: () => <nav data-testid="side-nav" /> }));
vi.mock("./ShellActions", () => ({ ShellCornerActions: () => null }));
vi.mock("./FeedbackFlow", () => ({ FeedbackFlow: () => null }));
vi.mock("./SessionFeedbackGlobal", () => ({ SessionFeedbackGlobal: () => null }));
vi.mock("./AchievementUnlockWatcher", () => ({ AchievementUnlockWatcher: () => null }));
vi.mock("./NavFeatureGate", () => ({
  NavFeatureGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { ShellFrame } from "./ShellFrame";

let mounts = 0;
function Page() {
  const [value] = React.useState(() => {
    mounts += 1;
    return `mount-${mounts}`;
  });
  return <div data-testid="page">{value}</div>;
}

describe("ShellFrame", () => {
  afterEach(() => {
    cleanup();
    mobile = true;
    mounts = 0;
  });

  it("keeps the page mounted when the layout switches between mobile and sidebar", () => {
    const { rerender } = render(
      <ShellFrame>
        <Page />
      </ShellFrame>,
    );
    expect(screen.getByTestId("top-nav")).toBeTruthy();
    expect(screen.getByTestId("page").textContent).toBe("mount-1");

    act(() => {
      mobile = false;
    });
    rerender(
      <ShellFrame>
        <Page />
      </ShellFrame>,
    );
    expect(screen.getByTestId("side-nav")).toBeTruthy();
    expect(screen.getByTestId("page").textContent).toBe("mount-1");

    act(() => {
      mobile = true;
    });
    rerender(
      <ShellFrame>
        <Page />
      </ShellFrame>,
    );
    expect(screen.getByTestId("top-nav")).toBeTruthy();
    expect(mounts).toBe(1);
  });

  it("renders exactly one app-shell <main> in either layout", () => {
    render(
      <ShellFrame>
        <Page />
      </ShellFrame>,
    );
    expect(screen.getAllByTestId("app-shell")).toHaveLength(1);
  });
});
