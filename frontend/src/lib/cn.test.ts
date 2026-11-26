import { describe, expect, it } from "vitest";
import { cn } from "./cn";

describe("cn", () => {
  it("keeps a font size and a text colour together", () => {
    expect(cn("text-md text-text-dim")).toBe("text-md text-text-dim");
    expect(cn("text-2xs", "text-err")).toBe("text-2xs text-err");
  });

  it("lets a later font size win", () => {
    expect(cn("text-md", "text-lg")).toBe("text-lg");
  });

  it("lets a later colour win", () => {
    expect(cn("text-text", "text-text-muted")).toBe("text-text-muted");
    expect(cn("bg-bg-panel", "bg-sap-50")).toBe("bg-sap-50");
  });

  it("keeps border width and border colour", () => {
    expect(cn("border border-border")).toBe("border border-border");
  });

  it("merges theme radii and shadows", () => {
    expect(cn("rounded-sm", "rounded-lg")).toBe("rounded-lg");
    expect(cn("shadow-sm", "shadow-md")).toBe("shadow-md");
  });

  it("keeps font family and weight", () => {
    expect(cn("font-display font-medium")).toBe("font-display font-medium");
  });

  it("drops falsy values", () => {
    expect(cn("p-2", false, null, undefined, 0 && "x", "m-1")).toBe("p-2 m-1");
  });
});

describe("cn and line height", () => {
  it("keeps a leading class before a font size", () => {
    expect(cn("leading-[1.6]", "text-md")).toBe("leading-[1.6] text-md");
  });
});
