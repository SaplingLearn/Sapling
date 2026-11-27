// Build Tailwind CSS for a fixed list of class candidates.
// usage: node scripts/codemods/twbuild.mjs <css entry> <candidates.json|-> <out.css>
import { compile } from "@tailwindcss/node";
import fs from "node:fs";
import path from "node:path";

const [entry, candFile, out] = process.argv.slice(2);
const css = fs.readFileSync(entry, "utf8");
const compiler = await compile(css, { base: path.dirname(path.resolve(entry)), onDependency() {} });
const cands = candFile && candFile !== "-" ? JSON.parse(fs.readFileSync(candFile, "utf8")) : [];
fs.writeFileSync(out, compiler.build(cands));
