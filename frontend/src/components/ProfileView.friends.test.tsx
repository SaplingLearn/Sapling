// @vitest-environment jsdom
/**
 * Task 16: the add-friend action on someone else's profile
 * (`AddFriendAction` in ProfileView.tsx).
 *
 * `fetchFriends`/`fetchFriendRequests` are self-only, so the component
 * checks the VIEWER's own lists to decide whether the profile being viewed
 * is already a friend or already has a pending outgoing request — this
 * pins that derivation, plus:
 *   - the action is absent entirely on your own profile;
 *   - a click sends the request and flips to a disabled "Request sent";
 *   - a 409 (already friends / already pending, discovered late) surfaces
 *     the server's detail via the existing toast and resyncs status rather
 *     than trusting the optimistic "pending" flip.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const userState = vi.hoisted(() => ({ userId: "viewer1" }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: userState.userId }),
}));

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  info: vi.fn(),
}));
vi.mock("./ToastProvider", () => ({
  useToast: () => toastSpies,
}));

vi.mock("./Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/lib/api", () => ({
  fetchFriends: vi.fn(),
  fetchFriendRequests: vi.fn(),
  sendFriendRequest: vi.fn(),
}));

import { AddFriendAction } from "./ProfileView";
import { fetchFriends, fetchFriendRequests, sendFriendRequest } from "@/lib/api";

const mockedFetchFriends = vi.mocked(fetchFriends);
const mockedFetchFriendRequests = vi.mocked(fetchFriendRequests);
const mockedSend = vi.mocked(sendFriendRequest);

function emptyRequests() {
  return { incoming: [], outgoing: [] };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  userState.userId = "viewer1";
});

describe("AddFriendAction", () => {
  it("renders nothing on your own profile, without fetching status", async () => {
    userState.userId = "profileUser1";
    render(<AddFriendAction profileUserId="profileUser1" />);

    // Give any stray effect a tick, then assert nothing rendered and no fetch fired.
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId("profile-add-friend")).toBeNull();
    expect(screen.queryByTestId("profile-friend-status")).toBeNull();
    expect(mockedFetchFriends).not.toHaveBeenCalled();
  });

  it("shows a Friends indicator (no button) when already friends", async () => {
    mockedFetchFriends.mockResolvedValue({
      friends: [{ user_id: "profileUser1", name: "Ada", level: 2, total_xp: 100 }],
    });
    mockedFetchFriendRequests.mockResolvedValue(emptyRequests());

    render(<AddFriendAction profileUserId="profileUser1" />);

    await waitFor(() => expect(screen.getByTestId("profile-friend-status")).toBeInTheDocument());
    expect(screen.getByText("Friends")).toBeInTheDocument();
    expect(screen.queryByTestId("profile-add-friend")).toBeNull();
  });

  it("shows a disabled Request sent when an outgoing request is already pending", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue({
      incoming: [],
      outgoing: [{ id: "r1", to_user_id: "profileUser1", name: "Ada", created_at: "2026-01-01" }],
    });

    render(<AddFriendAction profileUserId="profileUser1" />);

    const btn = await screen.findByTestId("profile-add-friend");
    expect(btn).toHaveTextContent("Request sent");
    expect(btn).toBeDisabled();
    expect(mockedSend).not.toHaveBeenCalled();
  });

  it("sends a request on click and flips to Request sent", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue(emptyRequests());
    mockedSend.mockResolvedValue({ request: { id: "r9" } });

    render(<AddFriendAction profileUserId="profileUser1" />);

    const btn = await screen.findByTestId("profile-add-friend");
    expect(btn).toHaveTextContent("Add friend");
    expect(btn).not.toBeDisabled();

    fireEvent.click(btn);

    await waitFor(() => expect(mockedSend).toHaveBeenCalledWith("viewer1", "profileUser1"));
    await waitFor(() => expect(screen.getByTestId("profile-add-friend")).toHaveTextContent("Request sent"));
    expect(screen.getByTestId("profile-add-friend")).toBeDisabled();
    expect(toastSpies.success).toHaveBeenCalled();
  });

  it("on 409 shows the server's detail via toast and resyncs to the real status", async () => {
    mockedFetchFriends.mockResolvedValueOnce({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValueOnce(emptyRequests());
    // The resync after the failed send discovers we're already friends —
    // some other path (e.g. they friended us first) beat this click.
    mockedFetchFriends.mockResolvedValueOnce({
      friends: [{ user_id: "profileUser1", name: "Ada", level: 2, total_xp: 100 }],
    });
    mockedFetchFriendRequests.mockResolvedValueOnce(emptyRequests());
    mockedSend.mockRejectedValue(new Error('{"detail":"Already friends."}'));

    render(<AddFriendAction profileUserId="profileUser1" />);

    const btn = await screen.findByTestId("profile-add-friend");
    fireEvent.click(btn);

    await waitFor(() => expect(mockedSend).toHaveBeenCalled());
    await waitFor(() => expect(toastSpies.error).toHaveBeenCalledWith("Already friends."));
    // Resynced from the optimistic "pending" flip to the server's "friends".
    await waitFor(() => expect(screen.getByTestId("profile-friend-status")).toBeInTheDocument());
    expect(screen.queryByTestId("profile-add-friend")).toBeNull();
  });
});
