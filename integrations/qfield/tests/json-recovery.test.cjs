const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const src=fs.readFileSync('integrations/qfield/geoflow-field.qml','utf8');
function method(n){const a=src.indexOf('function '+n+'(');let b=src.indexOf('{',a)+1,d=1;for(;d;b++){if(src[b]==='{')d++;if(src[b]==='}')d--;}return src.slice(a,b);}
let local={note:'retained',nested:{depth:1}},saved=0;
const old={changeset_id:'old',changes:[{id:'id',layer:'WTL_VALV_PS',action:'create',geometry_wkt:'POINT (1 2)',attributes:{ext_data:'[object Object]',name:'valve'}}]};
let state={outbox:old,pending:{next:{attributes:{name:'latest'}}}};
const c={layerBindings:[{standard:'WTL_VALV_PS',layer:{}}],featureByObjectId:()=>({attribute:()=>local}),projectState:()=>state,saveProjectState:s=>{state=s;saved++;},uuidV4:()=> 'new',log(){}};
vm.createContext(c);vm.runInContext(method('normalizedValue')+'\n'+method('recoverLegacyJsonPayload'),c);
assert.equal(JSON.stringify(c.normalizedValue(local)),JSON.stringify(local));
const result=c.recoverLegacyJsonPayload(old);assert.equal(result.changeset_id,'new');assert.equal(result.changes[0].geometry_wkt,old.changes[0].geometry_wkt);
assert.equal(result.changes[0].attributes.ext_data.note,'retained');assert.equal(old.changes[0].attributes.ext_data,'[object Object]');
assert.equal(state.pending.next.attributes.name,'latest');assert.equal(state.recovery_archive[0].original_outbox,old);
local='{invalid';state={outbox:old};saved=0;assert.equal(c.recoverLegacyJsonPayload(old),old);assert.equal(saved,0);
console.log('PASS: JSON objects preserved; legacy queue repaired from actual local value and archived; unreadable values retained');
