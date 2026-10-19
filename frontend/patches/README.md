# Dependency security compatibility patches

`npm ci` runs `scripts/apply-security-patches.mjs`. Do not use `--ignore-scripts`
for a build or lint environment that consumes `braces`.

## Braces 3.0.3: local structural bounds

[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
has no patched upstream release. Next's lint plugin still depends on
`fast-glob` → `micromatch` → `braces`. We preserve these public APIs and apply
a local structural bound rather than substitute a different glob implementation.

The MIT-licensed upstream package keeps its name/version and remains visible to
`npm audit`. This is a **local mitigation, not an upstream fixed release or an
audit suppression**. The JSON manifest pins the upstream and patched file hashes;
the adjacent diff is for review. Installation fails if upstream source changes.

The parser rejects more than 127 nested brace/parenthesis groups before building
the next group. Iterative validation protects `compile`, `expand`, and `stringify`
when called directly with an AST, including child/parent cycles. The traversal
also bounds AST node counts. These guards do not promise safe arbitrary attacker
regular expressions or unlimited brace expansion; existing character/range limits
still apply. Normal repository/workspace glob patterns remain supported.

Remove this mitigation only after a released upstream fix or a separately reviewed
parent migration eliminates the vulnerable package. Recheck the pinned bytes and
run the security regression tests whenever upgrading lint tooling.

## Glob and KaTeX overrides

`@node-minify/core`'s exact glob 10.3.3 is replaced with the upstream patched
10.5.0 within the same major. The minifier uses the library API, which remains
compatible; the vulnerable CLI path is tested with a harmless metacharacter
filename. See [GHSA-5j98-mcp5-4vw2](https://github.com/advisories/GHSA-5j98-mcp5-4vw2).

All KaTeX consumers resolve to the direct patched `0.18.2` dependency for
[GHSA-238p-pmpm-9mq7](https://github.com/KaTeX/KaTeX/security/advisories/GHSA-238p-pmpm-9mq7).
The parents' older ranges are overridden deliberately: their used public
`renderToString` API remains supported. KaTeX's CSS and mhchem extension come from
that same package. Version 0.18 prefixes internal CSS classes; Sapling has no
custom rules targeting those internal classes. Regression tests exercise real
markdown, chemistry, diagrams, macros, MathML and polluted prototype rejection.

KaTeX is pinned to 0.18.2: later 0.18.x releases bring commander 15 and raise
the install-time Node minimum beyond Sapling's declared Node 20.9 support.
