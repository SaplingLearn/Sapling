import React from "react";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Icon } from "./Icon";
import { NAV_SECTIONS } from "@/lib/navFeatures";

const featureIcons = {
  "/dashboard": "home",
  "/learn": "clover",
  "/tree": "trees",
  "/study": "study",
  "/library": "library",
  "/calendar": "calendar",
  "/social": "social",
  "/achievements": "achievements",
};

describe("supplied feature icons", () => {
  for (const [route, icon] of Object.entries(featureIcons)) {
    it(`uses icon-${icon}.svg for ${route}`, () => {
      const item = NAV_SECTIONS.flatMap(section => section.items).find(item => item.href === route);
      expect(item?.icon).toBe(icon);
    });
  }

  for (const icon of [...Object.values(featureIcons), "setting", "error", "upload"]) {
    it(`preserves the original geometry and bounds of icon-${icon}.svg`, () => {
      const source = readFileSync(new URL(`../../public/design/sapling/originals/icon-${icon}.svg`, import.meta.url), "utf8");
      const rendered = renderToStaticMarkup(<Icon name={icon} />);
      expect(rendered.match(/viewBox="([^"]+)"/)?.[1]).toBe(source.match(/viewBox="([^"]+)"/)?.[1]);
      const paths = (svg: string) => [...svg.matchAll(/\bd="([^"]+)"/g)].map(match => match[1]);
      expect(paths(rendered)).toEqual(paths(source));
    });
  }
});
