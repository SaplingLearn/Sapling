// src/styles/tokens.css + theme.css → the Design System artifact's
// tokens.json (lists of {name, value, usage}) and its compiled tokens.css.
// Values are copied exactly; a colour that points at another colour becomes
// an alias ("{sap-50}"). What the format can't hold is returned as `skipped`.

// Where a declaration has no comment of its own, say where it is used.
const USAGE = {
  bg: "Page background.",
  "bg-panel": "Raised surfaces: cards, panels, dialogs, menus.",
  "bg-subtle": "Quiet fills, hover rows, inactive pills.",
  "bg-soft": "Stronger quiet fill: pressed states, tracks.",
  "bg-input": "Text fields and selects.",
  "bg-inset": "Inset wells inside a panel.",
  "bg-topbar": "The top bar.",
  border: "Hairlines and the edge of every raised surface.",
  "border-strong": "Edges a control needs to show (unselected options, outlines).",
  text: "Body text and headings on bg, bg-panel and bg-subtle.",
  "text-dim": "Secondary text on bg, bg-panel and bg-subtle.",
  "accent-fg": "Text and icons on accent and brand-forest fills.",
  "accent-soft": "Background of a selected or highlighted row.",
  "accent-border": "Border of a selected or highlighted row.",
  warn: "Warnings: text, icons and borders.",
  "warn-soft": "Warning chip and banner background.",
  err: "Errors and destructive actions: text, icons and borders.",
  "err-soft": "Error chip and banner background.",
  info: "Neutral news: text, icons and borders.",
  "info-soft": "Info chip and banner background.",
  "state-mastery": "Mastered concept (graph dots, legends).",
  "state-progress": "Concept in progress.",
  "state-struggle": "Concept the student is struggling with.",
  "state-neutral": "Concept not started.",
  "c-ink": "Category hue for neutral, uncoloured items.",
  "r-full": "Pills and circles.",
  "row-h": "Height of a list row (compact density).",
  "brand-forest": "The brand green: the primary action's fill and brand moments. 7.4:1 under white text.",
  "brand-forest-hover": "Hover state of brand-forest fills.",
  "brand-forest-bright": "The brighter green: highlight and CTA fills, the accent role. 5.2:1 under white text.",
  "brand-forest-bright-hover": "Hover state of brand-forest-bright fills.",
  accent: "Highlight and focus role: focus rings, selected states, active indicators.",
  "text-muted": "Hints, placeholders and micro labels on bg, bg-panel and bg-inset (4.5:1).",
  positive: "Positive status: mastered, correct, grade A.",
  "alert-warn": "Dashboard alert dot: streak shield.",
  "alert-err": "Dashboard alert dot: notification.",
  "fallback-muted": "Placeholder colour for a course with no colour yet.",
  "sidenav-bg": "The side navigation rail's fill. White text on it is 4.23:1, under AA for small text: keep rail labels large or bold.",
};
const RAMP = {
  sap: (n) => `Brand green ramp, ${n} (50 lightest, 900 darkest): tints and soft fills in the brand-forest family.`,
  ink: (n) => `Warm neutral ramp, ${n} (0 lightest, 900 darkest): the app's paper and ink.`,
  moss: (n) => `Public pages' cool neutral, ${n}.`,
  leaf: (n) => `Public pages' green, ${n}.`,
  paper: (n) => `Public pages' paper, ${n}.`,
  c: (n) => `Category hue (${n}): course and tag colours.`,
  grade: (n) => `Grade band ${n.toUpperCase()}.`,
  "fs": (n) => `Type size ${n}.`,
};

const FS_USAGE = {
  "fs-2xs": "Micro labels and counts.",
  "fs-xs": "Badges, eyebrows, small labels.",
  "fs-sm": "Chrome: buttons, chips, captions.",
  "fs-md": "Body text, the most used size.",
  "fs-base": "Default page text; larger body copy.",
  "fs-lg": "Lead paragraphs and small headings.",
  "fs-xl": "Section headings.",
  "fs-2xl": "Card and panel headings.",
  "fs-3xl": "Page headings.",
  "fs-4xl": "Screen title (the top bar).",
  "fs-5xl": "Display numerals.",
};

