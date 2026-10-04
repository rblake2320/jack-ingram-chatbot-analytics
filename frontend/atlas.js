import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {DRACOLoader} from 'three/addons/loaders/DRACOLoader.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {validateManifest,packGroups,projectedExtent,unionBounds,validAction,explodeOffset} from './atlas-core.mjs';
import {renderRecallCards} from './recall-ui.mjs';

const $=id=>document.getElementById(id);
const viewport=$('viewport'), status=$('model-status');
let manifest, renderer, scene, camera, controls, model, selected=null, mode='assembled';
let frames=0, started=performance.now(), renderPending=false, busy=false;
const groups=new Map(), originals=new Map(), materials=new Map(), raycaster=new THREE.Raycaster();
const normal=new THREE.Vector3(5,3,6).normalize();
const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),normal).normalize();
const up=new THREE.Vector3().crossVectors(normal,right).normalize();
let lastDown=null, selectionBox;
let rendering='solid', explosion=0, motion=null, cameraView='perspective', rotating=false, tracing=false, showLabels=true;
let tourStarted=null, tourStep=-1, lastFrame=performance.now(), leaf=null;
const displayMaterials=new Map(), restWorld=new Map(), labels=new Map(), hidden=new Set();
let connections, vehicleBounds, cameraMotion=null;
const palette={body:'#d52330','front-wheels':'#007b83','rear-wheels':'#375fa3',glass:'#7896c8','front-fascia':'#b66a16',details:'#7961a6',underbody:'#4e7855'};
const directions={body:[0,.85,0],'front-wheels':[0,-.25,1.6],'rear-wheels':[0,-.25,-1.6],glass:[0,1.85,0],'front-fascia':[0,.25,2.75],details:[2.1,.3,0],underbody:[0,-1.2,0]};
const related={body:['glass','front-fascia','underbody'],glass:['body','details'],'front-wheels':['rear-wheels','underbody'],'rear-wheels':['front-wheels','underbody'],'front-fascia':['body','details'],details:['body','glass'],underbody:['body','front-wheels','rear-wheels']};
const isShell=id=>manifest.components.find(c=>c.id===id)?.system==='BODY' || ['body','glass'].includes(id);

function fail(error) {
  status.textContent=`3D unavailable: ${error.message}. Reload to retry.`;
  viewport.dataset.ready='false';
  motion=cameraMotion=null; rotating=false; stopTour();
  document.querySelectorAll('button, input').forEach(b=>b.disabled=true);
  $('model-metrics').textContent='Model did not finish loading.';
}

function draw() {
  if(!renderer || renderPending) return;
  renderPending=true;
  requestAnimationFrame(now=>{
    renderPending=false;
    tick(now);
    if(selectionBox && selected) selectionBox.box.copy(unionBounds(groups.get(selected)));
    renderer.render(scene,camera); frames++;
    const visible=[...groups.values()].flat().filter(m=>m.visible).length;
    $('model-metrics').textContent=`${visible}/${manifest.mesh_count-manifest.ignored_meshes.length} vehicle meshes visible · ${renderer.info.render.triangles.toLocaleString()} rendered triangles · ${renderer.info.render.calls} draw calls`;
    viewport.dataset.visibleMeshes=String(visible);
    viewport.dataset.drawCalls=String(renderer.info.render.calls);
    viewport.dataset.frames=String(frames);
    viewport.dataset.explosion=explosion.toFixed(4);
    viewport.dataset.renderMode=rendering;
    viewport.dataset.cameraView=cameraView;
    viewport.dataset.traceLines=String(connections?.children.length || 0);
    viewport.dataset.tourStep=String(tourStep);
    viewport.dataset.poseCenters=JSON.stringify([...groups].map(([id,meshes])=>{const box=new THREE.Box3();for(const mesh of meshes)box.union(new THREE.Box3().setFromObject(mesh));return{id,center:box.getCenter(new THREE.Vector3()).toArray()};}));
    positionLabels();
    if(motion || cameraMotion || rotating || tourStarted!==null) draw();
  });
}

