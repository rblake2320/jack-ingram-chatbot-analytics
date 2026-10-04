import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {Box3,Matrix4,Vector3,Quaternion} from 'three';
import {validateManifest,packGroups,projectedExtent} from './atlas-core.mjs';
const manifest=JSON.parse(readFileSync('src/demo/data/porsche_9922_systems.json','utf8'));
const bytes=readFileSync('src/demo/static/models/porsche-9922-systems.glb'),jsonLength=bytes.readUInt32LE(12);
const doc=JSON.parse(bytes.subarray(20,20+jsonLength)),binaryOffset=28+jsonLength,boxes=new Map();
function visit(index,parent,owner){
  const n=doc.nodes[index],local=n.matrix?new Matrix4().fromArray(n.matrix):new Matrix4().compose(new Vector3(...(n.translation||[0,0,0])),new Quaternion(...(n.rotation||[0,0,0,1])),new Vector3(...(n.scale||[1,1,1])));
  const world=new Matrix4().multiplyMatrices(parent,local);owner=n.extras?.component_id || owner;
  if(n.mesh!==undefined){assert.ok(owner);if(!boxes.has(owner))boxes.set(owner,new Box3());
    for(const primitive of doc.meshes[n.mesh].primitives){const a=doc.accessors[primitive.attributes.POSITION],v=doc.bufferViews[a.bufferView];assert.equal(a.componentType,5126);assert.equal(a.type,'VEC3');
      for(let i=0;i<a.count;i++){const offset=binaryOffset+(v.byteOffset||0)+(a.byteOffset||0)+i*(v.byteStride||12);boxes.get(owner).expandByPoint(new Vector3(bytes.readFloatLE(offset),bytes.readFloatLE(offset+4),bytes.readFloatLE(offset+8)).applyMatrix4(world));}}
  }
  for(const child of n.children || [])visit(child,world,owner);
}
for(const node of doc.scenes[doc.scene||0].nodes)visit(node,new Matrix4());
const close=(actual,expected,tolerance=1e-5)=>assert.ok(Math.abs(actual-expected)<tolerance,`${actual} differs from ${expected}`);
test('exported systems geometry has owned meshes, checked sources and distinct MY2026 identity',()=>{
  validateManifest(manifest,doc.meshes.length);assert.equal(createHash('sha256').update(bytes).digest('hex'),manifest.sha256);
  assert.equal(boxes.size,manifest.components.length);assert.equal(manifest.model_year,2026);assert.equal(manifest.hybrid,false);
  const sources=new Set(manifest.sources.map(s=>s.id));for(const c of manifest.components){assert.ok(c.geometry_grade.startsWith('D'));assert.ok(c.source_ids.length && c.source_ids.every(id=>sources.has(id)));}
});
test('actual GLB vertices preserve vehicle dimensions, axle spacing, tires and rotors in meters',()=>{
  const all=new Box3();for(const box of boxes.values())all.union(box);const size=all.getSize(new Vector3());close(size.z,4.542);close(size.y,1.303);close(size.x,1.852,.003);
  const front=boxes.get('front-left-tire'),rear=boxes.get('rear-left-tire');close(front.getCenter(new Vector3()).z-rear.getCenter(new Vector3()).z,2.450);
  close(front.getSize(new Vector3()).x,.245);close(front.getSize(new Vector3()).y,.6795);close(rear.getSize(new Vector3()).x,.305);close(rear.getSize(new Vector3()).y,.7164);
  close(boxes.get('front-left-brake').getSize(new Vector3()).y,.408);close(boxes.get('rear-left-brake').getSize(new Vector3()).y,.380);
  writeFileSync('docs/evidence/2026-10-04/porsche-systems-geometry.json',JSON.stringify({outcome:'Worked',sha256:manifest.sha256,measured_from:'Actual uncompressed GLB vertex buffers and node world transforms',size_m:size.toArray(),wheelbase_m:front.getCenter(new Vector3()).z-rear.getCenter(new Vector3()).z,components:[...boxes].map(([id,b])=>({id,center:b.getCenter(new Vector3()).toArray(),size:b.getSize(new Vector3()).toArray()}))},null,2)+'\n');
});
for(const aspect of [.46,1.8])test(`all exported systems parts pack without overlap at aspect ${aspect}`,()=>{
  const right=new Vector3(1,0,-1).normalize(),up=new Vector3(-.3,1,-.3).normalize();up.addScaledVector(right,-up.dot(right)).normalize();
  const items=[...boxes].map(([id,box])=>({id,box})),places=packGroups(items,right,up,aspect),ext=items.map((item,i)=>projectedExtent(item.box.clone().translate(places[i].delta),right,up));
  for(let a=0;a<ext.length;a++)for(let b=a+1;b<ext.length;b++)assert.ok(ext[a].maxX<=ext[b].minX || ext[b].maxX<=ext[a].minX || ext[a].maxY<=ext[b].minY || ext[b].maxY<=ext[a].minY);
});
