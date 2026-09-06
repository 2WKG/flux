/** Verify and copy the published pack into same-origin static assets. Never overwrites. */
import {readFile, lstat, mkdir, copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const lockRoot = path.join(root, 'data/3d/packs/flux-grid-v1');
const catalogRelative = 'data/3d/asset-archetypes-v1.json';
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

export function runtimeInventory(text) {
  const seen = new Set();
  return text.trim().split('\n').map(line => {
    const match = /^([a-f0-9]{64})  ([a-zA-Z0-9_./@-]+)$/.exec(line);
    if (!match || match[2].startsWith('/') || match[2].split('/').includes('..')) throw new Error('Invalid pinned inventory.');
    if (seen.has(match[2])) throw new Error(`Duplicate pinned inventory entry: ${match[2]}`);
    seen.add(match[2]);
    return {expected: match[1], relative: match[2]};
  }).filter(file => file.relative.startsWith('assets/') || file.relative === 'manifest.json');
}

/**
 * Confirm that the immutable manifest names exactly the runtime models the
 * installer will verify. This remains a packaging boundary: it never fetches,
 * mounts, or turns an asset into a Minnesota placement.
 */
export function parseReviewedJson(bytes, label, location) {
  try {
    return JSON.parse(bytes);
  } catch {
    throw new Error(`Invalid ${label} JSON: ${location}`);
  }
}

export function validateRuntimeManifest(manifest, inventory, catalogBytes) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('Invalid reviewed runtime manifest.');
  if (manifest.completion !== 'source_only_binaries_unpublished') throw new Error('Reviewed runtime manifest has an unsupported completion state.');
  if (!Array.isArray(manifest.assets) || manifest.assets.length !== 18) throw new Error('Reviewed runtime manifest must declare 18 assets.');
  const contract = manifest.source_contract;
  if (!contract || typeof contract !== 'object' || contract.file !== catalogRelative) throw new Error(`Reviewed runtime manifest must pin the frozen catalog: ${catalogRelative}`);
  if (typeof contract.sha256 !== 'string' || contract.sha256 !== digest(catalogBytes)) throw new Error('Reviewed runtime manifest source contract does not match the frozen catalog bytes.');
  const catalog = parseReviewedJson(catalogBytes, 'frozen asset archetype catalog', catalogRelative);
  if (!Array.isArray(catalog.archetypes) || catalog.archetypes.length === 0) throw new Error('Frozen asset archetype catalog declares no archetypes.');
  const known = new Set(catalog.archetypes.map(entry => entry?.id));
  const available = new Set(inventory.map(file => file.relative));
  const ids = new Set();
  const resources = new Set();
  for (const asset of manifest.assets) {
    if (!asset || typeof asset !== 'object' || typeof asset.archetype_id !== 'string' || !asset.archetype_id) throw new Error('Reviewed runtime manifest has an invalid archetype.');
    if (ids.has(asset.archetype_id)) throw new Error(`Reviewed runtime manifest duplicates archetype: ${asset.archetype_id}`);
    ids.add(asset.archetype_id);
    if (!known.has(asset.archetype_id)) throw new Error(`Reviewed runtime manifest names an archetype absent from the frozen catalog: ${asset.archetype_id}`);
    if (!asset.lods || typeof asset.lods !== 'object') throw new Error(`Reviewed runtime manifest has no LODs for ${asset.archetype_id}.`);
    for (const lod of ['lod0', 'lod1', 'lod2']) {
      const file = asset.lods[lod];
      if (!file || typeof file.path !== 'string' || !/^[a-zA-Z0-9_./@-]+$/.test(file.path) || file.path.split('/').includes('..')) throw new Error(`Reviewed runtime manifest has an invalid ${lod} path for ${asset.archetype_id}.`);
      const relative = `assets/${file.path}`;
      if (!available.has(relative)) throw new Error(`Reviewed runtime manifest resource is not pinned: ${relative}`);
      if (resources.has(relative)) throw new Error(`Reviewed runtime manifest reuses model resource: ${relative}`);
      resources.add(relative);
    }
  }
  // Defensive: 18 assets x 3 uniquely-pinned LODs already forces 54, so this line
  // cannot be reached from a manifest that passes the checks above.
  if (resources.size !== 54) throw new Error('Reviewed runtime manifest must declare 54 distinct model resources.');
  const totals = manifest.totals;
  if (!totals || typeof totals !== 'object' || totals.archetypes !== manifest.assets.length || totals.glb_files !== resources.size) throw new Error(`Reviewed runtime manifest totals disagree with its assets: expected ${manifest.assets.length} archetypes and ${resources.size} model resources.`);
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

export async function installFluxGridPack(packageRoot, repoRoot = root, {packRoot = lockRoot, catalogRoot = root} = {}) {
  await lstat(path.join(repoRoot, 'web/package.json'));
  const manifestPath = path.join(packRoot, 'manifest.json');
  const manifestBytes = await readFile(manifestPath);
  const inventory = runtimeInventory(await readFile(path.join(packRoot, 'package.SHA256SUMS'), 'utf8'));
  const catalogBytes = await readFile(path.join(catalogRoot, catalogRelative));
  validateRuntimeManifest(parseReviewedJson(manifestBytes, 'reviewed runtime manifest', manifestPath), inventory, catalogBytes);
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
