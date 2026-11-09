// @vitest-environment jsdom
/**
 * RLS step 2e (#115): the Social screen, not the per-room RoomChat, owns the
 * Realtime token lifecycle.
 *   - flags still loading: the lifecycle is not held (no token request, and
 *     the channels wait instead of joining with the anon key);
 *   - flag off: never held;
 *   - flag on: held ONCE for the screen; switching rooms or tabs neither
 *     releases it (a revert to anon) nor re-acquires it (a re-mint).
 */
import React from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, userName: "Me" }),
}));
vi.mock("../ToastProvider", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() }),
}));
vi.mock("../Icon", () => ({ Icon: () => <span /> }));
vi.mock("../Avatar", () => ({ Avatar: () => <span /> }));

const flagState = vi.hoisted(() => ({ flags: {} as Record<string, string>, ready: true }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => flagState,
  useFlag: (key: string) => flagState.flags[key] ?? "off",
}));

const lifecycle = vi.hoisted(() => ({ acquires: 0, releases: 0, enabledCalls: [] as boolean[] }));
vi.mock("@/lib/realtimeAuth", async () => {
  const { useEffect } = await import("react");
  return {
    recoverRealtimeAuth: vi.fn(async () => {}),
    superviseChannel: vi.fn(() => () => {}),
    useRealtimeAuth: (enabled: boolean) => {
      lifecycle.enabledCalls.push(enabled);
      useEffect(() => {
        if (!enabled) return;
        lifecycle.acquires += 1;
        return () => { lifecycle.releases += 1; };
      }, [enabled]);
      return { mode: enabled ? "token" : "off", epoch: enabled ? 1 : 0 };
    },
  };
});

vi.mock("@/lib/api", () => ({
  getUserRooms: vi.fn(),
  createRoom: vi.fn(),
  joinRoom: vi.fn(),
  listPublicRooms: vi.fn(),
  joinPublicRoom: vi.fn(),
  getRoomMessages: vi.fn(),
  sendRoomMessage: vi.fn(),
  editRoomMessage: vi.fn(),
  deleteRoomMessage: vi.fn(),
  toggleRoomReaction: vi.fn(),
  leaveRoom: vi.fn(),
  kickMember: vi.fn(),
  getRoomOverview: vi.fn(),
  getRoomActivity: vi.fn(),
  findStudyMatches: vi.fn(),
  getStudents: vi.fn(),
  fetchFriends: vi.fn(),
  fetchFriendRequests: vi.fn(),
  acceptFriendRequest: vi.fn(),
  declineFriendRequest: vi.fn(),
  cancelFriendRequest: vi.fn(),
  removeFriend: vi.fn(),
}));

import { Social } from "./Social";
import * as api from "@/lib/api";

const m = vi.mocked(api);

const room = (id: string, name: string) => ({
  id, name, invite_code: `CODE${id}`, member_count: 2, owner_id: "u1", created_by: "u1",
  topic: null, course: null, is_public: false, created_at: "2026-01-01", updated_at: null,
});

beforeEach(() => {
  Element.prototype.scrollTo = () => {};
  flagState.flags = {};
  flagState.ready = true;
  lifecycle.acquires = 0;
  lifecycle.releases = 0;
  lifecycle.enabledCalls = [];
  m.listPublicRooms.mockResolvedValue({ rooms: [] } as never);
  m.fetchFriends.mockResolvedValue({ friends: [] });
  m.fetchFriendRequests.mockResolvedValue({ incoming: [], outgoing: [] });
  m.getRoomMessages.mockResolvedValue({ messages: [], has_more: false });
  m.getUserRooms.mockResolvedValue({ rooms: [room("r1", "Algebra"), room("r2", "Biology")] });
  m.getRoomOverview.mockResolvedValue({ room: room("r1", "Algebra"), members: [], ai_summary: "" } as never);
  m.getRoomActivity.mockResolvedValue({ activities: [] } as never);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("Social realtime token lifecycle (RLS step 2e)", () => {
  it("flag on: held once for the screen across room and tab switches", async () => {
    flagState.flags = { realtime_rls: "on" };
    render(<Social />);
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));
    expect(lifecycle.acquires).toBe(1);

    fireEvent.click(screen.getByTestId("social-room-item-r2"));
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Biology"));
    fireEvent.click(screen.getByText("Overview"));
    fireEvent.click(screen.getByText("Chat"));
    await waitFor(() => expect(screen.getByTestId("social-chat-input")).toBeInTheDocument());

    expect(lifecycle.acquires).toBe(1);
    expect(lifecycle.releases).toBe(0);
  });

  it("flags loading: the lifecycle is not held until they are ready", async () => {
    flagState.flags = { realtime_rls: "on" };
    flagState.ready = false;
    render(<Social />);
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));
    expect(lifecycle.acquires).toBe(0);
    expect(lifecycle.enabledCalls.every((e) => e === false)).toBe(true);
  });

  it("flag off: never held", async () => {
    render(<Social />);
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));
    expect(lifecycle.acquires).toBe(0);
    expect(lifecycle.enabledCalls.every((e) => e === false)).toBe(true);
  });
});
