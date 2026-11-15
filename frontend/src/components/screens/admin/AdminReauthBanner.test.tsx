// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const startReauth = vi.fn();
vi.mock("@/lib/reauth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reauth")>();
  return { ...actual, startReauth: () => startReauth() };
});

import { notifyReauthRequired } from "@/lib/reauth";
import { AdminReauthBanner } from "./AdminReauthBanner";

afterEach(() => {
  cleanup();
  startReauth.mockReset();
});

describe("AdminReauthBanner", () => {
  it("renders only the live region until an admin call needs a fresh sign-in", () => {
    render(<AdminReauthBanner />);
    expect(screen.getByTestId("admin-reauth-region")).toBeInTheDocument();
    expect(screen.queryByTestId("admin-reauth-banner")).toBeNull();
  });

  it("offers to sign in again, and only goes when asked", () => {
    render(<AdminReauthBanner />);
    act(() => notifyReauthRequired());
    expect(screen.getByTestId("admin-reauth-banner")).toHaveTextContent(/sign in with Google again/i);
    expect(startReauth).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("admin-reauth-signin"));
    expect(startReauth).toHaveBeenCalledTimes(1);
  });
});
