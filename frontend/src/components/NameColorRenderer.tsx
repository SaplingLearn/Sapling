"use client";

import React from "react";
import type { Cosmetic } from "@/lib/types";

interface NameColorRendererProps {
  name: string;
  cosmetic?: Cosmetic | null;
  className?: string;
  style?: React.CSSProperties;
  as?: keyof React.JSX.IntrinsicElements;
}

export function NameColorRenderer({ name, cosmetic, className, style, as = "span" }: NameColorRendererProps) {
  const Tag = as as React.ElementType;
  const css = cosmetic?.css_value;

  if (!css) {
    return (
      <Tag className={className} style={style}>
        {name}
      </Tag>
    );
  }

  // Gradient-clipped headings are on the brand's explicit anti-reference
  // list (bg-clip-text is a 2024 AI-SaaS tell). If a legacy cosmetic still
  // stores a gradient CSS value, fall back to the first color stop so the
  // name renders as a solid hue rather than a gradient-text heading.
  const isGradient = /gradient\(/i.test(css);
  const color = isGradient ? extractFirstColor(css) : css;
  const applied: React.CSSProperties = { color };

  return (
    <Tag className={className} style={{ ...applied, ...style }}>
      {name}
    </Tag>
  );
}

// Best-effort: pull the first hex or rgb(a) token from a gradient string.
function extractFirstColor(css: string): string {
  const hex = css.match(/#(?:[0-9a-f]{3}){1,2}/i);
  if (hex) return hex[0];
  const rgb = css.match(/rgba?\([^)]+\)/i);
  if (rgb) return rgb[0];
  return "currentColor";
}
