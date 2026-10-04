// Original explanatory geometry. Public specifications constrain the envelope;
// internal shapes and positions are representative, never OEM CAD or VIN data.
import * as T from 'three';
import {GLTFExporter} from 'three/addons/exporters/GLTFExporter.js';
import {writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';

globalThis.FileReader=class {
  async readAsArrayBuffer(blob){this.result=await blob.arrayBuffer();this.onloadend?.();}
  async readAsDataURL(blob){this.result='data:'+blob.type+';base64,'+Buffer.from(await blob.arrayBuffer()).toString('base64');this.onloadend?.();}
};
const release='https://newsroom.porsche.com/en_US/2025/products/911-Carrera-4S-Cabriolet-Targa-2026-39921.html';
const dimensions='https://finder.porsche.com/lt/en-LT/details/porsche-911-carrera-4s-new-QVKM62';
const ptm='https://newsroom.porsche.com/en/innovation/engineering/porsche-traction-management-ptm-all-wheel-drive-agility-stability-traction-driving-dynamics-15050.html';
const wheels='https://static.nhtsa.gov/odi/tsbs/2026/MC-11033626-0001.pdf';
const body='https://newsroom.porsche.com/en/2019/technology/porsche-body-production-911-composite-design-technology-17111.html';
const sources=[
  {id:'my26',title:'Porsche MY2026 Carrera 4S announcement',url:release,publisher:'Porsche',checked_at:'2026-10-04',scope:'2026 non-hybrid Carrera 4S: engine, PDK, PTM, brakes, wheels and seating. Facts only; no media imported.'},
  {id:'envelope',title:'2026 Carrera 4S technical specifications',url:dimensions,publisher:'Porsche Finder',checked_at:'2026-10-04',scope:'Dimensions and engine figures; this European listing is not Jack Ingram stock.'},
  {id:'ptm',title:'Porsche Traction Management architecture',url:ptm,publisher:'Porsche',checked_at:'2026-10-04',scope:'General functional architecture; exact 992.2 routing and torque maps are not published here.'},
  {id:'wheels',title:'Porsche 11/26 wheel and tire certificate',url:wheels,publisher:'Porsche via NHTSA',page:1,checked_at:'2026-10-04',scope:'Non-hybrid 992PA 20/21-inch summer row. Wheel option and VIN still govern exact fitment.'},
  {id:'body',title:'Type 992 mixed-material body production',url:body,publisher:'Porsche',checked_at:'2026-10-04',scope:'2019 architecture reference. Geometry, material gauges and 2026 effectivity are not certified.'},
  {id:'rear-noise',title:'992.II rear drive shaft rattle · 2509',url:'https://static.nhtsa.gov/odi/tsbs/2025/MC-11016772-0001.pdf',publisher:'Porsche via NHTSA',page:1,checked_at:'2026-10-04',scope:'As of MY2025, listed model types; noise condition, not a stated loss of drivability. Applicability requires model/equipment checks.'},
  {id:'gpf',title:'Unapproved engine oil and GPF ash',url:'https://static.nhtsa.gov/odi/tsbs/2025/MC-11016770-0001.pdf',publisher:'Porsche via NHTSA',page:1,checked_at:'2026-10-04',scope:'992.II OPF-equipped cars as of MY2025. Explanatory context, not a diagnosis.'},
  {id:'recall-camera',title:'NHTSA 25V896000 / Porsche ASB2',url:'https://www.nhtsa.gov/recalls?nhtsaId=25V896000',publisher:'NHTSA',checked_at:'2026-10-04',scope:'Certain 2020–2025 911 vehicles; rear-view camera software recall. A 2026 illustration does not establish applicability.'},
  {id:'recall-lighting',title:'NHTSA 25V079000 / Porsche ASA1',url:'https://www.nhtsa.gov/recalls?nhtsaId=25V079000',publisher:'NHTSA',checked_at:'2026-10-04',scope:'Certain MY2025 911 vehicles; lighting-control software recall. Confirm VIN and repair status.'},
];
const systems={BODY:['Body & closures','#ba2b36'],POWERTRAIN:['Boxer engine & turbos','#db7942'],TRANSMISSION:['PDK transmission','#8760a9'],AWD_PTM:['All-wheel drive / PTM','#466daf'],CHASSIS:['Suspension & steering','#478883'],BRAKES_WHEELS:['Wheels & brakes','#ac7631'],THERMAL_FLUIDS:['Cooling regions','#6b9baa'],FUEL_EXHAUST:['Fuel & exhaust','#827550'],ELECTRICAL_NETWORK:['Electrical regions','#797c9e'],INTERIOR_RESTRAINTS:['Cabin & restraints','#985e78']};
const scene=new T.Scene(), components=[];
scene.userData={title:'2026 Carrera 4S systems reconstruction',author:'Jack Ingram demo contributors',license:'MIT',units:'meters',geometry_grade:'D representative',model_year:2026,generation:'992.2',hybrid:false};
const metal=new T.MeshStandardMaterial({color:0xb8bec6,metalness:.7,roughness:.35});
const rubber=new T.MeshStandardMaterial({color:0x252628,roughness:.95});
const painted=new T.MeshStandardMaterial({color:0xb62934,metalness:.55,roughness:.3});
const glass=new T.MeshStandardMaterial({color:0x738b98,metalness:.15,roughness:.12,transparent:true,opacity:.32,depthWrite:false});
const groups=new Map();
function part(id,label,system,position,description,refs=['my26'],aliases=[],grade='D representative',related=[]){
  const group=new T.Group();group.name=id;group.position.set(...position);group.userData={component_id:id,geometry_grade:grade};scene.add(group);groups.set(id,group);
  const [systemLabel,color]=systems[system];
  const direction=system==='BODY'?[position[0]*1.1,.8+position[1]*.8,position[2]*.25]:[position[0]*1.7,system==='POWERTRAIN'?1.15:system==='INTERIOR_RESTRAINTS'?1.5:-.3,position[2]*.65];
  components.push({id,label,system,system_label:systemLabel,color,explode:direction,aliases:[label.toLowerCase(),...aliases],description,question:'Inspect the source and confidence record. Confirm equipment and parts against the actual vehicle before purchase or service.',geometry_grade:grade,identity_grade:refs.includes('my26')?'A public model specification':'D architecture reference',placement_grade:'D illustrative layout',part_number:null,source_ids:refs,related,mesh_indices:[]});return group;
}
function mesh(g,geometry,material=metal,position=[0,0,0],rotation=[0,0,0],name='Representative surface'){
  const m=new T.Mesh(geometry,material.clone());m.material.name=name;m.position.set(...position);m.rotation.set(...rotation);m.name=g.name+' / '+name;g.add(m);return m;
}
function box(g,size,position=[0,0,0],material=metal,name='Envelope'){return mesh(g,new T.BoxGeometry(...size),material,position,[0,0,0],name);}
function cylinder(g,radius,length,position=[0,0,0],axis='y',material=metal,name='Cylinder envelope'){
  const rotation=axis==='x'?[0,0,Math.PI/2]:axis==='z'?[Math.PI/2,0,0]:[0,0,0];return mesh(g,new T.CylinderGeometry(radius,radius,length,32),material,position,rotation,name);
}
function link(g,a,b,radius=.018,material=metal,name='Schematic member'){
  const start=new T.Vector3(...a),end=new T.Vector3(...b),delta=end.clone().sub(start);const m=mesh(g,new T.CylinderGeometry(radius,radius,delta.length(),12),material,start.clone().lerp(end,.5).toArray(),[0,0,0],name);m.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),delta.normalize());return m;
}
function panel(g,points,material=painted,name='Reconstructed panel'){
  const geom=new T.BufferGeometry();geom.setAttribute('position',new T.Float32BufferAttribute(points.flat(),3));geom.setIndex([0,1,2,0,2,3]);geom.computeVertexNormals();const m=mesh(g,geom,material,[0,0,0],[0,0,0],name);m.material.side=T.DoubleSide;return m;
}
function curved(g,rows,material=painted,name='Original curved panel'){
  const points=[],indices=[],columns=rows[0].length;for(const row of rows)for(const point of row)points.push(...new T.Vector3(...point).sub(g.position).toArray());
  for(let r=0;r<rows.length-1;r++)for(let c=0;c<columns-1;c++){const a=r*columns+c,b=a+columns;indices.push(a,b,a+1,a+1,b,b+1);}const geometry=new T.BufferGeometry();geometry.setAttribute('position',new T.Float32BufferAttribute(points,3));geometry.setIndex(indices);geometry.computeVertexNormals();const m=mesh(g,geometry,material,[0,0,0],[0,0,0],name);m.material.side=T.DoubleSide;return m;
}
const profile=[[-2.18,.81,.72],[-1.6,.926,.86],[-1.2,.913,.88],[-.8,.87,.90],[.4,.87,.90],[.8,.89,.79],[1.25,.90,.78],[1.8,.84,.67],[2.18,.75,.58]];
function section(z){const i=Math.max(0,profile.findLastIndex(p=>p[0]<=z)),a=profile[i],b=profile[Math.min(i+1,profile.length-1)],t=b[0]===a[0]?0:(z-a[0])/(b[0]-a[0]);return [T.MathUtils.lerp(a[1],b[1],t),T.MathUtils.lerp(a[2],b[2],t)];}
function sidePanel(g,side,z0,z1){
  const rows=[];for(let i=0;i<=56;i++){const z=z0+(z1-z0)*i/56,[width,top]=section(z),dz=Math.min(Math.abs(z-1.245),Math.abs(z+1.205)),bottom=dz<.392?.35+Math.sqrt(.392**2-dz**2):.34;rows.push(Array.from({length:9},(_,k)=>{const t=k/8;return [side*(width-.025*(1-t)**2),bottom+(top-bottom)*t,z];}));}curved(g,rows,painted,'Original curved side panel');
}
const represent='Original representative geometry; position and shape are illustrative, not measured OEM parts.';
const floor=part('body','Floor & occupant structure','BODY',[0,.26,0],'A simplified floor and sill structure provides context for the assemblies. '+represent,['body'],['body','shell','panels'],undefined,['engine','pdk','front-differential']);box(floor,[1.62,.10,3.65],undefined,metal,'Floor envelope');
for(const side of [-1,1]){const s=side<0?'left':'right';
  const sill=part(s+'-sill',s+' sill','BODY',[side*.82,.39,0],represent,['body']);box(sill,[.12,.23,2.7],undefined,painted);
  const door=part(s+'-door',s+' door','BODY',[side*.87,.72,.1],represent,['body'],[s+' door']);sidePanel(door,side,-.55,.68);
  for(const [axle,z] of [['front',1.245],['rear',-1.205]]){
    const fender=part(s+'-'+axle+'-fender',s+' '+axle+' fender','BODY',[side*.81,.57,z],represent,['body']);
    // Open arch: surface follows a semicircle above the calibrated wheel center.
    sidePanel(fender,side,axle==='front'?.68:-2.18,axle==='front'?2.18:-.55);
  }
}
const roof=part('roof','Roof panel','BODY',[0,1.277,-.13],represent,['body'],['roof']);curved(roof,Array.from({length:17},(_,i)=>Array.from({length:17},(_,j)=>{const z=-.62+i/16*1.02,x=-.65+j/16*1.30;return [x,1.303-.14*(x/.65)**2-.065*((z+.11)/.51)**2,z];})));
for(const [id,label,z,length,y] of [['hood','Front luggage lid',1.54,1.4,.67],['rear-lid','Rear engine lid',-1.65,.98,.80]]){
  const p=part(id,label,'BODY',[0,y,z],represent,['body'],[id==='hood'?'hood':'engine lid']);const z0=id==='hood'?.99:-2.18,z1=id==='hood'?2.18:-1.20;curved(p,Array.from({length:25},(_,i)=>Array.from({length:17},(_,j)=>{const zz=z0+(z1-z0)*i/24,[w,top]=section(zz),x=(-1+j/8)*w;return [x,top+.045*(1-(x/w)**2),zz];})));
}
for(const [id,label,z,y,front] of [['windshield','Windshield',.79,1.05,true],['rear-glass','Rear glazing',-.96,1.03,false]]){
  const p=part(id,label,'BODY',[0,y,z],represent,['body'],['glass',label.toLowerCase()]);const z0=front?.40:-1.20,z1=front?.99:-.62;curved(p,Array.from({length:13},(_,i)=>Array.from({length:17},(_,j)=>{const t=i/12,width=front?.65+t*.14:.79-t*.14,x=(-1+j/8)*width,yy=front?1.238-t*.397:.925+t*.313;return [x,yy-.13*(x/width)**2,z0+(z1-z0)*t];})),glass,'Curved glazing');
}
for(const side of [-1,1]){const s=side<0?'left':'right',p=part(s+'-side-glass',s+' side glazing','BODY',[side*.73,1.03,-.12],represent,['body'],[s+' window']);panel(p,[[side*.14,-.16,-.73],[side*.14,-.16,.91],[side*-.10,.17,.45],[side*-.10,.17,-.48]],glass,'Side glazing');}
for(const [id,label,z] of [['front-fascia','Front fascia',2.196],['rear-fascia','Rear fascia',-2.196]]){const p=part(id,label,'BODY',[0,.49,z],represent,['body'],[label.toLowerCase()]);const m=mesh(p,new T.SphereGeometry(1,40,16),painted);m.scale.set(id==='front-fascia'?.82:.90,.19,.075);box(p,[.60,.10,.035],[0,-.055,id==='front-fascia'?.056:-.056],rubber,'Air opening reference');}
for(const side of [-1,1]){const s=side<0?'left':'right',p=part(s+'-headlight',s+' headlight region','BODY',[side*.63,.71,1.92],represent,['my26'],[s+' headlight']);const m=mesh(p,new T.SphereGeometry(1,24,16),glass);m.scale.set(.12,.13,.07);}
const engine=part('engine','3.0 L twin-turbo boxer engine','POWERTRAIN',[0,.52,-1.59],'MY2026: six-cylinder rear-mounted boxer, 2,981 cm³, 473 hp and 390 lb-ft. The envelope is representative.',['my26','envelope'],['engine','motor','boxer','flat six'],undefined,['pdk','left-turbo','right-turbo','left-cylinder-head','right-cylinder-head']);box(engine,[.32,.26,.62],undefined,metal,'Crankcase envelope');
const crank=part('crankshaft','Crankshaft reference','POWERTRAIN',[0,.54,-1.59],'A representative crankshaft illustrates the opposed-cylinder arrangement; journal positions and firing order are not certified.',['envelope'],['crankshaft']);cylinder(crank,.035,.58,undefined,'z');
for(const side of [-1,1]){const s=side<0?'left':'right';
  const head=part(s+'-cylinder-head',s+' cylinder head','POWERTRAIN',[side*.46,.55,-1.59],represent,['envelope'],[s+' head']);box(head,[.16,.21,.60]);
  for(let i=0;i<3;i++){const id=s+'-cylinder-'+(i+1),p=part(id,s+' cylinder '+(i+1),'POWERTRAIN',[side*.29,.54,-1.79+i*.20],'Six opposed cylinder envelopes. Bore 91.0 mm and stroke 76.4 mm are sourced; casting geometry is representative.',['envelope'],[id],undefined,['crankshaft',s+'-cylinder-head']);cylinder(p,.059,.21,undefined,'x');
    const piston=part(s+'-piston-'+(i+1),s+' piston '+(i+1),'POWERTRAIN',[side*.27,.54,-1.79+i*.20],'Illustrative piston at the sourced 91 mm bore envelope. No firing-order or physical simulation is claimed.',['envelope'],[s+' piston '+(i+1)]);cylinder(piston,.0445,.05,undefined,'x');}
  const turbo=part(s+'-turbo',s+' turbocharger','POWERTRAIN',[side*.62,.40,-1.77],'One of the two turbocharger envelopes. Internal blades and exact packaging are not reconstructed.',['my26'],[s+' turbo','turbo'],undefined,['engine',s+'-intercooler']);mesh(turbo,new T.TorusGeometry(.10,.04,12,32),metal,[0,0,0],[Math.PI/2,0,0],'Turbo envelope');
  const cooler=part(s+'-intercooler',s+' charge-air cooler','THERMAL_FLUIDS',[side*.59,.84,-1.6],'The model announcement confirms optimized intercooling; this is a representative exchanger envelope.',['my26'],[s+' intercooler','intercooler']);box(cooler,[.28,.10,.38]);for(let i=0;i<6;i++)box(cooler,[.29,.018,.025],[0,.06,-.16+i*.065],metal,'Cooling fin reference');
}
const pdk=part('pdk','Eight-speed PDK','TRANSMISSION',[0,.44,-.89],'Eight-speed dual-clutch transmission. The case, ribs and clutch shapes are original illustrative geometry, not a teardown of the OEM gearbox.',['my26'],['pdk','gearbox','transmission'],undefined,['engine','rear-differential','propeller-shaft']);const pdkCase=mesh(pdk,new T.SphereGeometry(1,32,16),metal,[0,0,0],[0,0,0],'Original case envelope');pdkCase.scale.set(.21,.165,.31);for(let i=0;i<7;i++){const z=-.23+i*.076,scale=Math.sqrt(1-(z/.34)**2),rib=mesh(pdk,new T.TorusGeometry(1,.025,8,32),metal,[0,0,z],[0,0,0],'Illustrative case rib');rib.scale.set(.215*scale,.17*scale,.17);}cylinder(pdk,.145,.07,[0,0,-.28],'z',metal,'Case flange');
const clutch=part('pdk-clutches','PDK clutch pair','TRANSMISSION',[0,.44,-.76],'Representative paired clutches explain dual-clutch operation. Disc count, dimensions and internal placement are not verified.',['my26'],['clutch','clutches']);for(const x of [-.09,.09])cylinder(clutch,.09,.13,[x,0,0],'z');
const rearDiff=part('rear-differential','Rear differential','AWD_PTM',[0,.37,-1.205],'Rear-axle power path shown schematically. PTV Plus functionality is documented; exact case shape is representative.',['my26','ptm'],['rear differential'],undefined,['rear-left-halfshaft','rear-right-halfshaft']);cylinder(rearDiff,.115,.28,undefined,'x');
const shaft=part('propeller-shaft','Propeller shaft','AWD_PTM',[0,.30,.08],'Illustrates the second transmission output toward the front axle. Physical routing is schematic.',['ptm'],['propeller shaft','cardan shaft','drive shaft'],undefined,['pdk','front-differential']);cylinder(shaft,.035,1.72,undefined,'z');
const frontDiff=part('front-differential','Front differential & PTM clutch','AWD_PTM',[0,.34,1.245],'Porsche documents a water-cooled front differential with an electromechanically controlled clutch. Routing and case dimensions are schematic.',['my26','ptm'],['front differential','ptm','all wheel drive','awd'],undefined,['front-left-halfshaft','front-right-halfshaft']);box(frontDiff,[.26,.20,.31]);cylinder(frontDiff,.08,.14,[0,0,-.22],'z');
for(const [axle,z] of [['front',1.245],['rear',-1.205]])for(const side of [-1,1]){
  const s=side<0?'left':'right',corner=axle+'-'+s,x=side*(axle==='front'?.79:.768),diameter=axle==='front'?.508:.5334,tread=axle==='front'?.245:.305,sidewall=axle==='front'?.08575:.0915,radius=diameter/2+sidewall,y=radius;
  const tire=part(corner+'-tire',corner+' tire','BRAKES_WHEELS',[x,y,z],`Calibrated ${axle==='front'?'245/35 ZR20':'305/30 ZR21'} envelope for the certificate's non-hybrid 20/21-inch summer configuration; tread pattern is illustrative.`,['wheels'],[corner+' tire',axle+' tires'],undefined,[corner+'-wheel',corner+'-brake']);
  for(const direction of [-1,1])mesh(tire,new T.TorusGeometry(diameter/2+sidewall/2,sidewall/2,14,48),rubber,[direction*(tread-sidewall)/2,0,0],[0,Math.PI/2,0],'Tire sidewall');
  // Open annular geometry preserves visibility of the brake assembly.
  const tireBand=new T.CylinderGeometry(radius,radius,tread,48,1,true);mesh(tire,tireBand,rubber,[0,0,0],[0,0,Math.PI/2],'Tread band');
  const wheel=part(corner+'-wheel',corner+' wheel','BRAKES_WHEELS',[x,y,z],'Staggered 20/21-inch wheel envelope. Spoke design is original and not a claim of the exact factory wheel option.',['my26','wheels'],[corner+' wheel',axle+' wheels','wheels'],undefined,[corner+'-tire',corner+'-brake']);mesh(wheel,new T.TorusGeometry(diameter/2,.018,8,40),metal,[0,0,0],[0,Math.PI/2,0],'Rim');cylinder(wheel,.065,tread*.6,undefined,'x');for(let k=0;k<10;k++){const a=k*Math.PI/5;link(wheel,[0,.055*Math.cos(a),.055*Math.sin(a)],[0,diameter*.47*Math.cos(a),diameter*.47*Math.sin(a)],.012,metal,'Original spoke');}
  const brake=part(corner+'-brake',corner+' brake rotor','BRAKES_WHEELS',[side*.73,y,z],`Sourced ${axle==='front'?'408':'380'} mm steel brake-disc diameter. Rotor thickness and internal ventilation shown here are representative.`,['my26'],[corner+' brake',axle+' brakes','brake rotor'],undefined,[corner+'-caliper',corner+'-wheel']);cylinder(brake,axle==='front'?.204:.190,.025,undefined,'x');
  const caliper=part(corner+'-caliper',corner+' brake caliper','BRAKES_WHEELS',[side*.72,y+.12,z+.12],'Original fixed-caliper envelope. Exact piston count and casting detail are not promoted from Carrera S documentation.',['my26'],[corner+' caliper','caliper']);box(caliper,[.08,.13,.16],undefined,painted);
  const half=part(corner+'-halfshaft',corner+' half-shaft','AWD_PTM',[side*.41,y-.04,z],'Schematic axle connection to the hub. Exact shaft geometry and joints are not measured.',['ptm'],[corner+' halfshaft',axle+' halfshaft'],undefined,[corner+'-wheel']);cylinder(half,.022,.64,undefined,'x');
  const damper=part(corner+'-damper',corner+' PASM damper','CHASSIS',[side*.67,.72,z],'PASM damper region. Spring and mount locations are representative, not a suspension travel model.',['my26'],[corner+' suspension','suspension','pasm'],undefined,[corner+'-wheel']);cylinder(damper,.028,.43);const coil=new T.CatmullRomCurve3(Array.from({length:121},(_,i)=>{const t=i/120,a=t*Math.PI*12;return new T.Vector3(.06*Math.cos(a),-.13+t*.30,.06*Math.sin(a));}));mesh(damper,new T.TubeGeometry(coil,120,.009,6,false),metal,undefined,undefined,'Original helical spring');
}
for(const side of [-1,1]){const s=side<0?'left':'right';const gpf=part(s+'-gpf',s+' exhaust / GPF region','FUEL_EXHAUST',[side*.47,.30,-1.91],'Representative exhaust-filter region. Public Porsche bulletin explains ash accumulation with unapproved oil on OPF-equipped 992.II cars; applicability must be checked.',['gpf'],[s+' exhaust','gpf','exhaust'],undefined,['engine',s+'-turbo']);cylinder(gpf,.075,.29,undefined,'z');link(gpf,[0,0,-.14],[side*.16,0,-.31],.025);}
for(const side of [-1,1]){const s=side<0?'left':'right';const seat=part(s+'-seat',s+' front seat','INTERIOR_RESTRAINTS',[side*.38,.57,.02],'The MY2026 coupe has two seats as standard, with optional rear seats. These seat shapes are original representative geometry.',['my26'],[s+' seat','seats','cabin']);box(seat,[.44,.12,.46],undefined,rubber,'Seat cushion');box(seat,[.44,.49,.10],[0,.29,-.17],rubber,'Seat back');}
const dash=part('dashboard','Dashboard & PCM region','INTERIOR_RESTRAINTS',[0,.87,.70],'Cabin layout region only. Screen geometry and switch positions are representative.',['envelope'],['dashboard','pcm','interior']);box(dash,[1.36,.18,.23],undefined,rubber);box(dash,[.34,.14,.025],[.17,.09,-.13],metal,'Screen region');
const steering=part('steering-wheel','Steering wheel','INTERIOR_RESTRAINTS',[-.40,.87,.46],represent,['envelope'],['steering wheel']);mesh(steering,new T.TorusGeometry(.17,.018,10,32),rubber);for(const a of [0,2.1,4.2])link(steering,[0,0,0],[.15*Math.cos(a),.15*Math.sin(a),0],.012);
const cameraRegion=part('rear-camera','Rear-view camera region','ELECTRICAL_NETWORK',[0,.72,-2.19],'Representative camera region for explaining rear visibility. The reviewed ASB2 safety recall covers certain 2020–2025 911 vehicles, not a verified 2026 VIN. No circuit routing is modeled.',['recall-camera'],['rear camera','backup camera','rearview camera']);cylinder(cameraRegion,.025,.036,undefined,'z');
const lighting=part('front-lighting','Front lighting control region','ELECTRICAL_NETWORK',[0,.57,1.78],'Representative lighting-control region. The reviewed ASA1 software recall is a 2025 911 campaign; this 2026 illustration does not establish applicability.',['recall-lighting'],['headlight','headlights','lighting']);box(lighting,[.18,.075,.12],undefined,metal,'Control-module region');

