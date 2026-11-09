import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sha256 = value => createHash('sha256').update(value).digest('hex');
const manifest = JSON.parse(readFileSync(path.join(frontend, 'patches/braces-3.0.3-depth-guard.json'), 'utf8'));
const guard = readFileSync(path.join(frontend, 'patches/braces-depth-guard.js'));
if (sha256(guard) !== manifest.guard_sha256) throw new Error('Braces guard digest mismatch');
const lock = JSON.parse(readFileSync(path.join(frontend, 'package-lock.json'), 'utf8'));
const updates = [];

// No generic text patching or version relabeling: unknown upstream bytes fail
// installation so this local mitigation must be reviewed when braces changes.
for (const [location, entry] of Object.entries(lock.packages)) {
  if (!location.endsWith('node_modules/braces')) continue;
  if (entry.version !== manifest.version) throw new Error('Review required for changed braces version');
  const directory = path.join(frontend, location);
  if (!existsSync(directory)) {
    // braces belongs only to lint tooling and is absent from --omit=dev installs.
    if (entry.dev === true) continue;
    throw new Error('Expected braces installation is missing');
  }
  const installed = JSON.parse(readFileSync(path.join(directory, 'package.json'), 'utf8'));
  if (installed.name !== manifest.package || installed.version !== manifest.version) {
    throw new Error('Unexpected braces package identity');
  }
  for (const file of manifest.files) {
    const target = path.join(directory, file.path);
    const original = readFileSync(target, 'utf8');
    const digest = sha256(original);
    if (digest === file.patched_sha256) continue;
    if (digest !== file.original_sha256) throw new Error('Unexpected braces source digest');
    let patched = original;
    for (const { before, after, count } of file.replacements) {
      if (patched.split(before).length - 1 !== count) throw new Error('Unexpected braces patch context');
      patched = patched.split(before).join(after);
    }
    if (sha256(patched) !== file.patched_sha256) throw new Error('Braces patched digest mismatch');
    updates.push([target, patched]);
  }
  updates.push([path.join(directory, 'lib/sapling-depth-guard.js'), guard]);
}

// Validate every source before writing any of them. Re-running is idempotent.
for (const [target, value] of updates) writeFileSync(target, value);
console.log('Verified local braces depth mitigation (upstream advisory remains visible).');
