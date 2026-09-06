import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {build} from 'esbuild';

const compiled = await build({entryPoints: [new URL('./layers/fluxGridAssets.ts', import.meta.url).pathname], bundle: true, packages: 'external', platform: 'node', format: 'esm', write: false});
const folder = await mkdtemp(new URL('../../node_modules/.flux-assets-test-', import.meta.url).pathname);
const entry = path.join(folder, 'assets.mjs');
await writeFile(entry, compiled.outputFiles[0].text);
const {assertPlacements, gltfToMapMatrix, lodForZoom, statusVariantGlb, FluxAssetCache, loadFluxGroups, createFluxAssetLayers} = await import(pathToFileURL(entry).href);
test.after(() => rm(folder, {recursive: true, force: true}));

const placement = {id: 'test', archetype_id: 'hospital', position: [0, 0, 0], heading_degrees: 0, label: 'Test geometry', status: 'synthetic', artifact_id: 'test-only'};
function glb() {
  const json = Buffer.from(JSON.stringify({asset:{version:'2.0'}, materials:[{name:'MAT_STATUS', pbrMetallicRoughness:{baseColorFactor:[.3,.3,.3,1]}},{name:'MAT_ACCENT',emissiveFactor:[0,.5,.7]}]}));
  const length = Math.ceil(json.length / 4) * 4;
  const bytes = Buffer.alloc(20 + length + 12, 32);
  bytes.writeUInt32LE(0x46546c67,0);bytes.writeUInt32LE(2,4);bytes.writeUInt32LE(bytes.length,8);bytes.writeUInt32LE(length,12);bytes.writeUInt32LE(0x4e4f534a,16);json.copy(bytes,20);
  bytes.writeUInt32LE(4,20+length);bytes.writeUInt32LE(0x004e4942,24+length);bytes.set([1,2,3,4],28+length);
  return bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
}
const parse = buffer => JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,20,new DataView(buffer).getUint32(12,true))));
test('axes, grounding and clockwise heading are converted exactly once', () => {
  const apply = (m,p) => [m[0]*p[0]+m[4]*p[1]+m[8]*p[2],m[1]*p[0]+m[5]*p[1]+m[9]*p[2],m[2]*p[0]+m[6]*p[1]+m[10]*p[2]].map(x=>Math.abs(x)<1e-12?0:x);
  assert.deepEqual(apply(gltfToMapMatrix(0),[0,0,-1]),[0,1,0]);
  assert.deepEqual(apply(gltfToMapMatrix(90),[0,0,-1]),[1,0,0]);
  assert.deepEqual(apply(gltfToMapMatrix(53),[0,1,0]),[0,0,1]);
  assert.deepEqual(apply(gltfToMapMatrix(53),[0,0,0]),[0,0,0]);
});
test('status vocabulary rejects inherited keys, absent identity and null accepted status', () => {
  for (const status of ['constructor','toString',null]) assert.throws(()=>assertPlacements([{...placement,status}],'accepted'));
  assert.throws(()=>assertPlacements([{...placement,artifact_id:''}],'accepted'));
  assert.doesNotThrow(()=>assertPlacements([{...placement,status:null}],'catalogue'));
});
test('neutral GLB is identical and tint only changes MAT_STATUS, not geometry or accent', () => {
  const original=glb(), modified=statusVariantGlb(original,'hypothetical');
  assert.deepEqual(statusVariantGlb(original,null),original);
  assert.notDeepEqual(parse(original).materials[0],parse(modified).materials[0]);
  assert.deepEqual(parse(original).materials[1],parse(modified).materials[1]);
  assert.deepEqual(new Uint8Array(original).slice(-12),new Uint8Array(modified).slice(-12));
});
test('zoom bands, unavailable states and regional fallback never load model geometry', async () => {
  assert.deepEqual([11,12,15,17].map(lodForZoom),['symbol','lod2','lod1','lod0']);
  const never = {url:()=>{throw new Error('unexpected model fetch');}};
  const manifest={assets:[{archetype_id:'hospital',lods:{lod0:{triangles:1}}}]};
  assert.deepEqual(await loadFluxGroups(never,manifest,[placement],{zoom:5,mode:'accepted'}),[]);
  assert.deepEqual(await loadFluxGroups(never,manifest,[{...placement,status:'unavailable'}],{zoom:18,mode:'accepted'}),[]);
  const layers=createFluxAssetLayers({zoom:5,mode:'accepted'},{placements:[{...placement,status:'request_failed'}],groups:[]});
  assert.ok(layers.every(layer=>layer.props.data.length===0));
});
test('checksum failure is explicit; successful cache deduplicates and disposal rejects reuse', async () => {
  const bytes=glb(), file={path:'hospital/test.glb',bytes:bytes.byteLength,sha256:createHash('sha256').update(new Uint8Array(bytes)).digest('hex'),triangles:1};
  const originalFetch=globalThis.fetch;let calls=0;
  globalThis.fetch=async()=>{calls++;return new Response(bytes);};
  const cache=new FluxAssetCache('/test-only/');
  try {
    await assert.rejects(cache.url({...file,sha256:'0'.repeat(64)},null),/checksum mismatch/);
    const one=await cache.url(file,null),two=await cache.url(file,null);
    assert.equal(one,two);assert.equal(calls,2);
    cache.dispose();await assert.rejects(cache.url(file,null),/disposed/);
  } finally {cache.dispose();globalThis.fetch=originalFetch;}
});