const isColor = (v) => /^#[0-9a-f]{3,8}$/i.test(v) || /^(rgb|rgba|hsl|hsla|oklch)\([\d\s.,%/]+\)$/i.test(v);
const clean = (c) => c.replace(/\s+/g, " ").replace(/\s*\*\s*/g, " ").trim();
const firstSentence = (c) => {
  const s = clean(c).replace(/^Canonical /, "").split(/(?<=\.)\s/)[0];
  return s.length > 300 ? s.slice(0, 297) + "..." : s;
};

/** Declarations in the first `selector { … }` block, with the comment before or after each. */
function declarations(css, selector) {
  const start = css.indexOf(selector);
  if (start < 0) return [];
  const open = css.indexOf("{", start);
  const close = css.indexOf("\n}", open);
  const body = css.slice(open + 1, close);
  const decls = [];
  let pending = "";
  const re = /\/\*([\s\S]*?)\*\/|--([a-z0-9-]+)\s*:\s*([^;]+);([ \t]*\/\*([\s\S]*?)\*\/)?/gi;
  let m;
  while ((m = re.exec(body))) {
    if (m[1] !== undefined) {
      pending = m[1];
      continue;
    }
    decls.push({ name: m[2], value: m[3].trim(), comment: m[5] ?? pending });
    pending = "";
  }
  return decls;
}

const PAD_ROLE = {
  "pad-sm": "Small padding: chips, tight rows.",
  "pad-md": "Default padding: cards, panels.",
  "pad-lg": "Large padding: dialogs, sections.",
  "pad-xl": "Extra-large padding: page gutters, hero blocks.",
};

function usageFor(d) {
  if (USAGE[d.name]) return USAGE[d.name];
  const ramp = /^(sap|ink|moss|leaf|paper|c|grade|fs)-(.+)$/.exec(d.name);
  const fromComment = d.comment && clean(d.comment) && clean(d.comment).length < 400 ? firstSentence(d.comment) : "";
  if (!ramp || !RAMP[ramp[1]]) return fromComment;
  const base = RAMP[ramp[1]](ramp[2]);
  return fromComment && ramp[1] !== "fs" ? `${base} ${fromComment}` : base;
}

/** Sort :root declarations into the format's families; what fits none is skipped. */
function sortDeclarations(root, { compact, spacious }) {
  const colorNames = new Set(root.filter((d) => isColor(d.value)).map((d) => d.name));
  const out = {
    color: [],
    radius: [],
    spacing: [{ name: "spacing", value: "4px", usage: "The spacing step: every padding, gap and margin is a multiple (Tailwind p-3 = 12px)." }],
    sizes: [],
    skipped: [],
  };
  for (const d of root) {
    const alias = /^var\(--([a-z0-9-]+)\)$/.exec(d.value);
    if (isColor(d.value)) {
      out.color.push({ name: d.name, value: d.value.toLowerCase(), usage: usageFor(d) });
    } else if (alias && colorNames.has(alias[1])) {
      colorNames.add(d.name);
      out.color.push({ name: d.name, value: `{${alias[1]}}`, usage: usageFor(d) });
    } else if (/^r-/.test(d.name)) {
      out.radius.push({ name: d.name, value: d.value, usage: usageFor(d) });
    } else if (/^(pad-|row-h)/.test(d.name)) {
      const role = PAD_ROLE[d.name] ?? USAGE[d.name] ?? "";
      const usage = `${role} Compact density, the app default (regular ${d.value}, spacious ${spacious[d.name] ?? d.value}).`.trim();
      out.spacing.push({ name: d.name, value: compact[d.name] ?? d.value, usage });
    } else if (/^fs-/.test(d.name)) {
      out.sizes.push(d);
    } else {
      const why = /^(dur|ease)/.test(d.name) ? "motion" : /^font-|medium-stroke/.test(d.name) ? "font plumbing (see Type)" : "not a token this format holds";
      out.skipped.push({ name: d.name, why });
    }
  }
  for (const c of out.color) {
    const a = /^\{(.+)\}$/.exec(c.value);
    if (a && !out.color.some((x) => x.name === a[1])) throw new Error(`alias of a missing colour: ${c.name} -> ${a[1]}`);
  }
  return out;
}

