const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const qml = fs.readFileSync('integrations/qfield/geoflow-field.qml', 'utf8');
const start = qml.indexOf('    function expireStalledChangeset()');
const end = qml.indexOf('    function reportSyncBlock', start);
assert(start >= 0 && end > start);
let aborted = 0, retries = 0;
const outbox = { changeset_id: 'same-id', changes: [{ id: 'pending-edit' }] };
const context = {
  syncInFlight: true, changesetStartedAtMs: 0, syncStatus: 'syncing', outbox,
  changesetRequest: { abort() { aborted++; assert.equal(context.syncInFlight, false); assert.equal(context.changesetRequest, null); } },
  Date: { now: () => 29000 }, scheduleRetry() { retries++; }, log() {},
};
vm.createContext(context);
vm.runInContext(qml.slice(start, end), context);
context.expireStalledChangeset();
assert.equal(aborted, 0);
context.Date.now = () => 31000;
context.expireStalledChangeset();
assert.equal(aborted, 1);
assert.equal(retries, 1);
assert.equal(context.outbox, outbox);
assert.equal(context.outbox.changeset_id, 'same-id');
context.expireStalledChangeset();
assert.equal(aborted, 1);
console.log('Timeout releases request lock and retains original changeset.');
