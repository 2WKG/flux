/** Verify and copy the published pack into same-origin static assets. Never overwrites. */
import {readFile, lstat, mkdir, copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const lockRoot = path.join(root, 'data/3d/packs/flux-grid-v1');
const catalogRelative = 'data/3d/asset-archetypes-v1.json';
const releaseReceiptRelative = 'releases/flux-grid-runtime-v1-20260906.json';
const publishedRelease = Object.freeze({
  release_tag: 'flux-grid-runtime-v1-20260906',
  asset_filename: 'flux-grid-runtime-v1-20260906T103700Z.zip',
  archive_sha256: '44ed49bd7e2a8392765825fdfc164e01061e7701befd8b89eaf38ac9ecc45d78',
  runtime_manifest_sha256: '068ca96a44b9730f3d59ab55c454cf5a8959b285db62625bbd2bcad57afd067b',
  release_contents: {archetypes: 18, glb_files: 54, preview_png_files: 18},
});
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

export function validateRuntimeManifest(manifest, inventory, catalogBytes, {completion} = {}) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('Invalid reviewed runtime manifest.');
  const validCompletions=new Set(['source_only_binaries_unpublished','complete_locally_generated']);
  if (!validCompletions.has(manifest.completion) || (completion && manifest.completion!==completion)) throw new Error('Reviewed runtime manifest has an unsupported completion state.');
  if (!Array.isArray(manifest.assets) || manifest.assets.length !== 18) throw new Error('Reviewed runtime manifest must declare 18 assets.');
  if (manifest.completion==='source_only_binaries_unpublished') {
    const contract = manifest.source_contract;
    if (!contract || typeof contract !== 'object' || contract.file !== catalogRelative) throw new Error(`Reviewed runtime manifest must pin the frozen catalog: ${catalogRelative}`);
    if (typeof contract.sha256 !== 'string' || contract.sha256 !== digest(catalogBytes)) throw new Error('Reviewed runtime manifest source contract does not match the frozen catalog bytes.');
  } else if (manifest.contract_id!=='flux:3d-asset-archetypes:v1' || manifest.package_name!=='flux-grid-assets-runtime' || manifest.runtime_base_url!=='/assets/flux-grid/' || manifest.status_material!=='MAT_STATUS') {
    throw new Error('Published runtime manifest has an unsupported complete-local shape.');
  }
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
  if (manifest.completion==='source_only_binaries_unpublished') {
    const totals = manifest.totals;
    if (!totals || typeof totals !== 'object' || totals.archetypes !== manifest.assets.length || totals.glb_files !== resources.size) throw new Error(`Reviewed runtime manifest totals disagree with its assets: expected ${manifest.assets.length} archetypes and ${resources.size} model resources.`);
  }
}

export function validatePublishedReleaseReceipt(receipt, catalogBytes) {
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)) throw new Error('Invalid published release receipt.');
  for (const [key,value] of Object.entries(publishedRelease)) {
    if (JSON.stringify(receipt[key]) !== JSON.stringify(value)) throw new Error(`Published release receipt does not pin ${key}.`);
  }
  if (receipt.publication_status!=='published_external_attachment_verified') throw new Error('Published release receipt is not verified as attached.');
  if (receipt.source_contract?.file!==catalogRelative || receipt.source_contract.sha256!==digest(catalogBytes)) throw new Error('Published release receipt source contract does not match the frozen catalog bytes.');
  return publishedRelease;
}

async function verifiedPublishedRelease(packRoot, catalogBytes, archivePath) {
  if (!archivePath) throw new Error('Installer requires a verified published archive path.');
  const receiptBytes=await readFile(path.join(packRoot,releaseReceiptRelative));
  const receipt=parseReviewedJson(receiptBytes,'published release receipt',path.join(packRoot,releaseReceiptRelative));
  const release=validatePublishedReleaseReceipt(receipt,catalogBytes);
  await rejectSymlinks(path.dirname(archivePath),path.basename(archivePath));
  if (digest(await readFile(archivePath))!==release.archive_sha256) throw new Error('Published release archive checksum mismatch.');
  return release;
}

function validatePublishedPackageShape(inventory, release) {
  const glbs=inventory.filter(file=>file.relative.endsWith('.glb'));
  const previews=inventory.filter(file=>file.relative.endsWith('.preview.png'));
  const metadata=inventory.filter(file=>file.relative.endsWith('.meta.json'));
  if (inventory.length!==96 || glbs.length!==release.release_contents.glb_files || previews.length!==release.release_contents.preview_png_files || metadata.length!==release.release_contents.archetypes || !inventory.some(file=>file.relative==='manifest.json')) {
    throw new Error('Published runtime package has an incomplete or unsupported shape.');
  }
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

export async function installFluxGridPack(packageRoot, repoRoot = root, {packRoot = lockRoot, catalogRoot = root, archivePath} = {}) {
  await lstat(path.join(repoRoot, 'web/package.json'));
  await rejectSymlinks(path.dirname(packageRoot),path.basename(packageRoot));
  const catalogBytes = await readFile(path.join(catalogRoot, catalogRelative));
  const release=await verifiedPublishedRelease(packRoot,catalogBytes,archivePath);
  const manifestPath = path.join(packageRoot, 'manifest.json');
  const manifestBytes = await readFile(manifestPath);
  if (digest(manifestBytes)!==release.runtime_manifest_sha256) throw new Error('Published release runtime manifest checksum mismatch.');
  const inventory = runtimeInventory(await readFile(path.join(packageRoot, 'package.SHA256SUMS'), 'utf8'));
  validatePublishedPackageShape(inventory,release);
  validateRuntimeManifest(parseReviewedJson(manifestBytes, 'published runtime manifest', manifestPath), inventory, catalogBytes, {completion:'complete_locally_generated'});
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
  if (!process.argv[2] || !process.argv[3]) throw new Error('Usage: node scripts/install_flux_grid_pack.mjs /path/to/extracted/flux-grid-assets /path/to/verified-release.zip');
  console.log(JSON.stringify(await installFluxGridPack(path.resolve(process.argv[2]),root,{archivePath:path.resolve(process.argv[3])}), null, 2));
}