function extentOf(box) {return projectedExtent(box,right,up);}
function fit(box, fixed=false, animate=false) {
  const center=box.getCenter(new THREE.Vector3());
  const aspect=viewport.clientWidth/viewport.clientHeight;
  let size, direction;
  const nextUp=new THREE.Vector3(0,1,0);
  if(fixed) {
    const e=extentOf(box); size=Math.max(e.height,e.width/aspect)*.62;
    controls.enableRotate=false;
    nextUp.copy(up); direction=normal.clone();
  } else {
    const views={perspective:[5,2.7,6],top:[0,1,.001],side:[1,.09,0],front:[0,.1,1],rear:[0,.1,-1]};
    direction=new THREE.Vector3(...views[cameraView]).normalize();
    const r=new THREE.Vector3().crossVectors(nextUp,direction).normalize(), u=new THREE.Vector3().crossVectors(direction,r).normalize();
    const e=projectedExtent(box,r,u); size=Math.max(e.height,e.width/aspect)*.61;
    controls.enableRotate=true;
  }
  size=Math.max(size,.05);
  const position=center.clone().addScaledVector(direction,box.getSize(new THREE.Vector3()).length()*2+10);
  if(animate && !matchMedia('(prefers-reduced-motion: reduce)').matches) cameraMotion={started:performance.now(),from:camera.position.clone(),to:position,fromTarget:controls.target.clone(),target:center,fromUp:camera.up.clone(),up:nextUp,fromSize:camera.top/camera.zoom,size,aspect};
  else {cameraMotion=null; camera.position.copy(position); camera.up.copy(nextUp); controls.target.copy(center); camera.left=-size*aspect; camera.right=size*aspect; camera.top=size; camera.bottom=-size;}
  camera.near=.01; camera.far=1000; camera.zoom=1; camera.updateProjectionMatrix();
  controls.update(); draw();
}

function ease(t){return t*t*(3-2*t);}
function tick(now){
  const dt=Math.min((now-lastFrame)/1000,.05); lastFrame=now;
  if(tourStarted!==null) advanceTour(now);
  if(motion){const t=Math.min((now-motion.started)/900,1); pose(motion.from+(motion.to-motion.from)*ease(t)); if(t===1) motion=null;}
  if(cameraMotion){const m=cameraMotion,t=Math.min((now-m.started)/800,1),e=ease(t),size=THREE.MathUtils.lerp(m.fromSize,m.size,e);camera.position.lerpVectors(m.from,m.to,e);camera.up.lerpVectors(m.fromUp,m.up,e).normalize();controls.target.lerpVectors(m.fromTarget,m.target,e);camera.top=size;camera.bottom=-size;camera.left=-size*m.aspect;camera.right=size*m.aspect;camera.updateProjectionMatrix();controls.update();if(t===1)cameraMotion=null;}
  if(rotating && !cameraMotion){const offset=camera.position.clone().sub(controls.target);offset.applyAxisAngle(new THREE.Vector3(0,1,0),dt*.22);camera.position.copy(controls.target).add(offset);controls.update();}
}

