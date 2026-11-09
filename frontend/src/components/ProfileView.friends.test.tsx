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
  acceptFriendRequest: vi.fn(),
  cancelFriendRequest: vi.fn(),
}));

import { AddFriendAction } from "./ProfileView";
import {
  fetchFriends, fetchFriendRequests, sendFriendRequest, acceptFriendRequest, cancelFriendRequest,
} from "@/lib/api";

const mockedFetchFriends = vi.mocked(fetchFriends);
const mockedFetchFriendRequests = vi.mocked(fetchFriendRequests);
const mockedSend = vi.mocked(sendFriendRequest);
const mockedAccept = vi.mocked(acceptFriendRequest);
const mockedCancel = vi.mocked(cancelFriendRequest);

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

  // #764 ────────────────────────────────────────────────────────────────────

  it("offers Accept (not Add friend) when this profile already sent the viewer a request", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue({
      incoming: [{ id: "in1", from_user_id: "profileUser1", name: "Ada", created_at: "2026-01-01" }],
      outgoing: [],
    });
    mockedAccept.mockResolvedValue({ accepted: true });

    render(<AddFriendAction profileUserId="profileUser1" />);

    const accept = await screen.findByTestId("profile-accept-friend");
    expect(screen.queryByTestId("profile-add-friend")).toBeNull();
    fireEvent.click(accept);

    await waitFor(() => expect(mockedAccept).toHaveBeenCalledWith("in1", "viewer1"));
    await waitFor(() => expect(screen.getByTestId("profile-friend-status")).toBeInTheDocument());
    expect(mockedSend).not.toHaveBeenCalled();
  });

  it("cancels an outgoing request back to Add friend", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue({
      incoming: [],
      outgoing: [{ id: "r1", to_user_id: "profileUser1", name: "Ada", created_at: "2026-01-01" }],
    });
    mockedCancel.mockResolvedValue({ cancelled: true });

    render(<AddFriendAction profileUserId="profileUser1" />);

    fireEvent.click(await screen.findByTestId("profile-cancel-friend-request"));

    await waitFor(() => expect(mockedCancel).toHaveBeenCalledWith("r1", "viewer1"));
    await waitFor(() => expect(screen.getByTestId("profile-add-friend")).toHaveTextContent("Add friend"));
    expect(screen.getByTestId("profile-add-friend")).not.toBeDisabled();
    expect(screen.queryByTestId("profile-cancel-friend-request")).toBeNull();
  });

  it("a request just sent can be cancelled using the id the send returned", async () => {
    mockedFetchFriends.mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue(emptyRequests());
    mockedSend.mockResolvedValue({ request: { id: "new1" } });
    mockedCancel.mockResolvedValue({ cancelled: true });

    render(<AddFriendAction profileUserId="profileUser1" />);
    fireEvent.click(await screen.findByTestId("profile-add-friend"));
    fireEvent.click(await screen.findByTestId("profile-cancel-friend-request"));

    await waitFor(() => expect(mockedCancel).toHaveBeenCalledWith("new1", "viewer1"));
  });

  it("resets when the viewed profile changes, and ignores the old profile's late answer", async () => {
    let resolveFirst: (v: { friends: { user_id: string; name: string; level: number; total_xp: number }[] }) => void = () => {};
    mockedFetchFriends
      .mockImplementationOnce(() => new Promise((res) => { resolveFirst = res; }))
      .mockResolvedValue({ friends: [] });
    mockedFetchFriendRequests.mockResolvedValue(emptyRequests());

    const { rerender } = render(<AddFriendAction profileUserId="profileUser1" />);
    rerender(<AddFriendAction profileUserId="profileUser2" />);

    const btn = await screen.findByTestId("profile-add-friend");
    expect(btn).toHaveTextContent("Add friend");

    // profileUser1's slow answer ("friends") arrives late and must not land.
    resolveFirst({ friends: [{ user_id: "profileUser1", name: "Ada", level: 1, total_xp: 0 }] });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId("profile-friend-status")).toBeNull();
    expect(screen.getByTestId("profile-add-friend")).toHaveTextContent("Add friend");
  });
});
