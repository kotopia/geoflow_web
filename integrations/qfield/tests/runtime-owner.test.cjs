const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const runtime = execFileSync('python', ['-c', 'from scripts.dev.update_qfield_runtime import render_runtime; print(render_runtime().decode())'], {encoding:'utf8'});
function method(text, name) {
 const start = text.indexOf('function ' + name + '('); assert.ok(start >= 0, name);
 const opening = text.indexOf('{', start); let depth = 1, end = opening + 1;
 while (depth && end < text.length) { if(text[end] === '{')depth++; if(text[end] === '}')depth--; end++; }
 return text.slice(start, end);
}
const host = {children: []};
function instance() {
 const ctx = {mainWindow:{contentItem:host}, runtimeLease:null, runtimeActive:false,
 Qt:{createQmlObject(_, parent) {const slot={objectName:'geoflowFieldRuntimeOwnerV1',owner:null};parent.children.push(slot);return slot;}}};
 ctx.geoflowField=ctx;
 vm.createContext(ctx);
 vm.runInContext(method(runtime,'acquireRuntime')+'\n'+method(runtime,'ownsRuntime'),ctx);
 return ctx;
}
const first=instance(), second=instance();
assert.equal(first.acquireRuntime(),true); assert.equal(second.acquireRuntime(),false);
assert.equal(!!first.ownsRuntime(),true);assert.equal(!!second.ownsRuntime(),false);
assert.equal(host.children.length,1);
for (const name of ['postOutbox','syncNow','pullDelta','claimPendingSession','captureGeometry','bindLayers']) {
 const body=method(runtime,name);assert.match(body,/\{\s*if \(!ownsRuntime\(\)\) return/);
 vm.runInContext(body,second); // inactive calls must not touch request/state dependencies
 second[name]();
}
first.runtimeLease.owner=null;first.runtimeActive=false;
assert.equal(second.acquireRuntime(),true);assert.equal(!!first.ownsRuntime(),false);
const launcher=fs.readFileSync('integrations/qfield/launcher/main.qml','utf8');
let saved='{}'; const files=new Set(['/new/geoflow-field.qgs','/old/geoflow-field.qgs']);
const ctx={activeOwner:true,entry:k=>k==='project_id'?'p':'http://server/',normalServer:v=>v.replace(/\/+$/,''),
 qgisProject:{fileName:'/new/geoflow-field.qgs'},QfFileUtils:{fileExists:p=>files.has(p)},
 projects:()=>JSON.parse(saved),key:(s,p)=>s+'|'+p,registry:{set projectsJson(v){saved=v;},sync(){}},log(){},toast(){}};
vm.createContext(ctx);vm.runInContext(method(launcher,'registerCurrent'),ctx);
assert.equal(ctx.registerCurrent(false),true);assert.equal(JSON.parse(saved)['http://server|p'],'/new/geoflow-field.qgs');
saved=JSON.stringify({'http://server|p':'/old/geoflow-field.qgs'});
assert.equal(ctx.registerCurrent(false),false);assert.equal(JSON.parse(saved)['http://server|p'],'/old/geoflow-field.qgs');
files.delete('/old/geoflow-field.qgs');assert.equal(ctx.registerCurrent(false),true);
ctx.activeOwner=false;assert.equal(ctx.registerCurrent(true),false);
console.log('PASS: one runtime owner, inactive network/capture blocked, owner release, guarded auto registration');
