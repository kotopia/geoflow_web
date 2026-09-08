const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('geoflow_ops/templates/geoflow_ops/gis/project_dashboard.html', 'utf8');
const script = html.slice(html.lastIndexOf('<script>') + 8, html.lastIndexOf('</script>'));
async function scenario(marker, importRequested, confirmResult = true) {
  const nodes = {};
  for (const id of ['qfieldPersistentOpen', 'qfieldForceInstall', 'qfieldRemoveLocal', 'qfieldPersistentStatus']) {
    nodes[id] = {dataset: {projectId: 'project', statusUrl: '/status'}, addEventListener(_, cb) {this.click = cb;}};
  }
  let confirms = 0;
  const window = {location: {href: ''}, confirm() {confirms++; return confirmResult;}, setTimeout(cb) {cb();}};
  vm.runInNewContext(script, {
    document: {getElementById: id => nodes[id]}, window,
    localStorage: {getItem() {return marker;}, setItem() {}, removeItem() {}},
    fetch: async () => ({ok: true, json: async () => ({ok: true, install: {launch_url: 'qfield://geoflow', install_url: 'qfield://import', plugin_runtime_version: 'new'}})})
  });
  await nodes[importRequested ? 'qfieldForceInstall' : 'qfieldPersistentOpen'].click();
  return {url: window.location.href, confirms};
}
(async () => {
  for (const marker of [null, '{"plugin_runtime_version":"old"}', '{broken']) {
    assert.deepEqual(await scenario(marker, false), {url: 'qfield://geoflow', confirms: 0});
  }
  assert.deepEqual(await scenario(null, true), {url: 'qfield://import', confirms: 1});
  assert.deepEqual(await scenario(null, true, false), {url: '', confirms: 1});
  console.log('PASS: open never imports; explicit import requires confirmation');
})().catch(error => {console.error(error); process.exitCode = 1;});
