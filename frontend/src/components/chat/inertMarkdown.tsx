"use client";

import React from "react";
import type { Components } from "react-markdown";
import styles from "./inertMarkdown.module.css";

/**
 * Which markdown a message may use (Z08).
 *
 * "rich" — every host but one: the tutor's own writing, with live links,
 * embedded GeoGebra materials, drawn diagrams and the app's own images.
 *
 * "inert" — text that may repeat class material verbatim. The learning loop
 * serves a check item's pose, an H2 hint (a classmate's shared passage), an
 * H4 worked sibling and an H6 or template reference from code, with no model
 * between the upload and the page, so the model-side link rule
 * (services/prompt_safety.py's INJECTION_GUARD_PROMPT) never sees them. Such
 * text is drawn as text: a link shows where it points and is never followed,
 * no image is fetched, nothing is embedded, no directive runs and no diagram
 * is drawn. Math, code, lists and emphasis still render.
 */
export type MarkdownProfile = "rich" | "inert";

/** The host an http(s) URL points at, or null for anything else. */
export function httpHost(href: string | undefined | null): string | null {
  try {
    const url = new URL(href ?? "");
    return url.protocol === "http:" || url.protocol === "https:" ? url.host : null;
  } catch {
    return null;
  }
}

/** The text a React node shows. */
function textOf(node: React.ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (React.isValidElement(node)) return textOf((node.props as { children?: React.ReactNode }).children);
  return "";
}

/** A link as text: its words, then the host it points at unless they already
 *  show it (a bare URL does) — never an anchor. */
function InertLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  const host = httpHost(href);
  const named = host !== null && textOf(children).toLowerCase().includes(host.toLowerCase());
  return (
    <span>
      {children}
      {host !== null && !named ? ` (${host})` : null}
    </span>
  );
}

/** An image as its label: nothing is fetched, and nothing links out. */
function InertImage({ alt }: { alt?: string }) {
  return <span>{alt ? `[image: ${alt}]` : "[image]"}</span>;
}

/** A ```mermaid or ```plot fence as the code it is: a drawn diagram can fetch
 *  what its text names. */
function FenceAsCode({ "data-content": code }: { "data-content"?: string }) {
  return (
    <pre className={`mono ${styles.fence}`}>
      <code>{code ?? ""}</code>
    </pre>
  );
}

/** The element overrides of the "inert" profile (MarkdownChat applies them
 *  last, so no caller can switch a link back on). */
export const INERT_COMPONENTS = {
  a: InertLink,
  img: InertImage,
  iframe: () => null,
  // MarkdownChat's names for the elements it turns those fences into
  "sap-mermaid": FenceAsCode,
  "sap-plot": FenceAsCode,
} as unknown as Components;
