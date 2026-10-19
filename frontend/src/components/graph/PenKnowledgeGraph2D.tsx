"use client";

import React from "react";
import type { GraphNode } from "@/lib/data";
import { sourceFillFor, truncateLabel } from "@/lib/graph/nodeStyle";
import { buildPenGraphLayout, penBranchFor, type PenGraphNodeLayout } from "@/lib/graph/penGraphGeometry";
import type { KnowledgeGraph2DProps } from "./KnowledgeGraph2D";
import styles from "./PenKnowledgeGraph2D.module.css";

type Point = { x: number; y: number };
type View = { tx: number; ty: number; scale: number };
type Gesture = {
  pointerId: number;
  start: Point;
  origin: Point;
  nodeId?: string;
  moved: boolean;
  captureTarget: SVGElement;
};
const INITIAL_VIEW: View = { tx: 0, ty: 0, scale: 1 };
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3;
const TOUCH_TARGET = { minWidth: 44, minHeight: 44 };
const TIER_LABEL = { mastered: "Mastered", learning: "Learning", struggling: "Struggling", unexplored: "Unexplored" };

/** The source paths are unchanged; responsive fitting only scales uniformly.
 * Learner graphs reuse those authored shapes with real IDs and relationships.
 * No simulation or mastery-dependent sizing moves a learner's map on refresh. */
