// @vitest-environment jsdom
/**
 * UrlTab error states (#827): a 400 means the student's link is not a
 * quizlet.com set link (tell them how to fix it); a 422 means Quizlet itself
 * refused or redirected away (offer the Paste-tab fallback). Anything else
 * stays a toast.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    body?: unknown;
    constructor(message: string, status: number, fields: { body?: unknown } = {}) {
      super(message);
      this.status = status;
      this.body = fields.body;
    }
  }
  return { ApiError, importParse: vi.fn() };
});

vi.mock("@/lib/api", () => api);
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1" }) }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("../../ToastProvider", () => ({ useToast: () => toast }));

import { UrlTab } from "./UrlTab";

function submit(url: string) {
  fireEvent.change(screen.getByPlaceholderText(/quizlet\.com/), { target: { value: url } });
  fireEvent.click(screen.getByRole("button", { name: /fetch cards/i }));
}

function apiError(status: number, detail: string) {
  const text = JSON.stringify({ detail });
  return new api.ApiError(text, status, { body: { detail } });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("UrlTab", () => {
  it("explains a rejected (400) link and how to fix it", async () => {
    api.importParse.mockRejectedValueOnce(apiError(400, "Only https://quizlet.com set links can be imported."));
    render(<UrlTab onCards={() => {}} />);
    submit("https://example.com/x");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/isn.t a Quizlet set link/);
    expect(alert.textContent).toMatch(/quizlet\.com\/123456789/);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("offers the Paste fallback when Quizlet blocks or redirects away (422)", async () => {
    api.importParse.mockRejectedValueOnce(apiError(422, "Quizlet redirected away from quizlet.com"));
    render(<UrlTab onCards={() => {}} />);
    submit("https://quizlet.com/1/x");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Couldn.t fetch this URL/);
    expect(alert.textContent).toMatch(/Paste/);
    expect(alert.textContent).toMatch(/redirected away/);
  });

  it("toasts any other failure", async () => {
    api.importParse.mockRejectedValueOnce(apiError(500, "boom"));
    render(<UrlTab onCards={() => {}} />);
    submit("https://quizlet.com/1/x");
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("delivers cards on success", async () => {
    api.importParse.mockResolvedValueOnce({ cards: [{ front: "a", back: "b" }], errors: [] });
    const onCards = vi.fn();
    render(<UrlTab onCards={onCards} />);
    submit("http://quizlet.com/1/x");
    await waitFor(() => expect(onCards).toHaveBeenCalledWith([{ front: "a", back: "b", row: 1 }]));
  });
});
