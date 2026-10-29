// @vitest-environment jsdom
// frontend/src/components/screens/SummaryEditor/SourceViewer.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: () => ({
    promise: Promise.resolve({
      numPages: 1,
      getPage: () => Promise.resolve({
        getViewport: () => ({ width: 300, height: 400 }),
        render: () => ({ promise: Promise.resolve() }),
      }),
    }),
  }),
}));

import { SourceViewer } from "./SourceViewer";

afterEach(cleanup);

describe("SourceViewer", () => {
  it("renders a canvas for the single-page fixture", async () => {
    render(<SourceViewer pdfUrl="https://example.com/doc.pdf" onReference={() => {}} />);
    expect(await screen.findByTestId("summary-editor-source-page-0")).toBeInTheDocument();
  });

  it("captures a lasso drag and calls onReference with an image blob", async () => {
    const onReference = vi.fn();
    render(<SourceViewer pdfUrl="https://example.com/doc.pdf" onReference={onReference} />);
    const canvas = await screen.findByTestId("summary-editor-source-page-0");

    // jsdom's canvas 2D context is a stub (no real pixel buffer), but
    // HTMLCanvasElement.toBlob is still callable — this test exercises the
    // component's own pointer-event -> polygon -> export wiring, not
    // real rasterization (see the task's scope note).
    (canvas as HTMLCanvasElement).toBlob = (cb: BlobCallback) => cb(new Blob(["fake-png"], { type: "image/png" }));

    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(canvas, { clientX: 50, clientY: 10 });
    fireEvent.pointerMove(canvas, { clientX: 50, clientY: 50 });
    fireEvent.pointerMove(canvas, { clientX: 10, clientY: 50 });
    fireEvent.pointerUp(canvas, { clientX: 10, clientY: 50 });

    await Promise.resolve(); // let the toBlob callback microtask flush
    expect(onReference).toHaveBeenCalledWith({ kind: "image", blob: expect.any(Blob) });
  });

  it("does not call onReference for a drag too small to be a real lasso", async () => {
    const onReference = vi.fn();
    render(<SourceViewer pdfUrl="https://example.com/doc.pdf" onReference={onReference} />);
    const canvas = await screen.findByTestId("summary-editor-source-page-0");

    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(canvas, { clientX: 11, clientY: 10 });
    fireEvent.pointerUp(canvas, { clientX: 11, clientY: 10 });

    expect(onReference).not.toHaveBeenCalled();
  });
});
