// @vitest-environment jsdom
/**
 * #764: the Social screen's room-selection state machine.
 *   - leaving the active room selects another room (or the empty state),
 *     never a stale id that renders a blank pane;
 *   - a slow room-overview response for a room we already switched away from
 *     is dropped, so room A's members never become room B's mention list;
 *   - RoomChat is keyed by room, so an in-flight message load for room A
 *     cannot land in room B's transcript.
 */

import React from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act } from "@testing-library/react";

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
vi.mock("@/lib/supabase", () => ({ getSupabase: () => null }));

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

const overview = (roomId: string, memberName: string) => ({
  room: room(roomId, roomId),
  members: [{ user_id: `member-${roomId}`, name: memberName, graph: { nodes: [], edges: [] } }],
  ai_summary: "",
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

beforeEach(() => {
  // jsdom has no layout: the chat auto-scroll calls Element.scrollTo.
  Element.prototype.scrollTo = () => {};
  m.listPublicRooms.mockResolvedValue({ rooms: [] } as never);
  m.fetchFriends.mockResolvedValue({ friends: [] });
  m.fetchFriendRequests.mockResolvedValue({ incoming: [], outgoing: [] });
  m.getRoomMessages.mockResolvedValue({ messages: [], has_more: false });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("Social rooms (#764)", () => {
  it("after leaving the active room, the next room is selected (not a blank pane)", async () => {
    m.getUserRooms
      .mockResolvedValueOnce({ rooms: [room("r1", "Algebra"), room("r2", "Biology")] })
      .mockResolvedValueOnce({ rooms: [room("r2", "Biology")] });
    m.getRoomOverview.mockImplementation(async (id: string) => overview(id, `name-${id}`) as never);
    m.leaveRoom.mockResolvedValue({ left: true });

    render(<Social />);
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));

    fireEvent.click(screen.getByText("Overview"));
    const leave = await screen.findByTestId("social-room-leave");
    fireEvent.click(leave);
    fireEvent.click(leave); // useConfirm: second click commits

    await waitFor(() => expect(m.leaveRoom).toHaveBeenCalledWith("r1", "u1"));
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Biology"));
  });

  it("leaving your only room lands on the empty state", async () => {
    m.getUserRooms
      .mockResolvedValueOnce({ rooms: [room("r1", "Algebra")] })
      .mockResolvedValueOnce({ rooms: [] });
    m.getRoomOverview.mockImplementation(async (id: string) => overview(id, `name-${id}`) as never);
    m.leaveRoom.mockResolvedValue({ left: true });

    render(<Social />);
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));
    fireEvent.click(screen.getByText("Overview"));
    const leave = await screen.findByTestId("social-room-leave");
    fireEvent.click(leave);
    fireEvent.click(leave);

    await waitFor(() => expect(screen.getByText("Select or create a room to begin.")).toBeInTheDocument());
  });

  it("a slow overview for the room we left behind never lands on the new room", async () => {
    m.getUserRooms.mockResolvedValue({ rooms: [room("r1", "Algebra"), room("r2", "Biology")] });
    const slowR1 = deferred<never>();
    m.getRoomOverview.mockImplementation((id: string) =>
      id === "r1" ? slowR1.promise : Promise.resolve(overview("r2", "Bob In R2") as never));

    render(<Social />);
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));

    fireEvent.click(screen.getByTestId("social-room-item-r2"));
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Biology"));
    await waitFor(() => expect(m.getRoomOverview).toHaveBeenCalledWith("r2"));
    await act(async () => { slowR1.resolve(overview("r1", "Alice In R1") as never); });

    fireEvent.change(screen.getByTestId("social-chat-input"), { target: { value: "@" } });
    await waitFor(() => expect(screen.getByTestId("social-chat-mention-member-r2")).toBeInTheDocument());
    expect(screen.queryByTestId("social-chat-mention-member-r1")).toBeNull();
  });

  it("an in-flight message load for the previous room cannot land in the new room's chat", async () => {
    m.getUserRooms.mockResolvedValue({ rooms: [room("r1", "Algebra"), room("r2", "Biology")] });
    m.getRoomOverview.mockImplementation(async (id: string) => overview(id, `name-${id}`) as never);
    const slowR1 = deferred<{ messages: never[]; has_more: boolean }>();
    const msg = (id: string, text: string) => ({
      id, user_id: "u2", user_name: "Other", text, image_url: null, created_at: "2026-01-01T00:00:00Z",
      reply_to_id: null, is_deleted: false, edited_at: null, reply_to: null, reactions: [],
    });
    m.getRoomMessages.mockImplementation((id: string) =>
      id === "r1"
        ? (slowR1.promise as never)
        : Promise.resolve({ messages: [msg("b1", "hello from r2")], has_more: false } as never));

    render(<Social />);
    await waitFor(() => expect(screen.getByTestId("social-room-name")).toHaveTextContent("Algebra"));

    fireEvent.click(screen.getByTestId("social-room-item-r2"));
    await waitFor(() => expect(screen.getByTestId("social-chat-message-b1")).toBeInTheDocument());

    await act(async () => {
      slowR1.resolve({ messages: [msg("a1", "hello from r1")] as never[], has_more: false });
    });
    expect(screen.queryByTestId("social-chat-message-a1")).toBeNull();
    expect(screen.getByTestId("social-chat-message-b1")).toBeInTheDocument();
  });
});
