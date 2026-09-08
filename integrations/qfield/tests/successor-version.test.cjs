const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const qml = fs.readFileSync('integrations/qfield/geoflow-field.qml','utf8');
const start=qml.indexOf('    function applyServerVersions('), end=qml.indexOf('    function postOutbox(',start);
const ctx={layerBindings:[],pendingKey:(layer,id)=>layer+'|'+id};vm.createContext(ctx);vm.runInContext(qml.slice(start,end),ctx);
for (const [receipt,base,expected] of [[true,'old','ack'],[false,'old','old'],[true,'different','different']]) {
 const state={feature_versions:{},pending:{'DORO|id':{base_updated_at:base,geometry_wkt:'preserve'}},outbox:{changeset_id:'frozen'}};
 ctx.applyServerVersions(state,{version_receipt:receipt,applied:[{layer:'DORO',id:'id',action:'update',updated_at:'ack'}]},{changes:[{layer:'DORO',id:'id',base_updated_at:'old'}]});
 assert.equal(state.pending['DORO|id'].base_updated_at,expected);
 assert.equal(state.pending['DORO|id'].geometry_wkt,'preserve');assert.equal(state.outbox.changeset_id,'frozen');
}
console.log('Successor version advances only from its own verified receipt.');

// An online acknowledgement must advance the next offline signal's cached base,
// without waiting for pullDelta or mutating a different layer/object.
ctx.layerBindings=[
 {standard:'DORO',fidMap:{1:'id',2:'other'},versionMap:{1:'old',2:'other-version'}},
 {standard:'SURVEY',fidMap:{1:'id'},versionMap:{1:'survey-version'}}
];
const state={feature_versions:{},pending:{},outbox:null};
ctx.applyServerVersions(state,{version_receipt:true,applied:[{layer:'DORO',id:'id',updated_at:'ack'}]},{changes:[]});
assert.equal(ctx.layerBindings[0].versionMap[1],'ack');
assert.equal(ctx.layerBindings[0].versionMap[2],'other-version');
assert.equal(ctx.layerBindings[1].versionMap[1],'survey-version');
ctx.applyServerVersions(state,{version_receipt:false,applied:[{layer:'DORO',id:'id',updated_at:'unverified'}]},{changes:[]});
assert.equal(ctx.layerBindings[0].versionMap[1],'ack');
console.log('Next offline capture uses the acknowledged version without a delta round trip.');