// Explicit functional links. Their 3D curves remain explanatory overlays.
for(const c of components)c.related=c.related.filter(id=>groups.has(id));
scene.updateMatrixWorld(true);
const exportData=await new GLTFExporter().parseAsync(scene,{binary:true,onlyVisible:false});
const asset=Buffer.from(exportData),json=JSON.parse(asset.subarray(20,20+asset.readUInt32LE(12)).toString('utf8'));
function assign(nodeIndex,owner){const n=json.nodes[nodeIndex];owner=n.extras?.component_id || owner;if(Number.isInteger(n.mesh)){const c=components.find(c=>c.id===owner);if(!c)throw new Error('Unowned systems geometry');c.mesh_indices.push(n.mesh);}for(const child of n.children || [])assign(child,owner);}
for(const index of json.scenes[json.scene || 0].nodes)assign(index,null);
const spec={length:4.542,width:1.852,height:1.303,wheelbase:2.450,front_axle_z:1.245,rear_axle_z:-1.205,front_tire:'245/35 ZR20',rear_tire:'305/30 ZR21',front_disc:.408,rear_disc:.380};
const manifest={id:'porsche-9922-c4s-systems',name:'2026 Porsche 911 Carrera 4S · Systems',model_year:2026,generation:'992.2',body_style:'Coupe',market:'US explanatory baseline',hybrid:false,transmission:'8-speed PDK',drivetrain:'PTM AWD',geometry_type:'representative_systems',native_units:'meters',envelope:spec,asset_url:'/static/models/porsche-9922-systems.glb',bytes:asset.length,sha256:createHash('sha256').update(asset).digest('hex'),mesh_count:json.meshes.length,ignored_meshes:[],author:'Jack Ingram demo contributors',author_url:'https://github.com/rblake2320/jack-ingram-chatbot-analytics',license:'MIT · original explanatory geometry',license_url:'https://opensource.org/license/mit',source_url:release,publisher_url:release,scope:'Original representative systems reconstruction. Public specification envelope; illustrative component shapes and positions. No OEM CAD, VIN stock, crash solver, wiring route or repair procedure.',sources,components};
await mkdir('src/demo/static/models',{recursive:true});
await writeFile('src/demo/static/models/porsche-9922-systems.glb',asset);
await writeFile('src/demo/data/porsche_9922_systems.json',JSON.stringify(manifest,null,2)+'\n');
const triangleCount=json.meshes.reduce((n,m)=>n+m.primitives.reduce((p,v)=>p+json.accessors[v.indices].count/3,0),0);
await writeFile('docs/evidence/2026-10-04/porsche-systems-build.json',JSON.stringify({outcome:'Worked',components:components.length,mesh_count:json.meshes.length,triangles:triangleCount,bytes:asset.length,sha256:manifest.sha256,units:'meters',axle_distance:spec.front_axle_z-spec.rear_axle_z,body_envelope:spec,hybrid:false,omitted:'Security systems, exact harness routing, VIN parts and OEM manufacturing geometry'},null,2)+'\n');
console.log(`Worked: original systems twin · ${components.length} components · ${json.meshes.length} meshes · ${triangleCount} triangles · ${asset.length} bytes`);
