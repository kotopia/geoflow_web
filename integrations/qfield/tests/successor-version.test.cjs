const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const qml = fs.readFileSync('integrations/qfield/geoflow-field.qml','utf8');
const start=qml.indexOf('    function applyServerVersions('), end=qml.indexOf('    function postOutbox(',start);
const ctx={pendingKey:(layer,id)=>layer+'|'+id};vm.createContext(ctx);vm.runInContext(qml.slice(start,end),ctx);
for (const [receipt,base,expected] of [[true,'old','ack'],[false,'old','old'],[true,'different','different']]) {
 const state={feature_versions:{},pending:{'DORO|id':{base_updated_at:base,geometry_wkt:'preserve'}},outbox:{changeset_id:'frozen'}};
 ctx.applyServerVersions(state,{version_receipt:receipt,applied:[{layer:'DORO',id:'id',action:'update',updated_at:'ack'}]},{changes:[{layer:'DORO',id:'id',base_updated_at:'old'}]});
 assert.equal(state.pending['DORO|id'].base_updated_at,expected);
 assert.equal(state.pending['DORO|id'].geometry_wkt,'preserve');assert.equal(state.outbox.changeset_id,'frozen');
}
console.log('Successor version advances only from its own verified receipt.');