function pose(amount){
  explosion=amount;
  for(const [id,meshes] of groups) for(const mesh of meshes){const p=restWorld.get(mesh).clone().add(explodeOffset(directions[id],amount));mesh.position.copy(mesh.parent.worldToLocal(p));}
  model.updateMatrixWorld(true);
  $('explode').value=String(Math.round(amount*100));$('explode-value').textContent=Math.round(amount*100)+'%';
  updateConnections();
}
function explodedBounds(){
  const result=new THREE.Box3();
  for(const [id,meshes] of groups) for(const mesh of meshes){const box=new THREE.Box3().setFromObject(mesh);box.translate(explodeOffset(directions[id],1-explosion));result.union(box);}
  return result;
}
function explodeTo(amount,animate=true){
  if(mode==='separate' || mode==='isolated'){restoreTransforms();hidden.clear();for(const meshes of groups.values())for(const mesh of meshes)mesh.visible=true;pose(0);}
  mode='exploded';leaf=null;viewport.dataset.mode=mode;controls.enableRotate=true;
  if(animate && !matchMedia('(prefers-reduced-motion: reduce)').matches)motion={from:explosion,to:amount,started:performance.now()};else{motion=null;pose(amount);}
  fit(amount>0 ? explodedBounds() : vehicleBounds,false,true);
  $('view-state').textContent='Spatial exploded view · drag to orbit · slide to reassemble';
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed','false'));updateList();draw();
}
function appearance(){
  for(const [mesh,original] of materials){const mat=displayMaterials.get(mesh),id=mesh.userData.componentId,active=id===selected && (!leaf || leaf===mesh);
    mat.color?.copy(original.color);mat.emissive?.copy(original.emissive);mat.opacity=original.opacity;mat.transparent=original.transparent;mat.depthWrite=original.depthWrite;mat.wireframe=rendering==='wire';
    if(rendering==='systems')mat.color?.set(palette[id]);
    if(rendering==='xray' && !active && isShell(id)){mat.transparent=true;mat.opacity=.12;mat.depthWrite=false;}
    if(active){mat.emissive?.set(0x60151c);if(!mat.emissive)mat.color?.set(palette[id]);}
    mat.needsUpdate=true;mesh.material=mat;
  }
  document.querySelectorAll('[data-render]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.render===rendering)));
  draw();
}
function renderMode(next){rendering=next;appearance();$('view-state').textContent={solid:'Exterior · select a part to explore',xray:'X-ray · transparent body reveals supplied surfaces',systems:'Systems · colors identify component groups',wire:'Wireframe · inspect the actual surface geometry'}[next];}
function setCamera(view){if(mode==='separate')setMode('assembled');cameraView=view;rotating=false;$('rotate').setAttribute('aria-pressed','false');document.querySelectorAll('[data-camera]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.camera===view)));fit(unionBounds(currentMeshes()),false,true);}
function updateConnections(){
  if(!connections)return;
  for(const line of [...connections.children]){line.geometry.dispose();line.material.dispose();connections.remove(line);}
  if(!tracing || !selected || mode==='isolated' || leaf)return;
  const center=id=>new THREE.Box3().union(unionBounds(groups.get(id).filter(m=>m.visible))).getCenter(new THREE.Vector3());
  if(!groups.get(selected).some(m=>m.visible))return;
  for(const id of (related[selected] || []).filter(id=>groups.get(id)?.some(m=>m.visible))){const a=center(selected),b=center(id),mid=a.clone().lerp(b,.5).add(new THREE.Vector3(0,.4,0));const curve=new THREE.QuadraticBezierCurve3(a,mid,b);const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(32)),new THREE.LineDashedMaterial({color:0xd52330,dashSize:.08,gapSize:.05,depthTest:false,transparent:true,opacity:.85}));line.computeLineDistances();line.renderOrder=5;connections.add(line);}
}
function positionLabels(){
  const w=viewport.clientWidth,h=viewport.clientHeight;
  const occupied=[];
  for(const [id,label] of [...labels].sort(([a],[b])=>Number(b===selected)-Number(a===selected))){const meshes=groups.get(id).filter(m=>m.visible);label.hidden=!showLabels || !meshes.length || (explosion<.1 && selected!==id && rendering!=='systems') || !!leaf;if(label.hidden)continue;const p=unionBounds(meshes).getCenter(new THREE.Vector3()).project(camera);label.hidden=p.z<-1||p.z>1||Math.abs(p.x)>1||Math.abs(p.y)>1;if(!label.hidden){const width=label.offsetWidth || 150,x=Math.max(width/2+4,Math.min(w-width/2-4,(p.x*.5+.5)*w)),y=Math.max(48,Math.min(h-48,(-p.y*.5+.5)*h));const box={left:x-width/2,right:x+width/2,top:y-16,bottom:y+16};if(occupied.some(b=>box.left<b.right+6 && box.right>b.left-6 && box.top<b.bottom+4 && box.bottom>b.top-4)){label.hidden=true;continue;}occupied.push(box);label.style.left=x+'px';label.style.top=y+'px';label.setAttribute('aria-pressed',String(selected===id));}}
  viewport.dataset.visibleLabels=String(occupied.length);
}
function stopTour(){tourStarted=null;tourStep=-1;if($('tour')){$('tour').textContent='▶ Play guided tour';$('tour-caption').hidden=true;}draw();}
let tour=[
  {at:0,title:'01 / Explore the exterior',text:'Rotate the car, then take it apart. Every selectable piece comes from the credited 3D asset.',run:()=>{setMode('assembled');rotating=true;}},
  {at:3.5,title:'02 / See beneath the body',text:'X-ray fades the shell so the supplied supporting geometry becomes visible.',run:()=>{renderMode('xray');select('front-wheels');}},
  {at:7,title:'03 / Understand the groups',text:'Component colors and relationship lines help you follow the model. Lines describe group associations.',run:()=>{renderMode('systems');tracing=true;$('trace').setAttribute('aria-pressed','true');updateConnections();}},
  {at:10.5,title:'04 / Take it apart',text:'The continuous exploded view moves the real mesh groups out of the assembled car. Drag to inspect from any angle.',run:()=>{rotating=false;cameraView='perspective';explodeTo(1);}},
  {at:15,title:'05 / Inspect actual surfaces',text:'Select wheels, glazing or body panels. The inspector exposes the source material surfaces for each group.',run:()=>{select('rear-wheels');renderMode('solid');}},
  {at:19,title:'06 / Put it back together',text:'Reassembly restores every piece to its original position. Use the slider and controls to explore for yourself.',run:()=>{tracing=false;updateConnections();explodeTo(0);}},
];
function startTour(){stopTour();tourStarted=performance.now();tourStep=-1;$('tour').textContent='■ Stop tour';draw();}
function advanceTour(now){const seconds=(now-tourStarted)/1000;const index=tour.findLastIndex(step=>seconds>=step.at);if(index!==tourStep){tourStep=index;const step=tour[index];step.run();$('tour-caption').replaceChildren();const b=document.createElement('b');b.textContent=step.title;$('tour-caption').append(b,document.createTextNode(step.text));$('tour-caption').hidden=false;}
  if(seconds>23){stopTour();setMode('assembled');status.textContent='Tour complete · explore the model with the controls.';}
}

function currentMeshes() { return [...groups.values()].flat().filter(m=>m.visible); }
function restoreTransforms() {
  for(const [mesh,position] of originals) mesh.position.copy(position);
  model.updateMatrixWorld(true);
}

function separation() {
  restoreTransforms();
  for(const meshes of groups.values()) for(const mesh of meshes) mesh.visible=true;
  const boxes=[...groups].map(([id,meshes])=>({id,box:unionBounds(meshes)}));
  for(const p of packGroups(boxes,right,up,viewport.clientWidth/viewport.clientHeight)) {
    for(const mesh of groups.get(p.id)) {
      const world=mesh.getWorldPosition(new THREE.Vector3()).add(p.delta);
      mesh.position.copy(mesh.parent.worldToLocal(world));
    }
  }
  model.updateMatrixWorld(true);
  fit(unionBounds(currentMeshes()),true);
  camera.updateMatrixWorld(true);
  let fits=true;
  for(const meshes of groups.values()) {
    const b=unionBounds(meshes);
    for(const x of [b.min.x,b.max.x]) for(const y of [b.min.y,b.max.y]) for(const z of [b.min.z,b.max.z]) {
      const p=new THREE.Vector3(x,y,z).project(camera);
      if(Math.abs(p.x)>1.001 || Math.abs(p.y)>1.001) fits=false;
    }
  }
  viewport.dataset.packingFits=String(fits);
  if(!fits) throw new Error('Separated parts do not fit the usable canvas.');
  // Verify applied world transforms, rather than trusting the packing function.
  const extents=[...groups].map(([id,meshes])=>({id,...extentOf(unionBounds(meshes))}));
  let overlaps=0;
  for(let a=0;a<extents.length;a++) for(let b=a+1;b<extents.length;b++) {
    const x=extents[a],y=extents[b];
    if(x.minX<y.maxX-1e-5 && y.minX<x.maxX-1e-5 && x.minY<y.maxY-1e-5 && y.minY<x.maxY-1e-5) overlaps++;
  }
  if(overlaps) throw new Error('Separated geometry overlaps; restore the vehicle.');
  viewport.dataset.packingOverlaps=String(overlaps);
  $('view-state').textContent='Separated parts · drag to pan · scroll to zoom';
}

function setMode(next) {
  motion=cameraMotion=null;leaf=null;hidden.clear();
  mode=next;
  explosion=0;$('explode').value='0';$('explode-value').textContent='0%';
  if(next==='separate') {rotating=false;$('rotate').setAttribute('aria-pressed','false');separation();}
  else {
    restoreTransforms();
    for(const [id,meshes] of groups) for(const mesh of meshes) mesh.visible=next!=='peel' || !isShell(id);
    if(next==='assembled') {selected=null;rendering='solid';cameraView='perspective';rotating=tracing=false;$('rotate').setAttribute('aria-pressed','false');$('trace').setAttribute('aria-pressed','false');clearHighlight(); $('surface-inspector').hidden=true;$('component-evidence').hidden=true;delete viewport.dataset.selectedMesh; $('selection-title').textContent='Choose a component'; $('selection-description').textContent='Click a part of the car or choose from the list. Ask the assistant to show or isolate it.'; $('selection-question').textContent=''; $('part-search').value=''; $('search-status').textContent=''; for(const b of $('parts').querySelectorAll('[data-component], details')) b.hidden=false;}
    fit(unionBounds(currentMeshes()));
    $('view-state').textContent=next==='peel' ? 'Body panels hidden · supplied surfaces only' : 'Assembled · drag to rotate · scroll to zoom';
  }
  viewport.dataset.mode=mode;
  $('isolate').setAttribute('aria-pressed','false');
  document.querySelectorAll('[data-camera]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.camera===cameraView)));
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===mode)));
  appearance();updateConnections();updateList(); draw();
}

