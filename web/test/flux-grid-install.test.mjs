import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, readdir, writeFile, symlink, rm, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {installFluxGridPack, runtimeInventory} from '../../scripts/install_flux_grid_pack.mjs';

async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(),'flux-grid-install-test-'));
  const pack = path.join(root,'pack'), repo = path.join(root,'repo');
  await mkdir(pack);await mkdir(path.join(repo,'web'),{recursive:true});
  await writeFile(path.join(repo,'web/package.json'),'{}\n');
  return {root,pack,repo};
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
  const packUrl=new URL('../../data/3d/packs/flux-grid-v1/',import.meta.url);
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
  const catalog=await readFile(new URL('../../data/3d/asset-archetypes-v1.json',import.meta.url));
  assert.equal(createHash('sha256').update(catalog).digest('hex'),manifest.source_contract.sha256);
  // The pack must not carry its own copy of the frozen catalog.
  await assert.rejects(access(new URL('source/asset-archetypes-v1.json',packUrl)));
  const inventory=runtimeInventory(await readFile(new URL('package.SHA256SUMS',packUrl),'utf8'));
  assert.ok(inventory.some(file=>file.relative==='assets/symbols/flux-grid@2x.png'));
  assert.equal(inventory.filter(file=>file.relative.endsWith('.glb')).length,54);
  assert.throws(()=>runtimeInventory(`${'0'.repeat(64)}  assets/../escape.glb`),/Invalid pinned inventory/);
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
