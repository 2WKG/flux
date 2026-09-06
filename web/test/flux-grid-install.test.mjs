import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, readdir, writeFile, symlink, rm, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {installFluxGridPack, runtimeInventory, validateRuntimeManifest} from '../../scripts/install_flux_grid_pack.mjs';

const packUrl=new URL('../../data/3d/packs/flux-grid-v1/',import.meta.url);
const catalogUrl=new URL('../../data/3d/asset-archetypes-v1.json',import.meta.url);

async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(),'flux-grid-install-test-'));
  const pack = path.join(root,'pack'), repo = path.join(root,'repo');
  await mkdir(pack);await mkdir(path.join(repo,'web'),{recursive:true});
  await writeFile(path.join(repo,'web/package.json'),'{}\n');
  return {root,pack,repo};
}

/**
 * A fixture whose *reviewed* pack root (the lock side the installer reads its
 * manifest and pinned inventory from) carries the supplied manifest bytes, so a
 * refusal can be driven through installFluxGridPack rather than asserted on the
 * validator alone.
 */
async function reviewedPackFixture(manifestBytes) {
  const base=await fixture();
  const packRoot=path.join(base.root,'reviewed-pack');
  await mkdir(packRoot);
  await writeFile(path.join(packRoot,'package.SHA256SUMS'),await readFile(new URL('package.SHA256SUMS',packUrl)));
  await writeFile(path.join(packRoot,'manifest.json'),manifestBytes);
  return {...base,packRoot};
}

async function committedManifest() {
  return JSON.parse(await readFile(new URL('manifest.json',packUrl),'utf8'));
}
test('installer rejects changed source bytes before creating runtime output', async()=>{
  const {root,pack,repo}=await fixture();
  try {
    const inventory=await readFile(new URL('../../data/3d/packs/flux-grid-v1/package.SHA256SUMS',import.meta.url),'utf8');
    const relative=inventory.split('\n').map(line=>line.slice(66)).find(file=>file.startsWith('assets/'));
    await mkdir(path.dirname(path.join(pack,relative)),{recursive:true});
    await writeFile(path.join(pack,relative),'not the pinned file');
    await assert.rejects(installFluxGridPack(pack,repo),/checksum mismatch/);
    await assert.rejects(access(path.join(repo,'web/public')));
  } finally {await rm(root,{recursive:true,force:true});}
});
test('installer rejects a symlink package root',async()=>{
  const {root,pack,repo}=await fixture();
  try {
    const link=path.join(root,'linked-pack');await symlink(pack,link,'dir');
    await assert.rejects(installFluxGridPack(link,repo),/Refusing symlink/);
    await assert.rejects(access(path.join(repo,'web/public')));
  } finally {await rm(root,{recursive:true,force:true});}
});
test('tracked publication manifest states the unpublished truth and stays contract-bound',async()=>{
  const archive=JSON.parse(await readFile(new URL('archive.json',packUrl),'utf8'));
  const manifest=JSON.parse(await readFile(new URL('manifest.json',packUrl),'utf8'));
  // The archive cannot be fetched, so the manifest must not call itself complete.
  assert.equal(archive.download_url,null);
  assert.equal(archive.publication_status,'binary_attachment_pending');
  assert.equal(manifest.completion,'source_only_binaries_unpublished');
  assert.equal(manifest.assets.length,18);
  assert.equal(manifest.assets.flatMap(asset=>Object.values(asset.lods)).length,54);
  // The provenance pin names a repository file; re-hash that exact file.
  assert.equal(manifest.source_contract.file,'data/3d/asset-archetypes-v1.json');
  const catalog=await readFile(catalogUrl);
  assert.equal(createHash('sha256').update(catalog).digest('hex'),manifest.source_contract.sha256);
  // The pack must not carry its own copy of the frozen catalog.
  await assert.rejects(access(new URL('source/asset-archetypes-v1.json',packUrl)));
  const inventory=runtimeInventory(await readFile(new URL('package.SHA256SUMS',packUrl),'utf8'));
  assert.ok(inventory.some(file=>file.relative==='assets/symbols/flux-grid@2x.png'));
  assert.equal(inventory.filter(file=>file.relative.endsWith('.glb')).length,54);
  assert.throws(()=>runtimeInventory(`${'0'.repeat(64)}  assets/../escape.glb`),/Invalid pinned inventory/);
  assert.throws(()=>runtimeInventory(`${'0'.repeat(64)}  assets/a.glb\n${'0'.repeat(64)}  assets/a.glb`),/Duplicate pinned inventory entry/);
  assert.doesNotThrow(()=>validateRuntimeManifest(manifest,inventory,catalog));
  const noLods=structuredClone(manifest);
  delete noLods.assets[0].lods;
  assert.throws(()=>validateRuntimeManifest(noLods,inventory,catalog),/has no LODs for /);
  const blankLod=structuredClone(manifest);
  blankLod.assets[0].lods.lod2.path='';
  assert.throws(()=>validateRuntimeManifest(blankLod,inventory,catalog),/invalid lod2 path/);
  const unpinned=structuredClone(manifest);
  unpinned.assets[0].lods.lod0.path='hospital/not-pinned.glb';
  assert.throws(()=>validateRuntimeManifest(unpinned,inventory,catalog),/resource is not pinned/);
});

