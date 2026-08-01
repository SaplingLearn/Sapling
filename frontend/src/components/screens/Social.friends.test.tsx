// @vitest-environment jsdom
/**
 * Task 16: the Friends panel (`FriendsPanel` in Social.tsx).
 *
 * What's pinned here is the state-transition logic, not the markup:
 *   - incoming/outgoing sections only render when non-empty, with the
 *     incoming count chip;
 *   - every mutation (remove/accept/decline) refetches both `fetchFriends`
 *     and `fetchFriendRequests` afterward, so the lists can't drift from the
 *     server;
 *   - remove is gated behind the two-click `useConfirm` pattern used
 *     elsewhere in this file (real hook, not mocked, so the confirm
 *     mechanics themselves are exercised);
 *   - a failed accept/decline still refetches (self-correcting UI) and
 *     surfaces the server's detail via toast rather than silently vanishing
 *     the row.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  info: vi.fn(),
}));
vi.mock("../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

vi.mock("../Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));
vi.mock("../Avatar", () => ({
  Avatar: ({ name }: { name: string }) => <span data-testid="avatar">{name}</span>,
}));

vi.mock("@/lib/api", () => ({
  fetchFriends: vi.fn(),
  fetchFriendRequests: vi.fn(),
  acceptFriendRequest: vi.fn(),
  declineFriendRequest: vi.fn(),
  removeFriend: vi.fn(),
}));

import { FriendsPanel } from "./Social";
import {
  fetchFriends,
  fetchFriendRequests,
  acceptFriendRequest,
  declineFriendRequest,
  removeFriend,
} from "@/lib/api";

const mockedFetchFriends = vi.mocked(fetchFriends);
const mockedFetchFriendRequests = vi.mocked(fetchFriendRequests);
const mockedAccept = vi.mocked(acceptFriendRequest);
const mockedDecline = vi.mocked(declineFriendRequest);
const mockedRemove = vi.mocked(removeFriend);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function emptyRequests() {
  return { incoming: [], outgoing: [] };
}

describe("FriendsPanel", () => {
  it("hides incoming/outgoing sections when empty and shows the friends list", async () => {
    mockedFetchFriends.mockResolvedValue({
      friends: [{ user_id: "f1", name: "Ada", level: 3, total_xp: 450 }],
    });
    mockedFetchFriendRequests.mockResolvedValue(emptyRequests());

    render(<FriendsPanel />);

    await waitFor(() => expect(screen.getByTestId("friend-row-f1")).toBeInTheDocument());
    const row = within(screen.getByTestId("friend-row-f1"));
    expect(row.getByText("Lv 3 · 450 XP")).toBeInTheDocument();
    expect(screen.queryByText("Incoming requests")).toBeNull();
    expect(screen.queryByText("Outgoing")).toBeNull();
  });

  it("shows the incoming count chip and an outgoing pending list only when non-empty", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue({
      incoming: [{ id: "r1", from_user_id: "u2", name: "Bo", created_at: "2026-01-01" }],
      outgoing: [{ id: "r2", to_user_id: "u3", name: "Cy", created_at: "2026-01-01" }],
    });

    render(<FriendsPanel />);

    await waitFor(() => expect(screen.getByTestId("friend-incoming-r1")).toBeInTheDocument());
    expect(screen.getByText("Incoming requests")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument(); // count chip
    expect(screen.getByTestId("friend-outgoing-r2")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("removing a friend requires a second click, then calls removeFriend and refetches", async () => {
    mockedFetchFriends.mockResolvedValue({
      friends: [{ user_id: "f1", name: "Ada", level: 3, total_xp: 450 }],
    });
    mockedFetchFriendRequests.mockResolvedValue(emptyRequests());
    mockedRemove.mockResolvedValue({ removed: true });

    render(<FriendsPanel />);
    await waitFor(() => expect(screen.getByTestId("friend-remove-f1")).toBeInTheDocument());

    const btn = screen.getByTestId("friend-remove-f1");
    fireEvent.click(btn);
    expect(mockedRemove).not.toHaveBeenCalled();
    expect(screen.getByText("Click again")).toBeInTheDocument();

    expect(mockedFetchFriends).toHaveBeenCalledTimes(1);

    fireEvent.click(btn);
    await waitFor(() => expect(mockedRemove).toHaveBeenCalledWith("f1", "u1"));
    // Refetch after the mutation: a second call to both list fetches.
    await waitFor(() => expect(mockedFetchFriends).toHaveBeenCalledTimes(2));
    expect(mockedFetchFriendRequests).toHaveBeenCalledTimes(2);
  });

  it("accepting a request calls acceptFriendRequest and refetches both lists", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue({
      incoming: [{ id: "r1", from_user_id: "u2", name: "Bo", created_at: "2026-01-01" }],
      outgoing: [],
    });
    mockedAccept.mockResolvedValue({ accepted: true });

    render(<FriendsPanel />);
    await waitFor(() => expect(screen.getByTestId("friend-accept-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("friend-accept-r1"));

    await waitFor(() => expect(mockedAccept).toHaveBeenCalledWith("r1", "u1"));
    await waitFor(() => expect(mockedFetchFriends).toHaveBeenCalledTimes(2));
    expect(mockedFetchFriendRequests).toHaveBeenCalledTimes(2);
  });

  it("a failed decline (403/404 — already actioned) still refetches so the list corrects itself", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValueOnce({
      incoming: [{ id: "r1", from_user_id: "u2", name: "Bo", created_at: "2026-01-01" }],
      outgoing: [],
    });
    // Second call (post-mutation refetch) reflects the request having
    // already been withdrawn server-side.
    mockedFetchFriendRequests.mockResolvedValueOnce(emptyRequests());
    mockedDecline.mockRejectedValue(new Error('{"detail":"Request not found."}'));

    render(<FriendsPanel />);
    await waitFor(() => expect(screen.getByTestId("friend-decline-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("friend-decline-r1"));

    await waitFor(() => expect(mockedDecline).toHaveBeenCalledWith("r1", "u1"));
    expect(toastSpies.error).toHaveBeenCalled();
    // The row disappears because the refetch's server truth no longer has it,
    // not because we removed it optimistically.
    await waitFor(() => expect(screen.queryByTestId("friend-decline-r1")).toBeNull());
  });
});
