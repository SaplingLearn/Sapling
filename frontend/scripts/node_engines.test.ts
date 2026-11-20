// The Node version the frontend declares (package.json `engines.node`) is one
// the locked tree can actually be installed on.
//
// `.npmrc` sets `engine-strict=true`, so `npm ci` refuses (EBADENGINE) any
// installed package whose own `engines.node` the running Node does not meet.
// A declared floor below a dependency's is therefore a promise the install
// cannot keep: katex 0.18.11's commander 15 asks for Node 22.12, while
// package.json still said 20.9 (#866 Z56). This test reads the lock and fails
// when a dependency raises the floor past the one package.json declares, and
// pins patches/README.md to the KaTeX version and floor the lock resolves.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const readJson = (name: string) => JSON.parse(fs.readFileSync(path.join(FRONTEND, name), "utf8"));

type Version = [number, number, number];
type Bound = { v: Version; inclusive: boolean };
type Interval = { lo?: Bound; hi?: Bound };

const cmp = (a: Version, b: Version) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

/** "22", "22.13", "22.x", "v22.13.0" → its parts; a wildcard part is null. */
function partial(text: string): (number | null)[] {
  const parts = text.replace(/^v/, "").split(".");
  if (!/^\d+$/.test(parts[0])) throw new Error(`unparsed version "${text}"`);
  return [0, 1, 2].map(i => (parts[i] === undefined || /^[x*]$/i.test(parts[i]) ? null : Number(parts[i])));
}

/** The first version past every one a partial names ("22" → 23.0.0, "22.13" → 22.14.0). */
function next(p: (number | null)[]): Version {
  if (p[1] === null) return [Number(p[0]) + 1, 0, 0];
  if (p[2] === null) return [Number(p[0]), Number(p[1]) + 1, 0];
  return [Number(p[0]), Number(p[1]), Number(p[2]) + 1];
}

const low = (p: (number | null)[]): Version => [Number(p[0]), p[1] ?? 0, p[2] ?? 0];

/** One comparator as an interval (the subset of node-semver npm's lock carries). */
function comparator(text: string): Interval {
  const m = /^(>=|<=|>|<|=|\^|~)?(.+)$/.exec(text);
  if (!m) throw new Error(`unparsed comparator "${text}"`);
  const [, op = "", ver] = m;
  const p = partial(ver);
  const at = (v: Version, inclusive: boolean): Bound => ({ v, inclusive });
  switch (op) {
    case ">=": return { lo: at(low(p), true) };
    case ">": return p[2] === null ? { lo: at(next(p), true) } : { lo: at(low(p), false) };
    case "<": return { hi: at(low(p), false) };
    case "<=": return p[2] === null ? { hi: at(next(p), false) } : { hi: at(low(p), true) };
    case "~": return { lo: at(low(p), true), hi: at(next([p[0], p[1], null]), false) };
    case "^": {
      const [major, minor] = [Number(p[0]), p[1]];
      const hi: Version = major > 0 || minor === null ? [major + 1, 0, 0]
        : minor > 0 || p[2] === null ? [0, minor + 1, 0] : [0, 0, Number(p[2]) + 1];
      return { lo: at(low(p), true), hi: at(hi, false) };
    }
    default:
      return p[2] === null ? { lo: at(low(p), true), hi: at(next(p), false) } : { lo: at(low(p), true), hi: at(low(p), true) };
  }
}

const inside = (v: Version, i: Interval) =>
  (!i.lo || (i.lo.inclusive ? cmp(v, i.lo.v) >= 0 : cmp(v, i.lo.v) > 0))
  && (!i.hi || (i.hi.inclusive ? cmp(v, i.hi.v) <= 0 : cmp(v, i.hi.v) < 0));

/** Whether `version` satisfies an npm `engines.node` range. */
export function satisfies(version: Version, range: string): boolean {
  return range.split("||").some(alternative => {
    // "> = 10" style spacing: an operator binds to the version after it.
    const set = alternative.trim().replace(/(>=|<=|>|<|=|\^|~)\s+/g, "$1");
    if (set === "" || set === "*") return true;
    return set.split(/\s+/).every(c => inside(version, comparator(c)));
  });
}

/** The floor a `>=X.Y.Z` declaration names. */
function declaredFloor(range: string): Version {
  const m = /^>=\s*(\d+)\.(\d+)\.(\d+)$/.exec(range.trim());
  if (!m) throw new Error(`package.json engines.node must be ">=X.Y.Z", got "${range}"`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

describe("satisfies (the range subset the lock uses)", () => {
  it.each([
    [[22, 13, 0], ">=22.12.0", true],
    [[20, 9, 0], ">=22.12.0", false],
    [[22, 13, 0], "^20.19.0 || ^22.13.0 || >=24.0.0", true],
    [[22, 12, 0], "^20.19.0 || ^22.13.0 || >=24.0.0", false],
    [[22, 13, 0], "6.* || 8.* || >= 10.*", true],
    [[22, 13, 0], ">=16 || 14 >=14.17", true],
    [[22, 13, 0], "^20.9.0", false],
    [[22, 13, 0], "*", true],
    [[22, 13, 0], ">=v12.22.7", true],
  ] as [Version, string, boolean][])("%j in %s → %s", (version, range, expected) => {
    expect(satisfies(version, range)).toBe(expected);
  });
});

describe("the declared Node floor", () => {
  const pkg = readJson("package.json");
  const lock = readJson("package-lock.json");
  const floor = declaredFloor(pkg.engines.node);

  it("is what the lock records for the root package", () => {
    expect(lock.packages[""].engines.node).toBe(pkg.engines.node);
  });

  it("meets every installed package's own engines.node", () => {
    // An optional package (a platform binary) that does not match is skipped
    // by npm rather than refused, so only the packages npm must install count.
    const refused = Object.entries(lock.packages as Record<string, {
      engines?: { node?: string } | string[]; optional?: boolean; version?: string;
    }>)
      .filter(([key, entry]) => key !== "" && !entry.optional)
      .flatMap(([key, entry]) => {
        const range = Array.isArray(entry.engines) ? undefined : entry.engines?.node;
        return range && !satisfies(floor, range) ? [`${key}@${entry.version}: engines.node "${range}"`] : [];
      });
    expect(refused, `package.json engines.node "${pkg.engines.node}" is below what these need`).toEqual([]);
  });
});

describe("patches/README.md", () => {
  const readme = fs.readFileSync(path.join(FRONTEND, "patches", "README.md"), "utf8");
  const lock = readJson("package-lock.json");
  const pkg = readJson("package.json");

  it("names the KaTeX version every consumer resolves to", () => {
    const resolved = Object.entries(lock.packages as Record<string, { version?: string }>)
      .filter(([key]) => key === "node_modules/katex" || key.endsWith("/node_modules/katex"))
      .map(([, entry]) => entry.version);
    expect(new Set(resolved)).toEqual(new Set([lock.packages["node_modules/katex"].version]));
    expect(readme).toContain(`\`${lock.packages["node_modules/katex"].version}\``);
    // No pin to a version the lock does not hold.
    for (const named of readme.matchAll(/KaTeX is pinned to (\S+?)[:.]/g)) {
      expect(named[1]).toBe(lock.packages["node_modules/katex"].version);
    }
  });

  it("states the Node floor package.json declares", () => {
    expect(readme).toContain(`\`node ${pkg.engines.node}\``);
  });
});
