/** Verify and copy the published pack into same-origin static assets. Never overwrites. */
import {readFile, lstat, mkdir, copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const lockRoot = path.join(root, 'data/3d/packs/flux-grid-v1');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

export function runtimeInventory(text) {
  return text.trim().split('\n').map(line => {
    const match = /^([a-f0-9]{64})  ([a-zA-Z0-9_./@-]+)$/.exec(line);
    if (!match || match[2].startsWith('/') || match[2].split('/').includes('..')) throw new Error('Invalid pinned inventory.');
    return {expected: match[1], relative: match[2]};
  }).filter(file => file.relative.startsWith('assets/') || file.relative === 'manifest.json');
}

async function rejectSymlinks(base, relative) {
  let current = base;
  for (const part of ['', ...relative.split('/')]) {
    if (part) current = path.join(current, part);
    const info = await lstat(current).catch(error => {
      if (error.code === 'ENOENT') return null;
      throw error;
    });
    if (info?.isSymbolicLink()) throw new Error(`Refusing symlink: ${current}`);
  }
}

export async function installFluxGridPack(packageRoot, repoRoot = root) {
  await lstat(path.join(repoRoot, 'web/package.json'));
  const manifestBytes = await readFile(path.join(lockRoot, 'manifest.json'));
  const inventory = runtimeInventory(await readFile(path.join(lockRoot, 'package.SHA256SUMS'), 'utf8'));
  const candidates = [];
  for (const {expected, relative} of inventory) {
    await rejectSymlinks(packageRoot, relative);
    const bytes = await readFile(path.join(packageRoot, relative));
    if (digest(bytes) !== expected) throw new Error(`Package checksum mismatch: ${relative}`);
    if (relative === 'manifest.json' && !bytes.equals(manifestBytes)) throw new Error('Package manifest differs from the reviewed manifest.');
    const target = `web/public/assets/flux-grid/${relative === 'manifest.json' ? relative : relative.slice(7)}`;
    await rejectSymlinks(repoRoot, target);
    const destination = path.join(repoRoot, target);
    const existing = await readFile(destination).catch(error => {
      if (error.code === 'ENOENT') return null;
      throw error;
    });
    if (existing && digest(existing) !== expected) throw new Error(`Existing file differs; no files copied: ${target}`);
    candidates.push({relative, destination, exists: existing !== null});
  }
  if (!candidates.some(file => file.relative === 'manifest.json') || candidates.filter(file => file.relative.endsWith('.glb')).length !== 54) throw new Error('Incomplete pinned runtime inventory.');
  const pending = candidates.filter(file => !file.exists);
  for (const file of pending) {
    await mkdir(path.dirname(file.destination), {recursive: true});
    await copyFile(path.join(packageRoot, file.relative), file.destination, 1);
  }
  return {verified: candidates.length, added: pending.length, identical: candidates.length - pending.length};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (!process.argv[2]) throw new Error('Usage: node scripts/install_flux_grid_pack.mjs /path/to/extracted/flux-grid-assets');
  console.log(JSON.stringify(await installFluxGridPack(path.resolve(process.argv[2])), null, 2));
}