test('published runtime release receipt names the immutable external bytes it attached',async()=>{
  const release=JSON.parse(await readFile(new URL('../../data/3d/packs/flux-grid-v1/releases/flux-grid-runtime-v1-20260906.json',import.meta.url),'utf8'));
  assert.equal(release.release_tag,'flux-grid-runtime-v1-20260906');
  // #338 attached the archive to the GitHub release and moved the receipt to the
  // published state; the tag now carries flux-grid-runtime-v1-20260906T103700Z.zip
  // at 5321737 bytes, whose sha256 is the archive_sha256 pinned below.
  assert.equal(release.publication_status,'published_external_attachment_verified');
  assert.equal(release.download_url,'https://github.com/2WKG/flux/releases/download/flux-grid-runtime-v1-20260906/flux-grid-runtime-v1-20260906T103700Z.zip');
  assert.equal(release.asset_filename,'flux-grid-runtime-v1-20260906T103700Z.zip');
  assert.equal(release.archive_sha256,'44ed49bd7e2a8392765825fdfc164e01061e7701befd8b89eaf38ac9ecc45d78');
  assert.equal(release.runtime_manifest_sha256,'068ca96a44b9730f3d59ab55c454cf5a8959b285db62625bbd2bcad57afd067b');
  assert.deepEqual(release.release_contents,{archetypes:18,glb_files:54,preview_png_files:18});
  assert.equal(release.source_contract.file,'data/3d/asset-archetypes-v1.json');
  const catalog=await readFile(catalogUrl);
  assert.equal(release.source_contract.sha256,createHash('sha256').update(catalog).digest('hex'));
  assert.equal(release.license.model_license,'CC0-1.0');
});

test('every enumerated manifest guarantee is a refusal with a failing case',async()=>{
  const manifest=await committedManifest();
  const inventory=runtimeInventory(await readFile(new URL('package.SHA256SUMS',packUrl),'utf8'));
  const catalog=await readFile(catalogUrl);
  // 18 assets.
  const short=structuredClone(manifest);
  short.assets=short.assets.slice(0,17);
  assert.throws(()=>validateRuntimeManifest(short,inventory,catalog),/must declare 18 assets/);
  // Unique archetype ids.
  const duplicateArchetype=structuredClone(manifest);
  duplicateArchetype.assets[1].archetype_id=duplicateArchetype.assets[0].archetype_id;
  assert.throws(()=>validateRuntimeManifest(duplicateArchetype,inventory,catalog),/duplicates archetype: /);
  // Archetype ids that exist in the frozen catalog.
  const fabricated=structuredClone(manifest);
  fabricated.assets[3].archetype_id='fabricated_archetype_not_in_catalog';
  assert.throws(()=>validateRuntimeManifest(fabricated,inventory,catalog),/absent from the frozen catalog: fabricated_archetype_not_in_catalog/);
  // Unique model resources.
  const reusedResource=structuredClone(manifest);
  reusedResource.assets[1].lods.lod0.path=reusedResource.assets[0].lods.lod0.path;
  assert.throws(()=>validateRuntimeManifest(reusedResource,inventory,catalog),/reuses model resource: /);
  // 54 model resources, asserted through the totals the manifest itself declares
  // (18 assets x 3 uniquely-pinned LODs makes the bare `resources.size !== 54`
  // line unreachable, so this is the branch a tampered count can actually hit).
  const wrongTotals=structuredClone(manifest);
  wrongTotals.totals.glb_files=53;
  assert.throws(()=>validateRuntimeManifest(wrongTotals,inventory,catalog),/totals disagree with its assets: expected 18 archetypes and 54 model resources/);
  // The reviewed completion state.
  const complete=structuredClone(manifest);
  complete.completion='binaries_published';
  assert.throws(()=>validateRuntimeManifest(complete,inventory,catalog),/unsupported completion state/);
  // The frozen catalog pin itself.
  const drifted=structuredClone(manifest);
  drifted.source_contract.sha256='0'.repeat(64);
  assert.throws(()=>validateRuntimeManifest(drifted,inventory,catalog),/does not match the frozen catalog bytes/);
  const repinned=structuredClone(manifest);
  repinned.source_contract.file='data/3d/somewhere-else.json';
  assert.throws(()=>validateRuntimeManifest(repinned,inventory,catalog),/must pin the frozen catalog: data\/3d\/asset-archetypes-v1\.json/);
});

