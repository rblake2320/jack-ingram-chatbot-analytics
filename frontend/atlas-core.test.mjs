import test from 'node:test';
import assert from 'node:assert/strict';
import {Box3, Vector3} from 'three';
import {projectedExtent,packGroups,validateManifest,validAction,explodeOffset} from './atlas-core.mjs';
import {readFileSync} from 'node:fs';

test('licensed model manifest accounts for every mesh including repeated source names',()=>{
  const m=JSON.parse(readFileSync('src/demo/data/vehicle_atlas.json','utf8'));
  assert.equal(validateManifest(m,45),true);
  const duplicate=structuredClone(m); duplicate.components[0].mesh_indices.push(8);
  assert.throws(()=>validateManifest(duplicate,45),/Duplicate/);
  const orphan=structuredClone(m); orphan.components[0].mesh_indices.pop();
  assert.throws(()=>validateManifest(orphan,45),/Unassigned/);
});
for(const aspect of [.46,1.8]) test(`rotated world bounds pack without overlapping at aspect ${aspect}`,()=>{
  const right=new Vector3(1,0,-1).normalize(), up=new Vector3(-.3,1,-.3).normalize();
  // Make camera basis orthogonal, as in the viewer.
  up.addScaledVector(right,-up.dot(right)).normalize();
  const items=Array.from({length:7},(_,i)=>({id:String(i),box:new Box3(new Vector3(i-1,-i/3,-2),new Vector3(i+1,2+i/2,1))}));
  const p=packGroups(items,right,up,aspect);
  const ext=items.map((item,i)=>projectedExtent(item.box.clone().translate(p[i].delta),right,up));
  for(let a=0;a<ext.length;a++) for(let b=a+1;b<ext.length;b++) assert.ok(ext[a].maxX<=ext[b].minX || ext[b].maxX<=ext[a].minX || ext[a].maxY<=ext[b].minY || ext[b].maxY<=ext[a].minY);
});
test('viewer executes only bounded component actions',()=>{
  assert.equal(validAction({operation:'isolate',component_id:'glass'},['glass']),true);
  assert.equal(validAction({operation:'execute',component_id:'glass'},['glass']),false);
  assert.equal(validAction({operation:'select',component_id:'../../private'},['glass']),false);
});

test('continuous exploded poses restore rest, reach endpoints and never accumulate',()=>{
  const rest=new Vector3(1,2,3), direction=[0,1.8,0];
  for(const amount of [0,.5,1,.5,0,1,0]) {
    const posed=rest.clone().add(explodeOffset(direction,amount));
    assert.deepEqual(posed.toArray(),[1,2+1.8*amount,3]);
    assert.deepEqual(rest.toArray(),[1,2,3]);
  }
  assert.throws(()=>explodeOffset(direction,2),/pose/);
});

test('F15-style render, camera and animation actions are bounded',()=>{
  for(const action of [{operation:'render',value:'xray'},{operation:'camera',value:'top'},{operation:'explode',value:.5},{operation:'tour'}]) assert.equal(validAction(action,['glass']),true);
  for(const action of [{operation:'render',value:'eval'},{operation:'explode',value:2},{operation:'camera',value:'private'},{operation:'tour',url:'https://evil.invalid'}]) assert.equal(validAction(action,['glass']),false);
});
