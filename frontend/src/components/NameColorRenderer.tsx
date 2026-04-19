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

  const isGradient = /gradient\(/i.test(css);
  const applied: React.CSSProperties = isGradient
    ? {
        backgroundImage: css,
        WebkitBackgroundClip: "text",
        backgroundClip: "text",
        color: "transparent",
        WebkitTextFillColor: "transparent",
      }
    : { color: css };

  return (
    <Tag className={className} style={{ ...applied, ...style }}>
      {name}
    </Tag>
  );
}
