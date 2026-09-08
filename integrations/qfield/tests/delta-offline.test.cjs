const vm=require('node:vm'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const src=execFileSync('python',['-c','from scripts.dev.update_qfield_runtime import render_runtime; print(render_runtime().decode())'],{encoding:'utf8'});
function method(name){const a=src.indexOf('function '+name+'(');assert.ok(a>=0);let b=src.indexOf('{',a)+1,d=1;for(;d;b++){if(src[b]==='{')d++;if(src[b]==='}')d--;}return src.slice(a,b);}
let now=100000, state, requests, applied, saved;
function setup(){
 state={base_revision:5,pending:{},outbox:null,conflict:null};requests=[];applied=0;saved=0;
 const c={Date:{now:()=>now},deltaIdleDelayMs:15000,nextDeltaAtMs:0,deltaSnapshotRequired:false,
 projectId:'p',serverUrl:'s',deltaUrl:'/delta',bearerToken:'test',deltaRequest:null,deltaStartedAtMs:0,
 deltaInFlight:false,syncInFlight:false,configReady:true,edits:false,authorized:true,
 ownsRuntime:()=>true,sessionAuthorized:()=>c.authorized,hasUncommittedEdits:()=>c.edits,
 projectState:()=>state,absoluteUrl:x=>x,saveProjectState:s=>{state=s;saved++;},
 applyDeltaChange:()=>{applied++;return true;},mapCanvas:{refresh(){}},bindLayers(){},rebuildPollingBaseline(){},log(){},toast(){},markSessionExpired(){c.authorized=false;},
 XMLHttpRequest:class {static DONE=4;open(){}setRequestHeader(){}send(){requests.push(this);}abort(){this.aborted=true;this.readyState=4;this.status=0;this.onreadystatechange();}}};
 vm.createContext(c);vm.runInContext(['pullDelta','canApplyDelta','scheduleDeltaCheck','expireStalledDelta'].map(method).join('\n'),c);
 c.respond=(r,body,status=200)=>{r.status=status;r.readyState=4;r.responseText=JSON.stringify(body);r.onreadystatechange();};return c;
}
const reply={ok:true,changes:[{revision:6}],has_more:false};
let c=setup();c.pullDelta(false);c.pullDelta(false);assert.equal(requests.length,1);
c.respond(requests[0],reply);assert.equal(applied,1);assert.equal(state.base_revision,6);assert.equal(c.deltaIdleDelayMs,15000);
for(const mutate of [()=>state.pending.x={geometry:'local'},()=>state.outbox={id:'offline'},()=>state.conflict={},()=>c.edits=true,()=>c.projectId='other',()=>state.base_revision=9,()=>c.authorized=false]){
 c=setup();c.pullDelta(false);mutate();c.respond(requests[0],reply);assert.equal(applied,0);assert.equal(saved,0);
}
c=setup();c.pullDelta(false);let old=requests[0];now+=31000;c.expireStalledDelta();assert.equal(c.deltaInFlight,false);assert.equal(old.aborted,true);assert.equal(c.deltaIdleDelayMs,60000);
c.respond(old,reply);assert.equal(applied,0);c.pullDelta(false);assert.equal(requests.length,1);
now+=61000;c.pullDelta(false);assert.equal(requests.length,2);
c=setup();c.scheduleDeltaCheck(false,false);assert.equal(c.deltaIdleDelayMs,30000);c.scheduleDeltaCheck(false,false);assert.equal(c.deltaIdleDelayMs,60000);c.scheduleDeltaCheck(false,false);assert.equal(c.deltaIdleDelayMs,60000);
c=setup();c.pullDelta(false);c.respond(requests[0],{ok:true,changes:[],has_more:true});assert.equal(requests.length,1);
// Flush queued state before returning; reconstruct a new instance from that persisted JSON.
let disk='{}',cache='{}';const offline={projectId:'p',parseStates:()=>JSON.parse(cache),durableState:{set projectStatesJson(v){cache=v;},sync(){disk=cache;}},updateUnsyncedCount(){}};
vm.createContext(offline);vm.runInContext(method('saveProjectState'),offline);
const queued={base_revision:8,pending:{road:{geometry:'offline-edit'}},outbox:{changeset_id:'stable-id'},conflict:null};offline.saveProjectState(queued);
assert.deepEqual(JSON.parse(disk).p,queued);
console.log('PASS: delta backoff/timeout, stale response rejection, local edit protection, queue persistence across reconstructed state');