test('installFluxGridPack refuses an invalid reviewed manifest before creating runtime output',async()=>{
  const manifest=await committedManifest();
  manifest.assets=manifest.assets.slice(0,17);
  const {root,pack,repo,packRoot}=await reviewedPackFixture(JSON.stringify(manifest));
  try {
    await assert.rejects(installFluxGridPack(pack,repo,{packRoot}),/Reviewed runtime manifest must declare 18 assets/);
    await assert.rejects(access(path.join(repo,'web/public')));
  } finally {await rm(root,{recursive:true,force:true});}
});

test('installFluxGridPack refuses fabricated archetype ids that the frozen catalog does not name',async()=>{
  const manifest=await committedManifest();
  // 18 assets, every LOD path left exactly as pinned in package.SHA256SUMS;
  // only the archetype identities are invented.
  manifest.assets=manifest.assets.map((asset,index)=>({...asset,archetype_id:`fabricated_archetype_${index}`}));
  const {root,pack,repo,packRoot}=await reviewedPackFixture(JSON.stringify(manifest));
  try {
    await assert.rejects(installFluxGridPack(pack,repo,{packRoot}),/absent from the frozen catalog: fabricated_archetype_0/);
    await assert.rejects(access(path.join(repo,'web/public')));
  } finally {await rm(root,{recursive:true,force:true});}
});

test('installFluxGridPack refuses malformed reviewed manifest bytes by name',async()=>{
  const {root,pack,repo,packRoot}=await reviewedPackFixture('{"assets": [ this is not json');
  try {
    await assert.rejects(installFluxGridPack(pack,repo,{packRoot}),/Invalid reviewed runtime manifest JSON: /);
    await assert.rejects(access(path.join(repo,'web/public')));
  } finally {await rm(root,{recursive:true,force:true});}
});
test('every committed pack file re-hashes to its pinned digest',async()=>{
  const packDir=fileURLToPath(new URL('../../data/3d/packs/flux-grid-v1/',import.meta.url));
  const pinned=new Map((await readFile(path.join(packDir,'committed-sources.SHA256SUMS'),'utf8'))
    .split('\n').filter(Boolean).map(line=>[line.slice(66),line.slice(0,64)]));
  const present=(await readdir(packDir,{recursive:true,withFileTypes:true}))
    .filter(entry=>entry.isFile())
    .map(entry=>path.relative(packDir,path.join(entry.parentPath??entry.path,entry.name)).split(path.sep).join('/'))
    .filter(relative=>relative!=='committed-sources.SHA256SUMS'
      && !relative.split('/').some(part=>part==='__pycache__'||part.startsWith('.')));
  assert.ok(pinned.size>=20,`inventory is too small to be the pack: ${pinned.size}`);
  // An added or deleted file is as much a drift as a mutated byte.
  assert.deepEqual(present.sort(),[...pinned.keys()].sort());
  for (const [relative,digest] of pinned) {
    const bytes=await readFile(path.join(packDir,relative));
    assert.equal(createHash('sha256').update(bytes).digest('hex'),digest,`${relative} does not match its pinned sha256`);
  }
});
