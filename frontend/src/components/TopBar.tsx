import React from "react";
import { cn } from "@/lib/cn";

export function TopBar({
  title,
  subtitle,
  actions,
  breadcrumb,
}: {
  // Title is optional now — the Dashboard uses a centered hero block
  // below the TopBar for its greeting, so the bar itself just shows
  // the breadcrumb + actions.
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  const hasTitle = title !== undefined && title !== null && title !== "";
  return (
    <header
      className={cn("flex items-end justify-between border-b border-b-border bg-bg sticky top-0 z-5", hasTitle ? "pt-5.5 px-8 pb-4" : "py-4 px-8")}
    >
      <div>
        {breadcrumb && <div className={cn("label-micro", hasTitle ? "mb-1" : "mb-0")}>{breadcrumb}</div>}
        {hasTitle && (
          <h1 className="h-serif m-0 text-4xl font-medium">{title}</h1>
        )}
        {subtitle && <div className="text-text-dim mt-1 text-md">{subtitle}</div>}
      </div>
      <div className="flex gap-2 items-center justify-end flex-wrap">{actions}</div>
    </header>
  );
}
