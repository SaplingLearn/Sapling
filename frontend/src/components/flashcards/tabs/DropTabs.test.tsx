// @vitest-environment jsdom
/**
 * The Upload and Photo tabs' drop areas. Each is one real <button> that opens
 * its (hidden) file input, so the keyboard reaches it, and still a drop
 * target. What a chosen or dropped file sends and parses is unchanged.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({ importParse: vi.fn() }));
vi.mock("@/lib/api", () => api);
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1" }) }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("../../ToastProvider", () => ({ useToast: () => toast }));

import { UploadTab } from "./UploadTab";
import { PhotoTab } from "./PhotoTab";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

const fileInput = (container: HTMLElement) => container.querySelector('input[type="file"]') as HTMLInputElement;

describe("UploadTab drop area", () => {
  it("is a button that opens the file dialog, and the hidden input stays out of the tab order", () => {
    const { container } = render(<UploadTab onCards={() => {}} />);
    const drop = screen.getByRole("button", { name: /Drop or click to upload \.csv/ });
    expect(drop).toHaveAttribute("type", "button");
    expect(drop).toHaveTextContent("Max 5MB");
    expect(screen.getAllByRole("button")).toHaveLength(1);

    const input = fileInput(container);
    expect(input).toHaveAttribute("hidden");
    expect(input).toHaveAttribute("tabindex", "-1");
    expect(input).toHaveAttribute("accept", ".csv,.tsv,.txt,.json,.xlsx,.apkg");
    const open = vi.spyOn(input, "click").mockImplementation(() => {});
    fireEvent.click(drop);
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("parses a chosen .csv locally and hands the cards up", async () => {
    const onCards = vi.fn();
    const { container } = render(<UploadTab onCards={onCards} />);
    const file = new File(["alpha,beta\ngamma,delta\n"], "cards.csv", { type: "text/csv" });
    fireEvent.change(fileInput(container), { target: { files: [file] } });
    await waitFor(() => expect(onCards).toHaveBeenCalledTimes(1));
    expect(onCards.mock.calls[0][0].map((c: { front: string; back: string }) => [c.front, c.back])).toEqual([
      ["alpha", "beta"],
      ["gamma", "delta"],
    ]);
    expect(api.importParse).not.toHaveBeenCalled();
  });

  it("takes a file dropped on the button", async () => {
    const onCards = vi.fn();
    render(<UploadTab onCards={onCards} />);
    const file = new File(["alpha\tbeta\n"], "cards.tsv", { type: "text/tab-separated-values" });
    fireEvent.drop(screen.getByRole("button"), { dataTransfer: { files: [file] } });
    await waitFor(() => expect(onCards).toHaveBeenCalledTimes(1));
    expect(onCards.mock.calls[0][0]).toEqual([expect.objectContaining({ front: "alpha", back: "beta" })]);
  });

  it("refuses an unsupported type with a toast", async () => {
    const onCards = vi.fn();
    const { container } = render(<UploadTab onCards={onCards} />);
    fireEvent.change(fileInput(container), { target: { files: [new File(["x"], "notes.docx")] } });
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Unsupported file type: .docx"));
    expect(onCards).not.toHaveBeenCalled();
  });
});

describe("PhotoTab drop area", () => {
  it("is a button that opens the file dialog", () => {
    const { container } = render(<PhotoTab onCards={() => {}} />);
    const drop = screen.getByRole("button", { name: /Drop or click to upload a photo of notes/ });
    const input = fileInput(container);
    expect(input).toHaveAttribute("hidden");
    expect(input).toHaveAttribute("accept", "image/*,.pdf");
    const open = vi.spyOn(input, "click").mockImplementation(() => {});
    fireEvent.click(drop);
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("sends a chosen image for OCR as base64 with its filename", async () => {
    api.importParse.mockResolvedValue({ cards: [{ front: "a", back: "b" }], errors: [] });
    const onCards = vi.fn();
    const { container } = render(<PhotoTab onCards={onCards} />);
    fireEvent.change(fileInput(container), { target: { files: [new File(["hi"], "notes.png", { type: "image/png" })] } });
    await waitFor(() => expect(onCards).toHaveBeenCalledWith([{ front: "a", back: "b", row: 1 }]));
    expect(api.importParse).toHaveBeenCalledWith("u1", "ocr", "aGk=", { filename: "notes.png" });
    expect(toast.success).toHaveBeenCalledWith("Extracted 1 cards from image.");
  });
});
