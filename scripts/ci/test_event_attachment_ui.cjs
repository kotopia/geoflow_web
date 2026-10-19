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

// Execute the visible detail-page renderers, not only the hidden shared UI.
for (const domain of ['contract', 'project']) {
  const path = 'geoflow_ops/templates/geoflow_ops/' + domain + 's/' + domain + '_detail.html';
  const html = fs.readFileSync(path, 'utf8');
  const start = html.indexOf('var events = (payload.events || [])');
  const end = html.indexOf('}).catch(function()', start);
  assert.ok(start >= 0 && end > start, path);
  function node() {
    return { children: [], textContent: '', appendChild(child) { this.children.push(child); },
      replaceChildren() { this.children = []; }, setAttribute() {}, addEventListener() {},
      classList: { add() {}, remove() {} } };
  }
  const events = [
    {title: 'Late entry, earlier event', occurred_at: '2025-01-22', created_at: '2026-10-01T00:00:00Z'},
    {title: 'Contract', occurred_at: '2025-01-23', created_at: '2026-09-30T05:59:31.780815Z'},
    {title: 'Kickoff', occurred_at: '2025-01-23', created_at: '2026-09-30T05:59:53.560858Z'},
    {title: 'Completion', occurred_at: '2025-05-20'},
    {title: 'Invoice', occurred_at: '2026-05-20'}
  ];
  const ctx = {payload: {events}, visibleList: node(), visibleEmpty: node(),
    document: {createElement: node}, stageLabels: {}, typeLabels: {}, window: {},
    formatContractEventDate: value => value, formatProjectEventDate: value => value};
  vm.createContext(ctx);
  const render = '(function(){' + html.slice(start, end) + '})()';
  vm.runInContext(render, ctx);
  const titles = () => ctx.visibleList.children.map(item => item.children[1].textContent);
  assert.deepEqual(titles(), events.map(ev => ev.title), path);
  events[1].updated_at = '2026-10-19T12:00:00Z';
  vm.runInContext(render, ctx);
  assert.deepEqual(titles(), events.map(ev => ev.title), path + ' after edit');
  ctx.payload.events = [];
  vm.runInContext(render, ctx);
  assert.equal(ctx.visibleList.children.length, 0);
  console.log('PASS: ' + domain + ' visible timeline chronology, same-day creation, edit stability, empty state');
}