function PenKnowledgeGraph2DImpl({
  nodes,
  edges,
  width = 600,
  height = 480,
  selectedId = null,
  highlightId,
  interactive = true,
  onNodeClick,
  comparison = null,
  comparisonColor = "#8a7bc4",
  comparisonLabel,
  viewControls = "all",
}: KnowledgeGraph2DProps) {
  const layout = React.useMemo(() => buildPenGraphLayout({ nodes, edges }), [nodes, edges]);
  const svgRef = React.useRef<SVGSVGElement>(null);
  const gestureRef = React.useRef<Gesture | null>(null);
  const suppressClickRef = React.useRef(false);
  const [view, setView] = React.useState<View>(INITIAL_VIEW);
  const [offsets, setOffsets] = React.useState<Record<string, Point>>({});
  const [hoveredId, setHoveredId] = React.useState<string | null>(null);
  const [focusedId, setFocusedId] = React.useState<string | null>(null);
  const prefix = React.useId().replace(/:/g, "");
  const fitScale = Math.min(width / Math.max(1, layout.width), height / Math.max(1, layout.height));
  const fitted = { tx: (width - layout.width * fitScale) / 2, ty: (height - layout.height * fitScale) / 2, scale: fitScale };
  const clampView = (next: View): View => {
    const scale = fitScale * next.scale;
    const bounded = (value: number, extent: number, viewport: number, origin: number) => {
      if (extent <= viewport) return (viewport - extent) / 2 - origin;
      return Math.max(viewport - extent - origin, Math.min(-origin, value));
    };
    return {
      scale: next.scale,
      tx: bounded(next.tx, layout.width * scale, width, fitted.tx),
      ty: bounded(next.ty, layout.height * scale, height, fitted.ty),
    };
  };
  // Stored pan distances are viewport pixels. Rebound them synchronously when
  // a resize or course filter changes the fitted canvas, before it is painted.
  // New gestures also begin from this displayed view rather than a stale pan.
  const boundedView = clampView(view);
  const shown = interactive ? { tx: fitted.tx + boundedView.tx, ty: fitted.ty + boundedView.ty, scale: fitted.scale * boundedView.scale } : fitted;
  const positions = new Map(layout.nodes.map(node => {
    const offset = offsets[node.id];
    // A scope change can repack the same ID against a smaller source canvas.
    // Retain its drag offset, but keep the current mark inside that canvas.
    return [node.id, offset ? {
      ...node,
      x: Math.max(node.r, Math.min(layout.width - node.r, node.x + offset.x)),
      y: Math.max(node.r, Math.min(layout.height - node.r, node.y + offset.y)),
    } : node];
  }));
  const orderedNodes = layout.nodes.filter(node => node.id !== selectedId);
  const selectedNode = layout.nodes.find(node => node.id === selectedId);
  if (selectedNode) orderedNodes.push(selectedNode);
  const comparisons = new Map((comparison ?? []).map(entry => [entry.name.trim().toLowerCase(), entry]));

  const svgPoint = (clientX: number, clientY: number): Point => {
    const rect = svgRef.current?.getBoundingClientRect();
    return {
      x: (clientX - (rect?.left ?? 0)) * (rect?.width ? width / rect.width : 1),
      y: (clientY - (rect?.top ?? 0)) * (rect?.height ? height / rect.height : 1),
    };
  };
  const zoomAt = (factor: number, anchor: Point) => setView(stored => {
    const previous = clampView(stored);
    const nextScale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, previous.scale * factor));
    const ratio = nextScale / previous.scale;
    return clampView({
      scale: nextScale,
      tx: anchor.x - fitted.tx - (anchor.x - fitted.tx - previous.tx) * ratio,
      ty: anchor.y - fitted.ty - (anchor.y - fitted.ty - previous.ty) * ratio,
    });
  });
  const handleWheel = React.useEffectEvent((event: WheelEvent) => {
    event.preventDefault();
    zoomAt(Math.exp(-event.deltaY * 0.0015), svgPoint(event.clientX, event.clientY));
  });
  React.useEffect(() => {
    if (!interactive) return;
    const svg = svgRef.current;
    if (!svg) return;
    const listener = (event: WheelEvent) => handleWheel(event);
    // React delegates wheel events passively. Exploration needs an explicit
    // non-passive listener so one wheel gesture cannot also scroll the page.
    svg.addEventListener("wheel", listener, { passive: false });
    return () => svg.removeEventListener("wheel", listener);
  }, [interactive]);

  const capture = (event: React.PointerEvent<SVGElement>) => {
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* Pointer capture is optional in older SVG engines. */ }
    return event.currentTarget;
  };
  const startPan = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!interactive || event.button !== 0) return;
    const captureTarget = capture(event);
    suppressClickRef.current = false;
    gestureRef.current = { pointerId: event.pointerId, start: svgPoint(event.clientX, event.clientY), origin: { x: boundedView.tx, y: boundedView.ty }, moved: false, captureTarget };
  };
  const startNodeDrag = (event: React.PointerEvent<SVGGElement>, node: PenGraphNodeLayout) => {
    if (!interactive || event.button !== 0) return;
    event.stopPropagation();
    const captureTarget = capture(event);
    suppressClickRef.current = false;
    const current = positions.get(node.id)!;
    gestureRef.current = { pointerId: event.pointerId, start: svgPoint(event.clientX, event.clientY), origin: { x: current.x, y: current.y }, nodeId: node.id, moved: false, captureTarget };
  };
  const movePointer = (event: React.PointerEvent<SVGSVGElement>) => {
    const gesture = gestureRef.current;
    if (!interactive || !gesture || gesture.pointerId !== event.pointerId) return;
    const point = svgPoint(event.clientX, event.clientY);
    const dx = point.x - gesture.start.x, dy = point.y - gesture.start.y;
    if (!gesture.moved && Math.hypot(dx, dy) < 3) return;
    gesture.moved = true;
    suppressClickRef.current = true;
    if (!gesture.nodeId) {
      setView(clampView({ ...boundedView, tx: gesture.origin.x + dx, ty: gesture.origin.y + dy }));
      return;
    }
    const node = layout.nodes.find(item => item.id === gesture.nodeId);
    if (!node) return;
    const x = Math.max(node.r, Math.min(layout.width - node.r, gesture.origin.x + dx / shown.scale));
    const y = Math.max(node.r, Math.min(layout.height - node.r, gesture.origin.y + dy / shown.scale));
    setOffsets(previous => ({ ...previous, [node.id]: { x: x - node.x, y: y - node.y } }));
  };
  const endPointer = (event: React.PointerEvent<SVGSVGElement>) => {
    if (gestureRef.current?.pointerId !== event.pointerId) return;
    const captureTarget = gestureRef.current.captureTarget;
    gestureRef.current = null;
    try { captureTarget.releasePointerCapture(event.pointerId); } catch { /* A canceled gesture may already have released capture. */ }
  };
  const activate = (node: GraphNode) => {
    if (interactive && !suppressClickRef.current) onNodeClick?.(node);
    suppressClickRef.current = false;
  };
  const reset = () => {
    gestureRef.current = null;
    suppressClickRef.current = false;
    setOffsets({});
    setView(INITIAL_VIEW);
  };

  return <div className={styles.container} style={{ width, height }}>
    <svg ref={svgRef} width={width} height={height} role="img" aria-label="Knowledge graph" data-renderer="pen" data-renderer-ready="true"
      className={styles.canvas} style={{ cursor: interactive ? "grab" : "default", touchAction: interactive ? "none" : "pan-y" }}
      onPointerDown={startPan} onPointerMove={movePointer} onPointerUp={endPointer} onPointerCancel={endPointer}>
      <g data-testid="graph-transform" transform={`translate(${shown.tx}, ${shown.ty}) scale(${shown.scale})`}>
        <g aria-hidden="true">
          {layout.edges.map((edge, index) => {
            const source = positions.get(edge.source), target = positions.get(edge.target);
            if (!source || !target) return null;
            const branch = offsets[source.id] || offsets[target.id] ? penBranchFor(source, target, index) : edge;
            const gradientId = `${prefix}-pen-edge-${index}`;
            return <g key={edge.id} transform={branch.transform}>
              <defs><linearGradient id={gradientId} gradientUnits="userSpaceOnUse" x1={branch.gradient.x1} y1={branch.gradient.y1} x2={branch.gradient.x2} y2={branch.gradient.y2} gradientTransform={branch.gradient.transform}>
                <stop offset="0%" stopColor={branch.gradient.from} /><stop offset="100%" stopColor={branch.gradient.to} />
              </linearGradient></defs>
              <path data-testid="graph-edge" data-edge-id={edge.id} data-source={edge.source} data-target={edge.target} data-source-path={branch.sourceId}
                d={branch.d} fill="none" stroke={`url(#${gradientId})`} strokeWidth={branch.strokeWidth / Math.max(0.000001, branch.projectionScale)} />
            </g>;
          })}
        </g>
        <g>
          {orderedNodes.map(node => {
            const position = positions.get(node.id)!;
            const color = sourceFillFor(node);
            const selected = node.id === selectedId;
            const focused = node.id === focusedId;
            const highlighted = node.id === highlightId;
            const active = selected || focused || highlighted || hoveredId === node.id;
            const partner = !node.is_subject_root && comparisons.get(node.name.trim().toLowerCase());
            return <g key={node.id} data-testid="graph-node" data-node-id={node.id} data-selected={selected || undefined} data-source-shape={node.sourceId}
              transform={`translate(${position.x}, ${position.y})`} className={styles.node}
              role={interactive && onNodeClick ? "button" : undefined} tabIndex={interactive && onNodeClick ? 0 : undefined}
              aria-label={`${node.name}, ${node.is_subject_root ? "Course" : TIER_LABEL[node.mastery_tier]}`}
              aria-pressed={interactive && onNodeClick ? selected : undefined}
              style={{ cursor: interactive ? onNodeClick ? "pointer" : "grab" : "default" }}
              onPointerDown={event => startNodeDrag(event, node)} onPointerEnter={() => interactive && setHoveredId(node.id)} onPointerLeave={() => setHoveredId(null)}
              onFocus={() => setFocusedId(node.id)} onBlur={() => setFocusedId(null)}
              onClick={event => { event.stopPropagation(); activate(node); }}
              onKeyDown={event => { if (interactive && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); suppressClickRef.current = false; onNodeClick?.(node); } }}>
              <title>{node.name}{node.is_subject_root ? " · Course" : ` · ${TIER_LABEL[node.mastery_tier]} · ${Math.round(node.mastery_score * 100)}% mastery`}</title>
              <circle r={Math.max(22 / shown.scale, node.r + 2)} fill="transparent" stroke="none" />
              {partner && <circle data-testid="graph-comparison-ring" r={node.r + 4 + partner.mastery_score * 5} fill="none" stroke={comparisonColor} strokeWidth={1.8} strokeDasharray="3 3" opacity={0.35 + partner.mastery_score * 0.55}>
                <title>{comparisonLabel || partner.partner_name ? `${comparisonLabel || partner.partner_name}: ` : ""}{Math.round(partner.mastery_score * 100)}% mastery on {node.name}</title>
              </circle>}
              <g transform={`translate(${-node.x}, ${-node.y})`} pointerEvents="none">
                <g transform={node.shapeTransform}>
                  <path data-testid="graph-node-circle" d={node.fillPath} transform={node.fillTransform} fill={color} opacity={1} />
                  <path d={node.outlinePath} transform={node.outlineTransform} fill="none" stroke={color} strokeWidth={node.strokeWidth} />
                </g>
              </g>
              {(selected || focused || highlighted) && <circle data-testid={selected ? "graph-node-selected-ring" : "graph-node-highlight-ring"} r={node.r + 6} fill="none" stroke="#416207" strokeWidth={2.5} strokeDasharray={highlighted && !selected ? "4 3" : undefined} pointerEvents="none" />}
              {node.is_subject_root && <text x={0} y={4} textAnchor="middle" fill="#F3EEE8" fontSize={14} fontFamily="var(--sapling-font-body, var(--font-sans))" fontWeight={600} pointerEvents="none">{truncateLabel(node.name.split(" - ")[0], 12)}</text>}
              {!node.is_subject_root && active && <text x={0} y={node.r + (selected ? 22 : 16)} textAnchor="middle" fontFamily="var(--sapling-font-body, var(--font-sans))" fontSize={selected ? 12.5 : 10.5} fontWeight={selected ? 600 : undefined} fill="#253D2F" stroke="#F7F4E9" strokeWidth={4} paintOrder="stroke" pointerEvents="none">{truncateLabel(node.name, selected ? 30 : 18)}</text>}
            </g>;
          })}
        </g>
      </g>
    </svg>
    {interactive && viewControls !== "none" && <div className={styles.controls} data-graph-controls aria-label="Knowledge graph view controls">
      <button type="button" className={styles.control} style={TOUCH_TARGET} aria-label="Zoom in" title="Zoom in" data-testid="graph-zoom-in" onClick={() => zoomAt(1.2, { x: width / 2, y: height / 2 })}>+</button>
      <button type="button" className={styles.control} style={TOUCH_TARGET} aria-label="Zoom out" title="Zoom out" data-testid="graph-zoom-out" onClick={() => zoomAt(1 / 1.2, { x: width / 2, y: height / 2 })}>−</button>
      {viewControls === "all" && <>
        <button type="button" className={styles.control} style={TOUCH_TARGET} aria-label="Reset view" title="Reset view" data-testid="graph-zoom-reset" onClick={reset}>↺</button>
        <button type="button" className={styles.control} style={TOUCH_TARGET} aria-label="Fit graph" title="Fit graph" data-testid="graph-zoom-fit" onClick={() => setView(INITIAL_VIEW)}>⤢</button>
      </>}
    </div>}
    <ul className={styles.srOnly} aria-label="Knowledge graph nodes" data-testid="graph-node-items">
      {nodes.map(node => <li key={node.id} data-testid="graph-node-item" data-node-id={node.id}>
        {onNodeClick && interactive ? <button type="button" data-testid="graph-node-activate" onFocus={() => setFocusedId(node.id)} onBlur={() => setFocusedId(null)} onClick={() => onNodeClick(node)}>{node.name}</button> : node.name}
      </li>)}
    </ul>
  </div>;
}

export const PenKnowledgeGraph2D = React.memo(PenKnowledgeGraph2DImpl);
