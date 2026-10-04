import {Box3, Vector3} from 'three';

export function validateManifest(manifest, meshCount) {
  if (!manifest || !Array.isArray(manifest.components) || manifest.mesh_count !== meshCount) throw new Error('Model manifest does not match the asset.');
  const seen = new Set(), ids = new Set();
  for (const item of manifest.ignored_meshes || []) {
    if (!Number.isInteger(item.index) || item.index < 0 || item.index >= meshCount || seen.has(item.index) || !item.reason) throw new Error('Invalid ignored mesh.');
    seen.add(item.index);
  }
  for (const c of manifest.components) {
    if (!c.id || ids.has(c.id) || !c.mesh_indices?.length) throw new Error('Invalid component identity.');
    ids.add(c.id);
    for (const i of c.mesh_indices) {
      if (!Number.isInteger(i) || i < 0 || i >= meshCount || seen.has(i)) throw new Error('Duplicate or invalid mesh assignment.');
      seen.add(i);
    }
  }
  if (seen.size !== meshCount) throw new Error('Unassigned geometry in model.');
  return true;
}

export function projectedExtent(box, right, up) {
  let minX=Infinity, maxX=-Infinity, minY=Infinity, maxY=-Infinity;
  for (const x of [box.min.x,box.max.x]) for (const y of [box.min.y,box.max.y]) for (const z of [box.min.z,box.max.z]) {
    const p=new Vector3(x,y,z), px=p.dot(right), py=p.dot(up);
    minX=Math.min(minX,px); maxX=Math.max(maxX,px); minY=Math.min(minY,py); maxY=Math.max(maxY,py);
  }
  return {minX,maxX,minY,maxY,width:maxX-minX,height:maxY-minY};
}

// Fixed camera basis, actual world bounds, no scaling of individual pieces.
export function packGroups(items, right, up, aspect) {
  const extents=items.map(item=>({...item, ...projectedExtent(item.box,right,up)}));
  const gap=Math.max(...extents.map(e=>Math.max(e.width,e.height)))*.12;
  const columns=aspect < 1 ? 2 : 3;
  const rows=[];
  for(let i=0;i<extents.length;i+=columns) rows.push(extents.slice(i,i+columns));
  const totalHeight=rows.reduce((n,row)=>n+Math.max(...row.map(e=>e.height))+gap,0)-gap;
  const placements=[]; let top=totalHeight/2;
  for(const row of rows) {
    const height=Math.max(...row.map(e=>e.height));
    const width=row.reduce((n,e)=>n+e.width+gap,0)-gap; let left=-width/2;
    for(const e of row) {
      const dx=left+e.width/2-(e.minX+e.maxX)/2, dy=top-height/2-(e.minY+e.maxY)/2;
      placements.push({id:e.id, delta:right.clone().multiplyScalar(dx).addScaledVector(up,dy)});
      left+=e.width+gap;
    }
    top-=height+gap;
  }
  return placements;
}

// Pack each imported surface at its original scale, using actual projected bounds.
// A surface is an artist-authored mesh, not a validated vehicle part.
export function packSurfaceInventory(items, right, up, aspect) {
  if (!Array.isArray(items) || !Number.isFinite(aspect) || aspect <= 0) throw new Error('Invalid surface inventory.');
  const ids=new Set();
  const entries=items.map(item=>{
    if(typeof item.id!=='string' || !item.id || ids.has(item.id))throw new Error('Duplicate or invalid source surface.');
    ids.add(item.id);
    const bounds=projectedExtent(item.box,right,up);
    return {...item,...bounds,width:Math.max(.015,bounds.width),height:Math.max(.015,bounds.height)};
  }).sort((a,b)=>b.height-a.height||b.width-a.width||a.id.localeCompare(b.id));
  if(!entries.length)return [];
  const gap=Math.max(.06,Math.max(...entries.map(e=>Math.max(e.width,e.height)))*.025);
  const area=entries.reduce((sum,e)=>sum+(e.width+gap)*(e.height+gap),0);
  const target=Math.max(...entries.map(e=>e.width),Math.sqrt(area*aspect));
  let x=0,y=0,rowHeight=0,totalWidth=0;
  const placed=[];
  for(const entry of entries){
    if(x && x+entry.width>target){x=0;y+=rowHeight+gap;rowHeight=0;}
    placed.push({...entry,x:x+entry.width/2,y:y+entry.height/2});
    x+=entry.width+gap;totalWidth=Math.max(totalWidth,x-gap);rowHeight=Math.max(rowHeight,entry.height);
  }
  const totalHeight=y+rowHeight;
  return placed.map(entry=>({id:entry.id,delta:right.clone().multiplyScalar(entry.x-totalWidth/2-(entry.minX+entry.maxX)/2).addScaledVector(up,totalHeight/2-entry.y-(entry.minY+entry.maxY)/2)}));
}

export function unionBounds(meshes) {
  const bounds=new Box3();
  for(const mesh of meshes) if(mesh.visible) bounds.union(new Box3().setFromObject(mesh));
  if(bounds.isEmpty()) throw new Error('No visible geometry. Restore the vehicle to continue.');
  return bounds;
}

export function validAction(action, ids) {
  if(!action || Object.keys(action).some(k=>!['operation','component_id','value'].includes(k))) return false;
  const {operation,component_id,value}=action;
  if(['select','isolate','trace','hide','show'].includes(operation)) return ids.includes(component_id) && value===undefined;
  if(component_id!==undefined) return false;
  if(['reset','peel','separate','tour'].includes(operation)) return value===undefined;
  if(operation==='render') return ['solid','xray','systems','wire'].includes(value);
  if(operation==='camera') return ['perspective','top','side','front','rear'].includes(value);
  if(operation==='explode') return Number.isFinite(value) && value>=0 && value<=1;
  return false;
}

export function explodeOffset(direction,amount) {
  if(!Array.isArray(direction) || direction.length!==3 || direction.some(v=>!Number.isFinite(v)) || !Number.isFinite(amount) || amount<0 || amount>1) throw new Error('Invalid exploded pose');
  return new Vector3(...direction).multiplyScalar(amount);
}
