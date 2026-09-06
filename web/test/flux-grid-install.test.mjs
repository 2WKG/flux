import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, writeFile, symlink, rm, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
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
test('tracked publication manifest pins the exact public archive and preserves no-binary boundary',async()=>{
  const archive=JSON.parse(await readFile(new URL('../../data/3d/packs/flux-grid-v1/archive.json',import.meta.url),'utf8'));
  const manifest=JSON.parse(await readFile(new URL('../../data/3d/packs/flux-grid-v1/manifest.json',import.meta.url),'utf8'));
  assert.equal(archive.bytes,24713909);
  assert.equal(archive.sha256,'ee032fe57c2cb61495271d6387a24f3acf9abd68e84e3b5dd2546ab90d45b39c');
  assert.equal(manifest.assets.length,18);
  assert.equal(manifest.assets.flatMap(asset=>Object.values(asset.lods)).length,54);
  const inventory=runtimeInventory(await readFile(new URL('../../data/3d/packs/flux-grid-v1/package.SHA256SUMS',import.meta.url),'utf8'));
  assert.ok(inventory.some(file=>file.relative==='assets/symbols/flux-grid@2x.png'));
  assert.equal(inventory.filter(file=>file.relative.endsWith('.glb')).length,54);
  assert.throws(()=>runtimeInventory(`${'0'.repeat(64)}  assets/../escape.glb`),/Invalid pinned inventory/);
});
