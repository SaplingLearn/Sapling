/**
 * globals.css has to survive the CSS parser.
 *
 * Nothing in the fast lane reads this file as CSS: eslint lints JS/TS, tsc
 * checks types, and vitest never imports the stylesheet. The first thing that
 * actually parses it is the Next production build — so a broken comment or an
 * unbalanced brace sails through `lint + tsc + vitest`, goes green in CI, and
 * only surfaces when the e2e stack tries to build the frontend.
 *
 * That happened while writing #288: an edit closed a block comment early,
 * leaving the rest of it as raw stylesheet text. postcss reported it 780 lines
 * later ("Unclosed string" at the next quote it met), which is a long way from
 * the actual mistake.
 *
 * This is a hand-rolled scan rather than a postcss import on purpose: postcss
 * is only a TRANSITIVE dependency here (`@tailwindcss/postcss` is the direct
 * one), and the installed version already drifts from CI's. A dependency-free
 * check can't develop that skew.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect } from 'vitest';

const CSS_PATH = path.resolve(__dirname, 'globals.css');

/**
 * Walk the stylesheet the way a tokenizer does — tracking comments, strings
 * and brace depth — and collect every structural problem with its line.
 */
function structuralProblems(css: string): string[] {
  const problems: string[] = [];
  let i = 0;
  let line = 1;
  let depth = 0;

  while (i < css.length) {
    const c = css[i];

    if (c === '\n') { line++; i++; continue; }

    // Block comment: skip to its terminator.
    if (c === '/' && css[i + 1] === '*') {
      const openedAt = line;
      const end = css.indexOf('*/', i + 2);
      if (end === -1) {
        problems.push(`unterminated block comment opened at line ${openedAt}`);
        break;
      }
      for (let k = i; k < end; k++) if (css[k] === '\n') line++;
      i = end + 2;
      continue;
    }

    // A comment terminator outside a comment means an earlier one closed
    // early — the exact mistake this file exists to catch.
    if (c === '*' && css[i + 1] === '/') {
      problems.push(`stray "*/" at line ${line} (a block comment closed early above)`);
      i += 2;
      continue;
    }

    // Strings: CSS strings do not span raw newlines.
    if (c === '"' || c === "'") {
      const quote = c;
      let k = i + 1;
      while (k < css.length && css[k] !== quote && css[k] !== '\n') {
        if (css[k] === '\\') k++;
        k++;
      }
      if (css[k] !== quote) {
        problems.push(`unclosed ${quote === '"' ? 'double' : 'single'}-quoted string at line ${line}`);
        break;
      }
      i = k + 1;
      continue;
    }

    if (c === '{') depth++;
    if (c === '}') {
      depth--;
      if (depth < 0) {
        problems.push(`unbalanced "}" at line ${line}`);
        depth = 0;
      }
    }
    i++;
  }

  if (depth !== 0) problems.push(`${depth} unclosed block(s) at end of file`);
  return problems;
}

describe('globals.css', () => {
  it('is structurally parseable', () => {
    const css = fs.readFileSync(CSS_PATH, 'utf8');
    expect(structuralProblems(css)).toEqual([]);
  });

  it('detects the failure modes it is meant to catch', () => {
    // Guard the guard: a scan that silently returns [] for broken input would
    // be worse than no scan at all.
    expect(structuralProblems('/* opened but never closed\n.a { color: red; }')).toHaveLength(1);
    expect(structuralProblems('/* closed early */ stray text */\n.a { color: red; }')[0]).toMatch(/stray/);
    expect(structuralProblems('.a { content: "oops;\n}')[0]).toMatch(/unclosed/);
    expect(structuralProblems('.a { color: red;')[0]).toMatch(/unclosed block/);
    expect(structuralProblems('.a { color: red; } }')[0]).toMatch(/unbalanced/);
    // And it must stay quiet on legitimate CSS, including quotes and
    // apostrophes inside comments.
    expect(structuralProblems('/* it\'s fine "really" */\n.a::before { content: ""; }')).toEqual([]);
  });
});
