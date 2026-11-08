#!/usr/bin/env node
/**
 * Fetch the commercially licensed font files (Gummi) into
 * src/app/fonts/licensed/ before a build.
 *
 * Why this exists: Gummi is licensed for saplinglearn.com only and may not be
 * redistributed, and this repository is public, so the binaries live in the
 * PRIVATE repo named in src/app/fonts/licensed-fonts.json and are pulled in at
 * build time with a read-only token. The directory they land in is git-ignored.
 *
 *   LICENSED_FONTS_TOKEN     GitHub token with read access to that repo's
 *                            contents (fine-grained PAT, Contents: read-only).
 *   LICENSED_FONTS_REQUIRED  "1" makes a missing or unverifiable file fatal.
 *   WORKERS_CI               Set to "1" by Cloudflare Workers Builds; treated
 *                            like LICENSED_FONTS_REQUIRED, so a deploy can
 *                            never quietly ship the Aleo stand-in.
 *
 * Every file is checked against the SHA-256 in licensed-fonts.json, both the
 * ones already on disk and the ones downloaded. Without a token on a
 * non-deploy build (CI, E2E, a teammate's laptop) this only warns: next.config
 * then aliases the heading font to the Aleo fallback (see
 * src/app/fonts/gummi.fallback.ts).
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifestPath = path.join(root, 'src/app/fonts/licensed-fonts.json');
const outDir = path.join(root, 'src/app/fonts/licensed');

const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
const env = process.env;
const required = env.LICENSED_FONTS_REQUIRED === '1' || env.WORKERS_CI === '1';
const token = (env.LICENSED_FONTS_TOKEN ?? '').trim();
const repo = (env.LICENSED_FONTS_REPO ?? '').trim() || manifest.repo;
const ref = (env.LICENSED_FONTS_REF ?? '').trim() || manifest.ref;

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');

async function verifiedOnDisk(file) {
  try {
    return sha256(await readFile(path.join(outDir, file.name))) === file.sha256;
  } catch {
    return false;
  }
}

async function download(file) {
  const url = `https://api.github.com/repos/${repo}/contents/${file.source}?ref=${encodeURIComponent(ref)}`;
  const res = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github.raw+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'sapling-fetch-licensed-fonts',
    },
  });
  if (!res.ok) {
    const status = [res.status, res.statusText].filter(Boolean).join(' ');
    throw new Error(`${file.name}: GitHub returned ${status} for ${repo}@${ref}:${file.source}`);
  }
  const buf = Buffer.from(await res.arrayBuffer());
  const got = sha256(buf);
  if (got !== file.sha256) {
    throw new Error(`${file.name}: SHA-256 mismatch (expected ${file.sha256}, got ${got})`);
  }
  // Write-then-rename so an interrupted run never leaves a truncated font
  // that a later run would mistake for a partial download.
  const dest = path.join(outDir, file.name);
  await writeFile(`${dest}.part`, buf);
  await rename(`${dest}.part`, dest);
}

function fail(message) {
  if (required) {
    console.error(`✗ licensed fonts: ${message}`);
    console.error('  This is a deploy build (WORKERS_CI=1 or LICENSED_FONTS_REQUIRED=1), so it stops here');
    console.error('  rather than shipping headings in the Aleo stand-in. See docs/licensed-fonts.md.');
    process.exit(1);
  }
  console.warn(`⚠ licensed fonts: ${message}`);
  console.warn('  Headings will render in Aleo (the stand-in) for this build. See docs/licensed-fonts.md.');
}

const missing = [];
for (const file of manifest.files) {
  if (!(await verifiedOnDisk(file))) missing.push(file);
}

if (missing.length === 0) {
  console.log(`✓ licensed fonts: ${manifest.files.length} file(s) present and verified`);
} else if (!token) {
  fail(`${missing.map((f) => f.name).join(', ')} missing and LICENSED_FONTS_TOKEN is not set`);
} else {
  await mkdir(outDir, { recursive: true });
  try {
    for (const file of missing) await download(file);
    console.log(`✓ licensed fonts: downloaded and verified ${missing.length} file(s) from ${repo}`);
  } catch (err) {
    fail(err instanceof Error ? err.message : String(err));
  }
}
