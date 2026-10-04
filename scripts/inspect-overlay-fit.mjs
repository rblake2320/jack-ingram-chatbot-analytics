import {readFile} from 'node:fs/promises';
import {Box3,Matrix4,Quaternion,Vector3} from 'three';

async function bounds(path,ignored=new Set()) {
  const file=await readFile(path);
  const doc=JSON.parse(file.subarray(20,20+file.readUInt32LE(12)).toString('utf8'));
  const complete=new Box3();
  function visit(index,parent) {
    const node=doc.nodes[index];
    const local=node.matrix ? new Matrix4().fromArray(node.matrix) : new Matrix4().compose(
      new Vector3().fromArray(node.translation || [0,0,0]),
      new Quaternion().fromArray(node.rotation || [0,0,0,1]),
      new Vector3().fromArray(node.scale || [1,1,1]));
    const world=new Matrix4().multiplyMatrices(parent,local);
    if(node.mesh!==undefined && !ignored.has(node.mesh)) {
      for(const primitive of doc.meshes[node.mesh].primitives) {
        const accessor=doc.accessors[primitive.attributes.POSITION];
        if(!accessor.min || !accessor.max) throw new Error('Missing measured mesh bounds');
        complete.union(new Box3(new Vector3().fromArray(accessor.min),new Vector3().fromArray(accessor.max)).applyMatrix4(world));
      }
    }
    for(const child of node.children || []) visit(child,world);
  }
  for(const index of doc.scenes[doc.scene || 0].nodes) visit(index,new Matrix4());
  return {min:complete.min.toArray(),max:complete.max.toArray(),size:complete.getSize(new Vector3()).toArray(),center:complete.getCenter(new Vector3()).toArray()};
}

const shell=await bounds('src/demo/static/models/porsche-911-carrera-4s.glb',new Set([12]));
const systems=await bounds('src/demo/static/models/porsche-9922-systems.glb');
const scale=systems.size.map((size,i)=>size/shell.size[i]);
const position=systems.center.map((center,i)=>center-shell.center[i]*scale[i]);
console.log(JSON.stringify({shell,systems,transform:{scale,position},disclaimer:'Visual registration only; exterior model year and part geometry are unverified.'},null,2));
