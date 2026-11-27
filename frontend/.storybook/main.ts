import type { StorybookConfig } from "@storybook/nextjs-vite";

// The component catalog (docs/decisions/0031). Stories sit next to their
// component in src/components/ui; `npm run storybook` serves them and
// `npm run build-storybook` writes the static site deployed to
// ui.saplinglearn.com and read by scripts/design-system/export.mjs.
const config: StorybookConfig = {
  stories: ["../src/components/**/*.stories.tsx"],
  addons: ["@storybook/addon-a11y"],
  framework: { name: "@storybook/nextjs-vite", options: {} },
  staticDirs: ["../public"],
  core: { disableTelemetry: true },
};

export default config;
