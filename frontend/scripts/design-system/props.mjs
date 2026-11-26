// A component file's props as a markdown table, read from its TypeScript
// types with react-docgen-typescript (the parser Storybook's docs use).
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const docgen = require("react-docgen-typescript");

const parser = docgen.withCustomConfig(path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../tsconfig.json"), {
  savePropValueAsString: true,
  shouldExtractLiteralValuesFromEnum: true,
  shouldRemoveUndefinedFromOptional: true,
  // Only the component's own props, not every DOM attribute it passes on.
  propFilter: (prop) => !prop.parent || !/node_modules/.test(prop.parent.fileName),
});

const typeOf = (t) => (t.name === "enum" && Array.isArray(t.value) ? t.value.map((v) => v.value).join(" | ") : t.raw ?? t.name);
const cell = (s) => String(s ?? "").replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();

export function propsTable(file) {
  const docs = parser.parse(file);
  const parts = [];
  for (const doc of docs) {
    const props = Object.values(doc.props);
    if (!props.length) continue;
    const rows = props
      .sort((a, b) => Number(b.required) - Number(a.required) || a.name.localeCompare(b.name))
      .map((p) => `| \`${p.name}\`${p.required ? "" : "?"} | \`${cell(typeOf(p.type))}\` | ${p.defaultValue ? `\`${cell(p.defaultValue.value)}\`` : ""} | ${cell(p.description)} |`);
    parts.push(
      (docs.length > 1 ? `### ${doc.displayName}\n\n` : "") +
        "| Prop | Type | Default | Notes |\n| --- | --- | --- | --- |\n" +
        rows.join("\n") +
        "\n",
    );
  }
  return parts.join("\n");
}