function clearHighlight() {
  if(selectionBox) {scene.remove(selectionBox); selectionBox.geometry.dispose(); selectionBox.material.dispose(); selectionBox=null;}
  appearance();
  viewport.dataset.selected=selected || '';
}

function updateList() {
  for(const button of $('parts').querySelectorAll('[data-component]')) {
    button.setAttribute('aria-pressed',String(button.dataset.component===selected));
    const visible=groups.get(button.dataset.component).some(m=>m.visible);
    button.querySelector('small').textContent=visible ? 'Visible' : 'Hidden';
  }
}

function select(id, focus=false) {
  if(!groups.has(id)) throw new Error('Unknown component.');
  if(mode==='peel' && isShell(id)) setMode('assembled');
  if(mode==='isolated') for(const [other,meshes] of groups) for(const mesh of meshes) mesh.visible=other===id;
  leaf=null;selected=id; clearHighlight();hidden.delete(id);
  const meshes=groups.get(id);
  for(const m of meshes) m.visible=true;
  const c=manifest.components.find(c=>c.id===id);
  $('selection-title').textContent=c.label;
  $('selection-description').textContent=c.description;
  $('selection-question').textContent=c.question;
  $('parts').querySelector(`[data-component="${id}"]`)?.closest('details')?.setAttribute('open','');
  $('component-evidence').hidden=!c.geometry_grade;
  if(c.geometry_grade){$('component-grade').textContent=`Identity: ${c.identity_grade}. Geometry: ${c.geometry_grade}. Placement: ${c.placement_grade}.`;$('component-sources').replaceChildren();for(const source of manifest.sources.filter(s=>c.source_ids.includes(s.id))){const a=document.createElement('a');a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=source.title+' ↗';const p=document.createElement('p');p.textContent=source.scope;$('component-sources').append(a,p);}}
  $('surface-inspector').hidden=false;$('source-surfaces').replaceChildren();
  for(const mesh of meshes){const button=document.createElement('button');button.type='button';button.textContent=`${materials.get(mesh).name || 'Surface'} · source mesh ${mesh.userData.meshIndex}`;button.addEventListener('click',()=>{stopTour();motion=null;rotating=false;leaf=mesh;for(const other of originals.keys())other.visible=other===mesh;mode='isolated';viewport.dataset.mode=mode;viewport.dataset.selectedMesh=String(mesh.userData.meshIndex);appearance();updateConnections();updateList();fit(new THREE.Box3().setFromObject(mesh),false,true);$('view-state').textContent=`Source surface: ${materials.get(mesh).name} · reassemble to restore all parts`;});$('source-surfaces').append(button);}
  viewport.dataset.selected=id;
  if(mode==='isolated') $('view-state').textContent='Isolated · '+c.label;
  appearance();updateConnections();updateList();
  if(focus) fit(unionBounds(meshes),mode==='separate',true);
  draw();
}

