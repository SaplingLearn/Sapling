// @vitest-environment jsdom
/**
 * The Tutor's Saved tab (`saved_items`): Save under a tutor reply, the session
 * panel's Plan / Saved (n) tabs and the Saved list, one store per session so
 * they never disagree. The board (session.design.html) names the tab
 * "Saved (2)".
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { flags, fetchJSON } = vi.hoisted(() => ({ flags: {} as Record<string, string>, fetchJSON: vi.fn() }));
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off", useFlagMap: () => ({ flags, ready: true }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), fetchJSON: (...a: unknown[]) => fetchJSON(...a) }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import { ChatPanel, type ChatMsg } from "../../chat/ChatPanel";
import { SAVED_COPY, __resetSavedForTests, savedTitle, useSaveAction } from "./saved";
import { SessionPanel } from "./SessionPanel";

const BOARD = fs.readFileSync(path.join(__dirname, "../__fixtures__/session.design.html"), "utf8");
const REPLY: ChatMsg = { id: "m1", role: "assistant", content: "**Key idea:** linear probing\nCollisions walk to the next bucket." };
const ITEM = { id: "s1", session_id: "ses1", course_id: "c1", title: "Key idea: linear probing", content: REPLY.content, created_at: "" };

function Chat({ sessionId }: { sessionId: string | null }) {
  const action = useSaveAction(sessionId);
  return <ChatPanel messages={[REPLY, { id: "u1", role: "user", content: "ok" }]} onSend={() => {}} messageAction={action} />;
}

beforeEach(() => {
  __resetSavedForTests();
  fetchJSON.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") return { item: ITEM };
    if (init?.method === "DELETE") return { deleted: true };
    return { items: [] };
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  for (const k of Object.keys(flags)) delete flags[k];
});

describe("Saved", () => {
  it("a reply's title is its first line without markdown marks", () => {
    expect(savedTitle(REPLY.content)).toBe("Key idea: linear probing");
    expect(savedTitle("x".repeat(100))).toHaveLength(80);
    expect(BOARD).toContain("Saved (2)");
    expect(SAVED_COPY.tab(2)).toBe("Saved (2)");
  });

  it("saved_items off: no Save under the reply", () => {
    render(<Chat sessionId="ses1" />);
    expect(screen.queryByTestId("tutor-save-reply")).toBeNull();
    expect(fetchJSON).not.toHaveBeenCalled();
  });

  it("Save under a tutor reply (never the student's), then Saved; one read per session", async () => {
    flags.saved_items = "on";
    render(<Chat sessionId="ses1" />);
    const save = await screen.findByTestId("tutor-save-reply");
    expect(screen.getAllByTestId("tutor-save-reply")).toHaveLength(1);
    await act(async () => { fireEvent.click(save); });
    await waitFor(() => expect(screen.getByTestId("tutor-save-reply").textContent).toBe("Saved"));
    expect((screen.getByTestId("tutor-save-reply") as HTMLButtonElement).disabled).toBe(true);
    const post = fetchJSON.mock.calls.find((c) => c[1]?.method === "POST")!;
    expect(JSON.parse(post[1].body)).toEqual({ user_id: "u1", session_id: "ses1", title: "Key idea: linear probing", content: REPLY.content });
    expect(fetchJSON.mock.calls.filter((c) => !c[1]?.method)).toHaveLength(1);
  });

  it("the session panel: Plan and Saved (n) tabs; the Saved list opens and removes", async () => {
    flags.saved_items = "on";
    flags.session_v2 = "on";
    fetchJSON.mockImplementation(async (_url: string, init?: RequestInit) => (init?.method === "DELETE" ? { deleted: true } : { items: [ITEM] }));
    render(<SessionPanel plan={null} currentNodeId={null} skills={[]} dueCount={0} dueHref={null} map={null}
      treeHref="/tree" showTreeLink={false} onHide={() => {}} sessionId="ses1" />);
    const savedTab = await screen.findByTestId("tutor-panel-tab-saved");
    await waitFor(() => expect(savedTab.textContent).toBe("Saved (1)"));
    expect(screen.getByTestId("tutor-panel-tab-plan").getAttribute("aria-selected")).toBe("true");
    fireEvent.click(savedTab);
    const list = screen.getByTestId("tutor-saved-list");
    expect(within(list).getByText("Key idea: linear probing")).toBeTruthy();
    await act(async () => { fireEvent.click(within(list).getByRole("button", { name: /Remove/ })); });
    await waitFor(() => expect(screen.getByTestId("tutor-saved-empty").textContent).toBe(SAVED_COPY.empty));
    expect(savedTab.textContent).toBe("Saved");
  });
});
