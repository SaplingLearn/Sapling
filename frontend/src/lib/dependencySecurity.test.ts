import { afterEach, describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import katex from 'katex';
import 'katex/contrib/mhchem';

const require = createRequire(import.meta.url);
const braces = require('braces') as {
  (pattern: string): string[];
  parse(pattern: string): object;
  compile(pattern: string | object): string;
  expand(pattern: string | object): string[];
  stringify(pattern: string | object): string;
};
const frontend = path.resolve(import.meta.dirname, '../..');
const temporary: string[] = [];
const temp = () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'sapling-dependency-security-'));
  temporary.push(directory);
  return directory;
};
afterEach(() => temporary.splice(0).forEach(directory => rmSync(directory, { recursive: true, force: true })));

describe('braces local mitigation for GHSA-vfj7-8cjw-p6xm', () => {
  it.each(['compile', 'expand', 'stringify', 'parse'] as const)('bounds deeply nested input before %s recursion', method => {
    const malicious = '{'.repeat(4000) + 'a,b' + '}'.repeat(4000);
    expect(() => braces[method](malicious)).toThrow('local structural depth limit');
    expect(() => braces[method]('('.repeat(4000) + 'a' + ')'.repeat(4000))).toThrow('local structural depth limit');
  });

  it.each(['compile', 'expand', 'stringify'] as const)('also protects direct %s AST entry points', method => {
    let deep: object = { type: 'text', value: 'x' };
    for (let i = 0; i < 5000; i++) deep = { type: 'root', nodes: [deep] };
    expect(() => braces[method](deep)).toThrow('local structural depth limit');
    const cyclic: { type: string; nodes: object[] } = { type: 'root', nodes: [] };
    cyclic.nodes.push(cyclic);
    expect(() => braces[method](cyclic)).toThrow('local structural depth limit');
    const parentCycle: { type: string; nodes: object[]; parent?: object } = { type: 'root', nodes: [] };
    parentCycle.parent = parentCycle;
    expect(() => braces[method](parentCycle)).toThrow('local structural depth limit');
    // Direct internal-module imports must not bypass the public-entry guard.
    const internal = require(`braces/lib/${method}`) as (value: object) => unknown;
    expect(() => internal(cyclic)).toThrow('local structural depth limit');
  });

  it('preserves normal nested brace/range, escaped and quoted patterns', () => {
    expect(braces.expand('packages/{app,web}/src/{one,two}.ts').sort()).toEqual([
      'packages/app/src/one.ts', 'packages/app/src/two.ts', 'packages/web/src/one.ts', 'packages/web/src/two.ts',
    ]);
    expect(braces.expand('unit-{1..3}')).toEqual(['unit-1', 'unit-2', 'unit-3']);
    expect(braces.compile('packages/{app,web}/src')).toBe('packages/(app|web)/src');
    expect(braces.stringify(braces.parse('a/{b,c}/d'))).toBe('a/{b,c}/d');
    expect(() => braces.compile('"' + '{'.repeat(500) + '"')).not.toThrow();
    expect(() => braces.compile('\\{'.repeat(500))).not.toThrow();
    expect(() => braces.compile('{'.repeat(127) + 'a,b' + '}'.repeat(127))).not.toThrow();
    expect(() => braces.parse('{'.repeat(128) + 'a,b' + '}'.repeat(128))).toThrow('local structural depth limit');
  });

  it('keeps Next workspace lint-root discovery working', () => {
    const directory = temp();
    mkdirSync(path.join(directory, 'app/src'), { recursive: true });
    mkdirSync(path.join(directory, 'web/src'), { recursive: true });
    writeFileSync(path.join(directory, 'file.txt'), 'not a workspace');
    const { getRootDirs } = require('@next/eslint-plugin-next/dist/utils/get-root-dirs') as {
      getRootDirs(context: { cwd: string; settings: { next?: { rootDir: string | string[] } } }): string[];
    };
    expect(getRootDirs({ cwd: directory, settings: {} })).toEqual([directory]);
    expect(getRootDirs({ cwd: directory, settings: { next: { rootDir: path.join(directory, '{app,web}') } } }).sort())
      .toEqual([path.join(directory, 'app'), path.join(directory, 'web')]);
  });

  it('verifies installed mitigation hashes and an idempotent install hook', () => {
    const result = spawnSync(process.execPath, ['scripts/apply-security-patches.mjs'], { cwd: frontend, encoding: 'utf8' });
    expect(result.status, result.stderr).toBe(0);
    const manifest = JSON.parse(readFileSync(path.join(frontend, 'patches/braces-3.0.3-depth-guard.json'), 'utf8')) as {
      files: { path: string; patched_sha256: string }[];
    };
    const installed = path.dirname(require.resolve('braces/package.json'));
    for (const file of manifest.files) {
      expect(createHash('sha256').update(readFileSync(path.join(installed, file.path))).digest('hex')).toBe(file.patched_sha256);
    }
  });

  it('fails installation on unexpected source without changing any target file', () => {
    const directory = temp();
    mkdirSync(path.join(directory, 'scripts'));
    mkdirSync(path.join(directory, 'patches'));
    mkdirSync(path.join(directory, 'node_modules/braces/lib'), { recursive: true });
    for (const file of ['scripts/apply-security-patches.mjs', 'patches/braces-3.0.3-depth-guard.json', 'patches/braces-depth-guard.js']) {
      writeFileSync(path.join(directory, file), readFileSync(path.join(frontend, file)));
    }
    writeFileSync(path.join(directory, 'package-lock.json'), JSON.stringify({
      packages: { 'node_modules/braces': { version: '3.0.3' } },
    }));
    writeFileSync(path.join(directory, 'node_modules/braces/package.json'), JSON.stringify({ name: 'braces', version: '3.0.3' }));
    const installed = path.dirname(require.resolve('braces/package.json'));
    for (const file of ['parse', 'compile', 'expand', 'stringify']) {
      writeFileSync(path.join(directory, `node_modules/braces/lib/${file}.js`), readFileSync(path.join(installed, `lib/${file}.js`)));
    }
    const target = path.join(directory, 'node_modules/braces/lib/compile.js');
    const unexpected = readFileSync(target, 'utf8') + '\n// unexpected upstream revision\n';
    writeFileSync(target, unexpected);
    const result = spawnSync(process.execPath, ['scripts/apply-security-patches.mjs'], { cwd: directory, encoding: 'utf8' });
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain('Unexpected braces source digest');
    expect(readFileSync(target, 'utf8')).toBe(unexpected);
    expect(existsSync(path.join(directory, 'node_modules/braces/lib/sapling-depth-guard.js'))).toBe(false);
  });
});

