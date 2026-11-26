#!/usr/bin/env node
// After the inline-style codemod, style constants that only fed `style={...}`
// are unused. Remove the ones the codemod orphaned (not ones that were
// already unused before), when the declaration is a pure const of literals.
//
//   tsc --noEmit --noUnusedLocals --pretty false | grep TS6133 > after.txt
//   node scripts/codemods/remove-unused-style-consts.mjs before.txt after.txt
import fs from "node:fs";
import { createRequire } from "node:module";
const ts = createRequire(import.meta.url)("typescript");

const parse = (f) => fs.readFileSync(f, "utf8").split("\n").map((l) => /^(.+?)\((\d+),(\d+)\): error TS6133: '(.+?)' is declared/.exec(l)).filter(Boolean).map((m) => ({ file: m[1], name: m[4] }));
const before = new Set(parse(process.argv[2]).map((x) => `${x.file}|${x.name}`));
const targets = parse(process.argv[3]).filter((x) => !before.has(`${x.file}|${x.name}`));
const byFile = new Map();
for (const t of targets) byFile.set(t.file, [...(byFile.get(t.file) ?? []), t.name]);

const pure = (e) => {
  while (ts.isAsExpression(e) || ts.isSatisfiesExpression(e) || ts.isParenthesizedExpression(e)) e = e.expression;
  if (ts.isStringLiteral(e) || ts.isNumericLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e) || ts.isIdentifier(e) || ts.isPropertyAccessExpression(e)) return true;
  if (ts.isPrefixUnaryExpression(e)) return pure(e.operand);
  if (ts.isTemplateExpression(e)) return e.templateSpans.every((s) => pure(s.expression));
  if (ts.isObjectLiteralExpression(e)) return e.properties.every((p) => (ts.isPropertyAssignment(p) && pure(p.initializer)) || (ts.isSpreadAssignment(p) && pure(p.expression)));
  if (ts.isArrayLiteralExpression(e)) return e.elements.every(pure);
  if (ts.isConditionalExpression(e)) return pure(e.condition) && pure(e.whenTrue) && pure(e.whenFalse);
  return false;
};

let removed = 0, kept = 0;
for (const [file, names] of byFile) {
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const edits = [];
  (function visit(n) {
    // an unused import of a style constant (or of CSSProperties)
    if (ts.isImportDeclaration(n) && n.importClause && !n.importClause.name && n.importClause.namedBindings && ts.isNamedImports(n.importClause.namedBindings)) {
      const els = n.importClause.namedBindings.elements;
      const drop = els.filter((e) => names.includes(e.name.text));
      if (drop.length) {
        removed += drop.length;
        if (drop.length === els.length) {
          edits.push({ start: n.getFullStart() + (text.slice(n.getFullStart(), n.getStart(sf)).match(/^\n*/)?.[0].length ?? 0), end: n.getEnd() + (text[n.getEnd()] === "\n" ? 1 : 0) });
        } else {
          const keep = els.filter((e) => !drop.includes(e)).map((e) => e.getText(sf));
          const nb = n.importClause.namedBindings;
          edits.push({ start: nb.getStart(sf), end: nb.getEnd(), text: `{ ${keep.join(", ")} }` });
        }
      }
      return;
    }
    if (ts.isVariableStatement(n) && n.declarationList.flags & ts.NodeFlags.Const && n.declarationList.declarations.length === 1) {
      const d = n.declarationList.declarations[0];
      if (ts.isIdentifier(d.name) && names.includes(d.name.text) && d.initializer && pure(d.initializer) && !n.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) {
        const full = n.getFullStart(), start = n.getStart(sf);
        const trivia = text.slice(full, start);
        const gap = trivia.lastIndexOf("\n\n");
        edits.push({ start: gap >= 0 ? full + gap + 1 : full, end: n.getEnd() });
        removed++;
        return;
      }
    }
    ts.forEachChild(n, visit);
  })(sf);
  kept += names.length - edits.length;
  let out = text;
  for (const e of edits.sort((a, b) => b.start - a.start)) out = out.slice(0, e.start) + (e.text ?? "") + out.slice(e.end);
  out = out.replace(/\n{3,}/g, "\n\n");
  fs.writeFileSync(file, out);
}
console.log(JSON.stringify({ removed, notRemoved: kept }));
