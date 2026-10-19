// Execute the actual modal renderer with a minimal DOM; no network or live files.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('geoflow_ops/static/geoflow_ops/js/process-workboard-ui.js', 'utf8');
const renderer = source.slice(source.indexOf('  function renderAttachments('), source.indexOf('  function resetModal('));
function element() { return { children: [], appendChild(child) { this.children.push(child); }, replaceChildren() { this.children = []; } }; }
async function run() {
  let calls = [], refresh = 0, errors = [], question;
  const ctx = { document: { createElement: element }, attachList: element(), currentCanWrite: true, config: { csrfToken: 'test' }, confirm: text => { question = text; return false; }, window: { deleteAttachment: async id => calls.push(id) }, loadEvents: async keep => { assert.equal(keep, true); refresh++; }, showAlert: text => errors.push(text) };
  vm.createContext(ctx); vm.runInContext(renderer, ctx);
  const render = () => ctx.renderAttachments([{ id: 'chosen', original_name: '계약서.pdf' }, { id: 'other', original_name: 'other.pdf' }]);
  const remove = () => ctx.attachList.children[0].children[1].children[1];
  render(); remove().onclick(); assert.match(question, /계약서.pdf/); assert.deepEqual(calls, []);
  ctx.confirm = () => true; remove().onclick(); await new Promise(setImmediate);
  assert.deepEqual(calls, ['chosen']); assert.equal(refresh, 1);
  ctx.window.deleteAttachment = async () => { throw Error('403'); };
  render(); remove().onclick(); await new Promise(setImmediate);
  assert.equal(errors.length, 1); assert.equal(refresh, 1); assert.equal(remove().disabled, false);
  ctx.currentCanWrite = false; render(); assert.equal(ctx.attachList.children[0].children[1].children.length, 1);
  for (const file of ['process-workboard-ui.js', 'process-events-ui.js']) {
    const text = fs.readFileSync('geoflow_ops/static/geoflow_ops/js/' + file, 'utf8');
    const timeline = text.slice(text.indexOf('  function renderTimeline('), text.indexOf('  function loadEvents('));
    assert.ok(!timeline.includes('.sort('), file + ' must preserve server order');
  }
  console.log('PASS: filename confirmation, cancel, selected-file delete, refresh, failure, read-only buttons, server order');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
