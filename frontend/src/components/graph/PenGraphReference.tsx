"use client";

import React from "react";
import { PEN_NATIVE_GRAPH_REFERENCE } from "@/lib/graph/penNativeGraphSource";

type SourcePath = {
  sourceId: string;
  sourcePath: number;
  d: string;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  group?: string;
  transform?: string;
  strokeLinecap?: React.SVGProps<SVGPathElement>["strokeLinecap"];
  strokeLinejoin?: React.SVGProps<SVGPathElement>["strokeLinejoin"];
  vectorEffect?: React.SVGProps<SVGPathElement>["vectorEffect"];
};

/** Explicit design fixture only. The outlined sample course labels and every
 * authored path/paint remain intact; learner graphs use PenKnowledgeGraph2D. */
export function PenGraphReference({ width = 893, height = 601 }: { width?: number; height?: number }) {
  const prefix = React.useId().replace(/:/g, "");
  const paths = PEN_NATIVE_GRAPH_REFERENCE.paths as readonly SourcePath[];
  const paint = (value?: string) => value?.replace(/url\(#([^)]+)\)/g, `url(#${prefix}-$1)`);
  const renderPath = (path: SourcePath) => <path key={path.sourcePath} data-source-path={path.sourcePath} data-source-node={path.sourceId}
    d={path.d} transform={path.transform} fill={paint(path.fill)} stroke={paint(path.stroke)} strokeWidth={path.strokeWidth}
    strokeLinecap={path.strokeLinecap} strokeLinejoin={path.strokeLinejoin} vectorEffect={path.vectorEffect} />;
  const children: React.ReactNode[] = [];
  for (let index = 0; index < paths.length; index++) {
    const path = paths[index];
    if (!path.group) {
      children.push(renderPath(path));
      continue;
    }
    const group = [renderPath(path)];
    while (paths[index + 1]?.group === path.group) group.push(renderPath(paths[++index]));
    children.push(<g key={`group-${path.group}`} filter={`url(#${prefix}-${path.group})`}>{group}</g>);
  }
  const filter = PEN_NATIVE_GRAPH_REFERENCE.filter;
  return <svg width={width} height={height} viewBox="0 0 893 601" fill="none" xmlns="http://www.w3.org/2000/svg"
    role="img" aria-label="Pen knowledge graph design reference" data-testid="pen-graph-reference" data-renderer-ready="true" data-source-sha256={PEN_NATIVE_GRAPH_REFERENCE.sha256}>
    {children}
    <defs>
      <filter id={`${prefix}-${filter.id}`} x={filter.x} y={filter.y} width={filter.width} height={filter.height} filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
        <feFlood floodOpacity="0" result="BackgroundImageFix" />
        <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha" />
        <feMorphology radius="6" operator="dilate" in="SourceAlpha" result="effect1_dropShadow_3457_3774" />
        <feOffset />
        <feComposite in2="hardAlpha" operator="out" />
        <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.01 0" />
        <feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow_3457_3774" />
        <feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow_3457_3774" result="shape" />
      </filter>
      {PEN_NATIVE_GRAPH_REFERENCE.gradients.map(gradient => <linearGradient key={gradient.id} id={`${prefix}-${gradient.id}`} x1={gradient.x1} y1={gradient.y1} x2={gradient.x2} y2={gradient.y2} gradientTransform={gradient.transform} gradientUnits="userSpaceOnUse">
        {gradient.stops.map((stop, index) => <stop key={index} offset={stop.offset} stopColor={stop.color} stopOpacity={stop.opacity} />)}
      </linearGradient>)}
    </defs>
  </svg>;
}