describe('glob patched library and CLI compatibility', () => {
  const minifierRequire = createRequire(require.resolve('@node-minify/core'));

  it('does not shell-evaluate metacharacters in matched filenames', () => {
    const directory = temp();
    const filename = '$(touch injected-marker).js';
    writeFileSync(path.join(directory, filename), 'const safe = true;');
    const packageFile = minifierRequire.resolve('glob/package.json');
    const pkg = JSON.parse(readFileSync(packageFile, 'utf8')) as { bin: string | { glob: string } };
    const bin = typeof pkg.bin === 'string' ? pkg.bin : pkg.bin.glob;
    const result = spawnSync(process.execPath, [path.resolve(path.dirname(packageFile), bin), '-c', 'echo', '*.js'], {
      cwd: directory, encoding: 'utf8', timeout: 5000,
    });
    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout.trim()).toBe(filename);
    expect(existsSync(path.join(directory, 'injected-marker'))).toBe(false);
  });

  it('minifies wildcard input through the real OpenNext minifier dependencies', async () => {
    const directory = temp();
    writeFileSync(path.join(directory, 'one.js'), 'globalThis.securityOne = 1 + 2;');
    writeFileSync(path.join(directory, 'two.js'), 'globalThis.securityTwo = 3 + 4;');
    mkdirSync(path.join(directory, 'out'));
    const minify = require('@node-minify/core') as (settings: object) => Promise<string>;
    const result = await minify({
      compressor: require('@node-minify/terser'),
      input: path.join(directory, '*.js'), output: path.join(directory, 'out/result.js'),
    });
    expect(result).toContain('securityOne=3');
    expect(result).toContain('securityTwo=7');
    expect(readFileSync(path.join(directory, 'out/result.js'), 'utf8')).toBe(result);
  });
});

describe('KaTeX prototype-pollution gadget removal', () => {
  it('does not inherit trust from renderer options', () => {
    const options = Object.assign(Object.create({ trust: true }), { throwOnError: false });
    const html = katex.renderToString(String.raw`\href{javascript:alert(1)}{click}`, options);
    expect(html).not.toMatch(/<a(?:\s|>)/);
    expect(html).not.toContain('href="javascript:');
  });

  it('does not inherit a polluted Object.prototype trust option', () => {
    const previous = Object.getOwnPropertyDescriptor(Object.prototype, 'trust');
    Object.defineProperty(Object.prototype, 'trust', { value: true, writable: true, configurable: true });
    try {
      const html = katex.renderToString(String.raw`\includegraphics{https://invalid.example/image.png}`, { throwOnError: false });
      expect(html).not.toContain('<img');
    } finally {
      if (previous) Object.defineProperty(Object.prototype, 'trust', previous);
      else Reflect.deleteProperty(Object.prototype, 'trust');
    }
  });

  it('preserves display math, macros, chemistry and matching prefixed CSS', () => {
    const html = katex.renderToString(String.raw`\R \quad \frac{1}{2} \quad \ce{H2O}`, {
      displayMode: true, macros: { '\\R': '\\mathbb{R}' },
    });
    expect(html).toContain('katex-display');
    expect(html).toContain('<math');
    expect(html).toContain('katex-base');
    expect(html).not.toContain('katex-error');
    const css = readFileSync(path.join(path.dirname(require.resolve('katex')), 'katex.min.css'), 'utf8');
    expect(css).toContain('.katex-base');
    for (const parent of ['mermaid', 'rehype-katex', 'micromark-extension-math']) {
      expect(createRequire(require.resolve(parent)).resolve('katex')).toBe(require.resolve('katex'));
    }
  });
});