function isolate() {
  if(!selected) {status.textContent='Choose a component first.'; return;}
  if(mode==='isolated'){const id=selected;setMode('assembled');select(id);return;}
  motion=null;rotating=false;
  for(const [id,meshes] of groups) for(const m of meshes) m.visible=id===selected;
  mode='isolated'; viewport.dataset.mode=mode;
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed','false'));
  $('view-state').textContent='Isolated · '+manifest.components.find(c=>c.id===selected).label;
  select(selected,true);
  $('isolate').setAttribute('aria-pressed','true');updateConnections();
}

function apply(action) {
  if(!validAction(action,manifest.components.map(c=>c.id))) throw new Error('The assistant returned an unsupported viewer action.');
  stopTour();
  if(action.operation==='select' || action.operation==='isolate' || action.operation==='trace') {
    select(action.component_id);
    if(action.operation==='isolate') isolate();
    if(action.operation==='trace'){tracing=true;$('trace').setAttribute('aria-pressed','true');updateConnections();}
  } else if(action.operation==='render')renderMode(action.value);
  else if(action.operation==='camera')setCamera(action.value);
  else if(action.operation==='explode')explodeTo(action.value);
  else if(action.operation==='tour')startTour();
  else if(action.operation==='hide' || action.operation==='show'){for(const mesh of groups.get(action.component_id))mesh.visible=action.operation==='show';if(action.operation==='hide')hidden.add(action.component_id);else hidden.delete(action.component_id);if(!currentMeshes().length)setMode('assembled');updateList();updateConnections();draw();}
  else setMode(action.operation==='reset' ? 'assembled' : action.operation);
  status.textContent='Viewer updated · '+(action.component_id ? $('selection-title').textContent : $('view-state').textContent);
}

