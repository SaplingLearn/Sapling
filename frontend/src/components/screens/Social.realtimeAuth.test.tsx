// @vitest-environment jsdom
/**
 * RLS step 2e (#115): the Social screen, not the per-room RoomChat, owns the
 * Realtime token lifecycle: held ONCE for the screen, with no feature flag in
 * the way (realtime_rls graduated); switching rooms or tabs neither releases
 * it (dropping the token) nor re-acquires it (a re-mint). Which modes let
 * the channels join is planRoomRealtime's (Social.realtime.test.ts); the
 * channel wiring itself is covered by frontend/e2e/study-room.spec.ts.
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

const lifecycle = vi.hoisted(() => ({ acquires: 0, releases: 0, mode: "token" as string }));
vi.mock("@/lib/realtimeAuth", async () => {
  const { useEffect } = await import("react");
  return {
    recoverRealtimeAuth: vi.fn(async () => {}),
    superviseChannel: vi.fn(() => () => {}),
    useRealtimeAuth: () => {
      useEffect(() => {
        lifecycle.acquires += 1;
        return () => { lifecycle.releases += 1; };
      }, []);
      return { mode: lifecycle.mode, epoch: lifecycle.mode === "token" ? 1 : 0 };
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
  lifecycle.acquires = 0;
  lifecycle.releases = 0;
  lifecycle.mode = "token";
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
  it("held once for the screen across room and tab switches", async () => {
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

  it.each(["pending", "unavailable"])(
    "%s: still held once, and the room still loads over REST",
    async (mode) => {
      lifecycle.mode = mode;
      render(<Social />);
      await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));
      await waitFor(() => expect(m.getRoomMessages).toHaveBeenCalled());
      expect(lifecycle.acquires).toBe(1);
    },
  );
});
