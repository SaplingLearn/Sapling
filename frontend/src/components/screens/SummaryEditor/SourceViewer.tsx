"use client";
import React from "react";
import type { AskReference } from "@/lib/types";

export interface SourceViewerProps {
  pdfUrl: string;
  onReference: (reference: AskReference) => void;
}

type Point = { x: number; y: number };

// Below this many CSS pixels of travel, a pointerdown->pointerup is a
// click/tap, not a deliberate lasso — ignore it rather than crop a
// near-empty sliver (and surprise the student with a reference chip they
// didn't mean to attach).
const MIN_LASSO_SPAN = 8;

function spanOf(points: Point[]): number {
  if (points.length < 2) return 0;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  return Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
}

function cropToLasso(canvas: HTMLCanvasElement, points: Point[], onReference: (r: AskReference) => void) {
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const width = Math.max(...xs) - minX;
  const height = Math.max(...ys) - minY;
  if (width < 1 || height < 1) return;

  const crop = document.createElement("canvas");
  crop.width = width;
  crop.height = height;
  const ctx = crop.getContext("2d");

  // jsdom (without the optional "canvas" npm package) returns null from
  // getContext('2d') for every canvas — there's no real 2D context to
  // draw/clip into there. Real browsers always have one. When it's
  // unavailable, fall back to exporting the source canvas as-is: that
  // keeps the pointer-event -> polygon -> export wiring exercisable
  // without pulling in native canvas rasterization (see this component's
  // test file, which mocks toBlob on the source canvas for exactly this
  // reason — true pixel cropping is proven by the Task 14 E2E run, not here).
  const exportCanvas = ctx ? crop : canvas;

  if (ctx) {
    // White-fill first: the area inside the bounding box but OUTSIDE the
    // drawn outline stays white rather than transparent — this fill must
    // happen BEFORE the clip is applied, or the clip would mask it too.
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, width, height);

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(points[0].x - minX, points[0].y - minY);
    for (const p of points.slice(1)) ctx.lineTo(p.x - minX, p.y - minY);
    ctx.closePath();
    ctx.clip();
    ctx.drawImage(canvas, minX, minY, width, height, 0, 0, width, height);
    ctx.restore();
  }

  exportCanvas.toBlob((blob) => {
    if (blob) onReference({ kind: "image", blob });
  }, "image/png");
}

export function SourceViewer({ pdfUrl, onReference }: SourceViewerProps) {
  const [pageCount, setPageCount] = React.useState(0);
  const canvasRefs = React.useRef<(HTMLCanvasElement | null)[]>([]);
  const drawingRef = React.useRef<Point[] | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const pdfjs = await import("pdfjs-dist");
      const doc = await pdfjs.getDocument({ url: pdfUrl }).promise;
      if (cancelled) return;
      setPageCount(doc.numPages);
      for (let i = 0; i < doc.numPages; i++) {
        const page = await doc.getPage(i + 1);
        const viewport = page.getViewport({ scale: 1.5 });
        const canvas = canvasRefs.current[i];
        if (!canvas || cancelled) continue;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvas, viewport }).promise;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pdfUrl]);

  const pointFromEvent = (canvas: HTMLCanvasElement, e: React.PointerEvent): Point => {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  return (
    <div style={{ overflowY: "auto", height: "100%" }}>
      {Array.from({ length: pageCount }, (_, i) => i).map((i) => (
        <canvas
          key={i}
          data-testid={`summary-editor-source-page-${i}`}
          ref={(el) => {
            canvasRefs.current[i] = el;
          }}
          style={{ display: "block", marginBottom: 12, cursor: "crosshair", maxWidth: "100%" }}
          onPointerDown={(e) => {
            const canvas = e.currentTarget;
            drawingRef.current = [pointFromEvent(canvas, e)];
          }}
          onPointerMove={(e) => {
            if (!drawingRef.current) return;
            drawingRef.current.push(pointFromEvent(e.currentTarget, e));
          }}
          onPointerUp={(e) => {
            const points = drawingRef.current;
            drawingRef.current = null;
            if (!points || spanOf(points) < MIN_LASSO_SPAN) return;
            cropToLasso(e.currentTarget, points, onReference);
          }}
        />
      ))}
    </div>
  );
}