function addReply(text,role) {
  const p=document.createElement('p'); p.className='atlas-message '+role; p.textContent=text;
  $('atlas-messages').append(p); $('atlas-messages').scrollTop=$('atlas-messages').scrollHeight;
}
async function ask(message) {
  if(busy || !message.trim() || !manifest || !model) return;
  busy=true; $('atlas-send').disabled=true; $('atlas-question').value=''; addReply(message,'user');
  $('assistant-status').textContent='Preparing your answer…';
  try {
    const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,analytics_consent:false,vehicle_context:{vehicle_id:manifest.id,component_id:selected}}),signal:AbortSignal.timeout(25000)});
    const data=await response.json();
    if(!response.ok || typeof data.response!=='string' || !data.response.trim()) throw new Error(data.response || 'The assistant is unavailable. Try again.');
    addReply(data.response,'assistant');
    if(data.recall_cards){renderRecallCards($('recall-results'),data.recall_cards,showRecall);$('recall-status').textContent=data.recall_status+' · model-level result; confirm VIN';$('recall-panel').open=true;$('recall-panel').scrollIntoView({block:'nearest'});}
    if(data.explorer_action) apply(data.explorer_action);
  } catch(error) {addReply(error.message,'error');}
  finally {busy=false; $('atlas-send').disabled=false; $('assistant-status').textContent='';}
}

function showRecall(card){
  if(!groups.has(card.component_id)){status.textContent='This exterior reference does not model the affected system. Open the 2026 systems reconstruction to see its representative region.';return;}
  stopTour();setMode('assembled');renderMode('xray');select(card.component_id);setCamera(card.component_id==='rear-camera'?'rear':'front');tracing=true;updateConnections();
  $('recall-status').textContent=card.campaign+' · '+card.model_scope+(card.geometry_scope?' '+card.geometry_scope:'');
  viewport.dataset.recallCampaign=card.campaign;
  $('view-state').textContent=card.campaign+' · '+card.year+' notice · 2026 representative system region';
}
async function loadRecalls(campaign){
  $('recall-status').textContent='Checking official NHTSA model-year records…';$('recall-submit').disabled=true;
  try{const r=await fetch('/api/recalls?'+new URLSearchParams({vehicle:$('recall-vehicle').value,year:$('recall-year').value}),{signal:AbortSignal.timeout(20000)});if(!r.ok)throw new Error('Recall lookup unavailable. Retry or check NHTSA directly.');const data=await r.json();
    $('recall-status').textContent=data.status==='unavailable'?data.error:`${data.cards.length} model-level campaigns · ${data.status==='live'?'live official response':'saved official response; live lookup failed'} · checked ${data.checked_at}. Confirm your VIN.`;
    const cards=campaign?[...data.cards].sort((a,b)=>Number(b.campaign===campaign)-Number(a.campaign===campaign)):data.cards;renderRecallCards($('recall-results'),cards,showRecall);if(campaign){const c=data.cards.find(c=>c.campaign===campaign);if(c)showRecall(c);else $('recall-status').textContent+=' Requested campaign was not returned for this vehicle/year.';}
  }catch(e){$('recall-status').textContent=e.message;}finally{$('recall-submit').disabled=false;}
}

