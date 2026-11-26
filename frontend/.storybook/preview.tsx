import type { Preview } from "@storybook/nextjs-vite";
import React from "react";
import { fontVariables } from "../src/app/fonts";
import { GUMMI_BOOT_SCRIPT } from "../src/lib/licensedFonts";
import "../src/app/globals.css";

// Same <html> setup as app/layout.tsx: the font variables and the default
// density. Gummi switches on only where the licence allows (licensedFonts.ts);
// elsewhere the heading face stays on Aleo, as it does in the app.
if (typeof document !== "undefined") {
  const html = document.documentElement;
  html.classList.add(...fontVariables.split(" "));
  html.dataset.accent = "sage";
  html.dataset.density = html.dataset.density || "compact";
  if (!document.getElementById("gummi-boot")) {
    const s = document.createElement("script");
    s.id = "gummi-boot";
    s.textContent = GUMMI_BOOT_SCRIPT;
    document.head.appendChild(s);
  }
}

const preview: Preview = {
  parameters: {
    layout: "centered",
    controls: { expanded: true },
    a11y: { test: "error" },
    backgrounds: { disable: true },
  },
  globalTypes: {
    density: {
      description: "Spacing density",
      toolbar: { title: "Density", items: ["compact", "spacious"], dynamicTitle: true },
    },
  },
  initialGlobals: { density: "compact" },
  decorators: [
    (Story, ctx) => {
      if (typeof document !== "undefined") document.documentElement.dataset.density = String(ctx.globals.density ?? "compact");
      return (
        <div className="bg-bg text-text font-sans p-6">
          <Story />
        </div>
      );
    },
  ],
};

export default preview;
