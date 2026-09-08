const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const src=execFileSync('python',['-c','from scripts.dev.update_qfield_runtime import render_runtime; print(render_runtime().decode())'],{encoding:'utf8'});
function method(n){const a=src.indexOf('function '+n+'(');assert.ok(a>=0);let b=src.indexOf('{',a)+1,d=1;for(;d;b++){if(src[b]==='{')d++;if(src[b]==='}')d--;}return src.slice(a,b);}
let queued=[],editing=true;
const feature={attribute:n=>n==='id'?'new':'project'};
const c={ownsRuntime:()=>true,configReady:true,captureSuppressed:false,syncInFlight:false,authBlocked:false,requestInFlight:false,
 layerBindings:[{standard:'SURVEY',layer:{}}],pollingBaselineReady:true,pollingBaseline:{},projectId:'project',
 LayerUtils:{createFeatureIterator(){let first=true;return {hasNext:()=>first,next(){first=false;return feature;},close(){}};}},
 canonicalUuid:v=>v,pendingKey:(l,id)=>typeof l==='object'?l.layer+'|'+l.id:l+'|'+id,
 featureSignature:()=> 'signature',projectState:()=>({pending:{},outbox:null}),featureBaseUpdatedAt:()=>'',
 hasUncommittedEdits:()=>editing,featureGeometryWkt:()=> 'POINT (1 2)',collectAttributes:()=>({code:'S01'}),
 queueChange:x=>queued.push(x),log(){},syncNow(){}};
vm.createContext(c);vm.runInContext(method('pollForLocalChanges'),c);
c.pollForLocalChanges(false);assert.equal(queued.length,0);assert.equal(Object.keys(c.pollingBaseline).length,0);
editing=false;c.pollForLocalChanges(false);assert.equal(queued.length,1);assert.equal(queued[0].action,'create');
c.pollForLocalChanges(false);assert.equal(queued.length,1);
let rollback=0,commit=0,changed=[];
const layer={fields:()=>({indexOf:n=>n==='name'?2:-1}),startEditing:()=>true,changeAttributeValue:(fid,idx,v)=>{changed.push([fid,idx,v]);return true;},commitChanges:()=>{commit++;return true;},rollBack:()=>rollback++};
const d={canonicalUuid:v=>v,deltaLayer:()=>layer,featureByObjectId:()=>({id:()=>7}),captureSuppressed:false,protectedField:n=>n==='id',log(){}};
vm.createContext(d);vm.runInContext(method('applyDeltaChange'),d);
assert.equal(d.applyDeltaChange({client_id:'remote',id:'uuid',action:'update',attributes:{name:'received'}},{}),true);
assert.deepEqual(changed,[[7,2,'received']]);assert.equal(commit,1);
assert.equal(d.applyDeltaChange({client_id:'remote',id:'uuid',action:'update',attributes:{unknown:'bad'}},{}),false);assert.equal(rollback,1);assert.equal(commit,1);assert.equal(d.captureSuppressed,false);
console.log('PASS: committed create fallback exactly once and received attributes use field/FID methods; schema mismatch rejects');