async function init() {
  const systems=new URLSearchParams(location.search).get('subject')==='systems';
  const manifestResponse=await fetch('/api/vehicle-atlas'+(systems?'?subject=systems':''));
  if(!manifestResponse.ok) throw new Error('Model manifest unavailable.');
  manifest=await manifestResponse.json(); validateManifest(manifest,manifest.mesh_count);
  for(const c of manifest.components){palette[c.id]=c.color || palette[c.id];directions[c.id]=c.explode || directions[c.id];related[c.id]=c.related || related[c.id] || [];}
  if(systems){tour=[
    {at:0,title:'01 / A 2026 systems reconstruction',text:'Public specifications constrain this original explanatory model. Shapes and placement are representative.',run:()=>{setMode('assembled');rotating=!matchMedia('(prefers-reduced-motion: reduce)').matches;}},
    {at:3.5,title:'02 / The rear-mounted boxer',text:'Transparent panels reveal the opposed six-cylinder engine and two turbocharger regions.',run:()=>{rotating=false;renderMode('xray');select('engine');}},
    {at:7,title:'03 / Follow the power path',text:'Eight-speed PDK feeds the rear axle and the front PTM connection. Trace curves explain functional links.',run:()=>{renderMode('systems');select('pdk');tracing=true;$('trace').setAttribute('aria-pressed','true');updateConnections();}},
    {at:10.5,title:'04 / Explore the assemblies',text:'Separate body, engine, drivetrain, brakes and cabin using the continuous exploded-view slider.',run:()=>{cameraView='perspective';explodeTo(1);}},
    {at:15,title:'05 / Inspect wheels and brakes',text:'The 408 mm front steel rotor and 20-inch wheel envelope have public specification sources in the inspector.',run:()=>{select('front-left-brake');renderMode('systems');}},
    {at:19,title:'06 / Restore the complete model',text:'Reassembly restores every component to its starting position. Search a part, isolate it, or ask the assistant.',run:()=>{tracing=false;updateConnections();explodeTo(0);}}
  ];}
  const assetResponse=await fetch(manifest.asset_url);
  if(!assetResponse.ok) throw new Error('Vehicle asset unavailable.');
  const bytes=await assetResponse.arrayBuffer();
  if(bytes.byteLength!==manifest.bytes) throw new Error('Vehicle asset was truncated.');
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  const hash=Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join('');
  if(hash!==manifest.sha256) throw new Error('Vehicle asset integrity check failed.');
  renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,2)); renderer.setSize(viewport.clientWidth,viewport.clientHeight);
  renderer.outputColorSpace=THREE.SRGBColorSpace; renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=1.1;
  renderer.domElement.setAttribute('aria-label','Interactive Porsche 911 Carrera 4S model. Use the named component buttons for keyboard selection.');
  viewport.append(renderer.domElement);
  renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();fail(new Error('Graphics context lost'));});
  scene=new THREE.Scene(); scene.background=new THREE.Color(0xf0efed);
  connections=new THREE.Group();scene.add(connections);
  const pmrem=new THREE.PMREMGenerator(renderer), environment=new RoomEnvironment();
  scene.environment=pmrem.fromScene(environment,.04).texture; environment.dispose(); pmrem.dispose();
  camera=new THREE.OrthographicCamera(-5,5,5,-5,.01,1000);
  controls=new OrbitControls(camera,renderer.domElement); controls.addEventListener('change',draw);
  controls.minZoom=.2; controls.maxZoom=12; controls.enableDamping=false;
  const failedAssets=[];
  const manager=new THREE.LoadingManager(); manager.onError=url=>failedAssets.push(url);
  // JS decoder keeps CSP free of eval/WASM exceptions. Pin this compatibility API until a tested migration.
  const draco=new DRACOLoader(manager).setDecoderPath('/static/atlas/draco/').setDecoderConfig({type:'js'}).setWorkerLimit(2);
  const loader=new GLTFLoader(manager).setDRACOLoader(draco);
  let gltf;
  try {gltf=await loader.parseAsync(bytes,'/static/models/');} finally {draco.dispose();}
  if(failedAssets.length) throw new Error('An embedded texture or decoder failed to load');
  validateManifest(manifest,gltf.parser.json.meshes.length);
  model=gltf.scene; scene.add(model); model.updateMatrixWorld(true);
  const owners=new Map(); for(const c of manifest.components) {groups.set(c.id,[]); for(const i of c.mesh_indices) owners.set(i,c.id);}
  const seen=new Set();
  const ignored=new Set(manifest.ignored_meshes.map(m=>m.index));
  model.traverse(obj=>{
    if(!obj.isMesh) return;
    const index=gltf.parser.associations.get(obj)?.meshes;
    if(!Number.isInteger(index) || (!owners.has(index) && !ignored.has(index)) || seen.has(index)) throw new Error('Loaded geometry identity mismatch.');
    if(ignored.has(index)) {seen.add(index); obj.visible=false; return;}
    seen.add(index); obj.userData.componentId=owners.get(index); groups.get(owners.get(index)).push(obj);
    obj.userData.meshIndex=index;
    originals.set(obj,obj.position.clone()); materials.set(obj,obj.material);
    displayMaterials.set(obj,obj.material.clone());restWorld.set(obj,obj.getWorldPosition(new THREE.Vector3()));
  });
  if(seen.size!==manifest.mesh_count) throw new Error('The model has missing geometry.');
  vehicleBounds=unionBounds(currentMeshes()).clone();
  const directories=new Map();
  for(const c of manifest.components) {
    const button=document.createElement('button'); button.type='button'; button.dataset.component=c.id;
    button.setAttribute('aria-pressed','false'); button.textContent=c.label;
    button.style.setProperty('--component-color',palette[c.id]);
    const small=document.createElement('small'); small.textContent='Visible'; button.append(small);
    button.addEventListener('click',()=>{stopTour();select(c.id);});
    if(c.system){if(!directories.has(c.system)){const d=document.createElement('details'),summary=document.createElement('summary');summary.textContent=c.system_label;d.append(summary);$('parts').append(d);directories.set(c.system,d);}directories.get(c.system).append(button);}else $('parts').append(button);
    const label=document.createElement('button');label.className='part-label';label.textContent=c.label;label.type='button';label.setAttribute('aria-label','Select '+c.label+' in 3D');label.addEventListener('click',()=>{stopTour();select(c.id);});$('part-labels').append(label);labels.set(c.id,label);
  }
  $('part-search').addEventListener('input',e=>{
    const q=e.target.value.toLowerCase(); let count=0;
    for(const b of $('parts').querySelectorAll('[data-component]')) {b.hidden=!b.textContent.toLowerCase().includes(q); if(!b.hidden) count++;}
    for(const d of directories.values()){d.hidden=![...d.querySelectorAll('[data-component]')].some(b=>!b.hidden);d.open=!!q && !d.hidden;}
    $('search-status').textContent=count ? `${count} matching components` : 'No modeled component matches. Try engine, wheels or body.';
  });
  renderer.domElement.addEventListener('pointerdown',e=>{stopTour();cameraMotion=null;rotating=false;$('rotate').setAttribute('aria-pressed','false');lastDown={x:e.clientX,y:e.clientY};});
  renderer.domElement.addEventListener('pointerup',e=>{
    if(!lastDown || Math.hypot(e.clientX-lastDown.x,e.clientY-lastDown.y)>6) {lastDown=null;return;}
    lastDown=null; const rect=renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1),camera);
    const hit=raycaster.intersectObjects(currentMeshes(),false)[0]; if(hit) select(hit.object.userData.componentId);
  });
  document.querySelectorAll('[data-view]').forEach(button=>{button.disabled=false;button.addEventListener('click',()=>{stopTour();setMode(button.dataset.view);});});
  document.querySelectorAll('[data-render]').forEach(button=>{button.disabled=false;button.addEventListener('click',()=>{stopTour();renderMode(button.dataset.render);});});
  document.querySelectorAll('[data-camera]').forEach(button=>{button.disabled=false;button.addEventListener('click',()=>{stopTour();setCamera(button.dataset.camera);});});
  for(const id of ['tour','explode','rotate','reset-atlas','trace','labels'])$(id).disabled=false;
  $('explode').addEventListener('input',e=>{stopTour();explodeTo(Number(e.target.value)/100);});
  $('tour').addEventListener('click',()=>tourStarted===null?startTour():stopTour());
  $('rotate').addEventListener('click',()=>{stopTour();if(mode==='separate')setMode('assembled');rotating=!rotating;lastFrame=performance.now();$('rotate').setAttribute('aria-pressed',String(rotating));draw();});
  $('reset-atlas').addEventListener('click',()=>{stopTour();setMode('assembled');});
  $('trace').addEventListener('click',()=>{stopTour();if(!selected)select('body');tracing=!tracing;$('trace').setAttribute('aria-pressed',String(tracing));updateConnections();draw();});
  $('labels').addEventListener('click',()=>{showLabels=!showLabels;$('labels').setAttribute('aria-pressed',String(showLabels));draw();});
  document.querySelectorAll('[data-ask], #part-search, #atlas-question, #atlas-send').forEach(el=>el.disabled=false);
  $('focus').disabled=false; $('isolate').disabled=false;
  $('focus').addEventListener('click',()=>{stopTour();if(selected) fit(unionBounds(groups.get(selected)),mode==='separate',true);});
  $('isolate').addEventListener('click',()=>{stopTour();isolate();});
  $('atlas-form').addEventListener('submit',e=>{e.preventDefault();ask($('atlas-question').value);});
  document.querySelectorAll('[data-ask]').forEach(b=>b.addEventListener('click',()=>ask(b.dataset.ask)));
  $('forget-atlas').addEventListener('click',async()=>{
    if(busy) return;
    try {
      const r=await fetch('/api/privacy',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(!r.ok) throw new Error('Could not delete this conversation. Try again.');
      $('atlas-messages').replaceChildren(); addReply('Your conversation has been deleted. Select a component to continue.','assistant');
    } catch(e) {addReply(e.message,'error');}
  });
  new ResizeObserver(()=>{
    renderer.setSize(viewport.clientWidth,viewport.clientHeight);
    if(mode==='separate') separation(); else fit(unionBounds(currentMeshes()));
  }).observe(viewport);
  setMode('assembled');
  viewport.dataset.ready='true';
  $('recall-form').addEventListener('submit',e=>{e.preventDefault();loadRecalls();});
  $('recall-example').addEventListener('click',()=>{$('recall-vehicle').value='porsche-911';$('recall-year').value='2025';$('recall-panel').open=true;loadRecalls('25V896000');});
  const query=new URLSearchParams(location.search);if(query.has('recall')){$('recall-panel').open=true;$('recall-year').value=query.get('year') || '2026';loadRecalls(query.get('recall'));}
  status.textContent=`Ready · ${(bytes.byteLength/1e6).toFixed(2)} MB · loaded in ${((performance.now()-started)/1000).toFixed(1)}s · asset verified`;
}
init().catch(fail);
