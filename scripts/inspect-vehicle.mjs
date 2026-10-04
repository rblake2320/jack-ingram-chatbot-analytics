import {readFile,writeFile} from 'node:fs/promises';
import {Box3,Matrix4,Vector3,Quaternion} from 'three';
const file=await readFile('src/demo/static/models/porsche-911-carrera-4s.glb');
const doc=JSON.parse(file.subarray(20,20+file.readUInt32LE(12)).toString('utf8'));
const records=[];
function visit(i,parent) {
  const n=doc.nodes[i];
  const local=n.matrix ? new Matrix4().fromArray(n.matrix) : new Matrix4().compose(new Vector3().fromArray(n.translation||[0,0,0]),new Quaternion().fromArray(n.rotation||[0,0,0,1]),new Vector3().fromArray(n.scale||[1,1,1]));
  const world=new Matrix4().multiplyMatrices(parent,local);
  if(n.mesh!==undefined) {
    const m=doc.meshes[n.mesh],b=new Box3();
    for(const p of m.primitives) {
      const a=doc.accessors[p.attributes.POSITION];
      b.union(new Box3(new Vector3().fromArray(a.min),new Vector3().fromArray(a.max)).applyMatrix4(world));
    }
    records.push({mesh_index:n.mesh,node_index:i,name:n.name,materials:m.primitives.map(p=>doc.materials[p.material]?.name),center:b.getCenter(new Vector3()).toArray(),size:b.getSize(new Vector3()).toArray()});
  }
  for(const child of n.children||[]) visit(child,world);
}
for(const i of doc.scenes[doc.scene||0].nodes) visit(i,new Matrix4());
const report={asset:doc.asset,meshes:records.sort((a,b)=>a.mesh_index-b.mesh_index)};
await writeFile('docs/evidence/2026-10-04/vehicle-source-geometry.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report.meshes,null,2));
