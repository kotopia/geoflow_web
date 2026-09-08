const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const qml=fs.readFileSync('integrations/qfield/geoflow-field.qml','utf8');
const start=qml.indexOf('    function buildConflictRecovery('),end=qml.indexOf('    // QField exposes configure',start);
assert(start>0&&end>start);const ctx={pendingKey:(l,i)=>l+'|'+i};vm.createContext(ctx);vm.runInContext(qml.slice(start,end),ctx);
const old={outbox:{changeset_id:'old',client_id:'client',base_revision:58,changes:[{action:'update',layer:'DORO',id:'road',base_updated_at:'old-version',geometry_wkt:'old-shape',attributes:{name:'road'}}]},pending:{'DORO|road':{action:'update',geometry_wkt:'latest-shape',attributes:{note:'latest'}},other:{action:'update'}},conflict:{changeset_id:'old',conflicts:[{layer:'DORO',id:'road',reason:'server_object_changed',server_updated_at:'reviewed-version'}]}};
const snapshot=JSON.stringify(old);const result=ctx.buildConflictRecovery(old,'new').state;
assert.equal(JSON.stringify(old),snapshot);
assert.equal(result.outbox.changeset_id,'new');assert.equal(result.outbox.changes[0].base_updated_at,'reviewed-version');assert.equal(result.outbox.changes[0].geometry_wkt,'latest-shape');assert.equal(result.outbox.changes[0].attributes.name,'road');assert.equal(result.outbox.changes[0].attributes.note,'latest');assert(result.pending.other);assert(!result.pending['DORO|road']);assert.equal(JSON.stringify(result.recovery_archive[0].outbox),JSON.stringify(old.outbox));
for(const mutate of [s=>s.conflict.changeset_id='other',s=>s.conflict.conflicts[0].reason='server_object_missing',s=>s.conflict.conflicts[0].server_updated_at='',s=>s.pending['DORO|road'].action='delete']){
 const state=JSON.parse(snapshot);mutate(state);assert.throws(()=>ctx.buildConflictRecovery(state,'new'));
}
console.log('Recovery preserves history/latest edits and rejects unsupported conflicts.');