export function parseTokens({ tokensCss, themeCss, title }) {
  const root = declarations(tokensCss, ":root {");
  const density = (sel) => {
    const m = new RegExp(sel.replace(/[[\]"]/g, "\\$&") + "\\s*\\{([^}]*)\\}").exec(tokensCss);
    return Object.fromEntries([...(m?.[1] ?? "").matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map((x) => [x[1], x[2].trim()]));
  };
  const compact = density('html[data-density="compact"]');
  const spacious = density('html[data-density="spacious"]');
  // The density block is one line of declarations; declarations() reads it too.
  const theme = declarations(themeCss, "@theme static {").concat(declarations(themeCss, "@theme {"));
  const { color, radius, spacing, sizes, skipped } = sortDeclarations(root, { compact, spacious });

  const themeVar = (name) => theme.find((d) => d.name === name)?.value;
  const stack = (v) =>
    [...new Set(
      v
        .replace(/var\(--font-(gummi|aleo)\)/g, "'Aleo'")
        .replace(/var\(--font-suse\)/g, "'SUSE'")
        .split(",")
        .map((s) => s.trim().replace(/"/g, "'")),
    )].join(", ");
  const families = {
    sans: stack(themeVar("font-sans")),
    serif: stack(themeVar("font-serif")),
    display: stack(themeVar("font-display")),
    code: stack(themeVar("font-code")),
  };
  const shadow = theme
    .filter((d) => d.name.startsWith("shadow-"))
    .map((d) => ({
      name: d.name,
      value: d.value,
      usage: { "shadow-sm": "Resting cards.", "shadow-md": "Hover and popovers.", "shadow-lg": "Dialogs, sheets and menus.", "shadow-inset": "Pressed and inset wells." }[d.name] ?? "",
    }));

  const px = (d) => parseInt(d.value, 10);
  const style = (d, family, lineHeight, weight) => ({
    name: d.name,
    fontSize: d.value,
    lineHeight,
    fontWeight: weight,
    ...(family ? { family } : {}),
    usage: FS_USAGE[d.name] ?? "",
  });
  const type = {
    fonts: [
      { family: "SUSE", file: "fonts/SUSE-variable.woff2", weight: "100 900", style: "normal" },
      { family: "Aleo", file: "fonts/Aleo-variable.woff2", weight: "100 900", style: "normal" },
      { family: "Aleo", file: "fonts/Aleo-variable-italic.woff2", weight: "100 900", style: "italic" },
    ],
    families,
    groups: [
      { name: "UI", family: "sans", styles: sizes.filter((d) => px(d) <= 16).map((d) => style(d, null, d.name === "fs-md" || px(d) >= 13 ? 1.5 : 1.3, px(d) <= 11 ? 600 : 400)) },
      { name: "Headings", family: "display", styles: sizes.filter((d) => px(d) > 16).map((d) => style(d, null, 1.15, 500)) },
    ],
  };

  const tokens = {
    name: title,
    version: 1,
    color: { themes: [{ id: "light", name: "Light" }], tokens: color },
    type,
    spacing: { tokens: spacing },
    radius: { tokens: radius },
    shadow: { tokens: shadow },
  };

  // tokens.css, laid out as the format compiles it.
  const v = (val) => val.replace(/^\{(.+)\}$/, "var(--$1)");
  const lines = [`/* ${title} — generated from tokens.json */`];
  lines.push(`:root, [data-theme="light"] {`);
  for (const t of color) lines.push(`  --${t.name}: ${v(t.value)};`);
  for (const t of shadow) lines.push(`  --${t.name}: ${t.value};`);
  lines.push("}");
  lines.push(":root {");
  for (const t of spacing) lines.push(`  --${t.name}: ${t.value};`);
  for (const t of radius) lines.push(`  --${t.name}: ${t.value};`);
  for (const [k, s] of Object.entries(families)) lines.push(`  --font-${k}: ${s};`);
  lines.push("}");
  for (const g of type.groups)
    for (const s of g.styles)
      lines.push(`.${s.name} { font-family: var(--font-${s.family ?? g.family}); font-size: ${s.fontSize}; line-height: ${s.lineHeight}; font-weight: ${s.fontWeight}; }`);
  for (const f of type.fonts)
    lines.push(`@font-face { font-family: "${f.family}"; src: url("${f.file}") format("woff2"); font-weight: ${f.weight}; font-style: ${f.style}; font-display: swap; }`);

  return { tokens, tokensCss: lines.join("\n") + "\n", skipped };
}
