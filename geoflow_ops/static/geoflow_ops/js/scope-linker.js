/* scope-linker.js — preload JSON once, client render, buffer persist. */

const GFSpinner = (() => {
  const el = document.getElementById('globalSpinner');
  let depth = 0;
  const show = () => { if (el) { depth += 1; el.classList.remove('d-none'); } };
  const hide = () => { if (el) { depth = Math.max(0, depth - 1); if (depth === 0) el.classList.add('d-none'); } };
  return { show, hide };
})();

async function gfFetch(url, opts = {}) {
  GFSpinner.show();
  try { return await fetch(url, opts); }
  finally { GFSpinner.hide(); }
}

async function fetchHtml(url) {
  const response = await gfFetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return response.text();
}

function ensureScopeModal() {
  let el = document.getElementById('scopeModal');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'scopeModal';
  el.className = 'modal fade';
  el.tabIndex = -1;
  const dialog = document.createElement('div');
  dialog.className = 'modal-dialog modal-xl modal-dialog-scrollable';
  const content = document.createElement('div');
  content.className = 'modal-content';
  dialog.appendChild(content);
  el.appendChild(dialog);
  document.body.appendChild(el);
  return el;
}

function replaceModalContent(html) {
  const modalEl = ensureScopeModal();
  const content = modalEl.querySelector('.modal-content');
  if (content) content.innerHTML = html; // trusted server-rendered modal fragment
  return modalEl;
}

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  return parts.length === 2 ? parts.pop().split(';').shift() : undefined;
}

function getScopeBuffer(modalEl) {
  if (!modalEl._scopeBuffer) modalEl._scopeBuffer = {};
  return modalEl._scopeBuffer;
}
function makeKey(l2, lv3) { return `${l2}|${lv3}`; }

function seedBufferFromDOM(modalEl) {
  const buffer = getScopeBuffer(modalEl);
  modalEl.querySelectorAll('#scope-table tbody tr').forEach((tr) => {
    const lv2 = tr.dataset.l2Id;
    const lv3 = tr.dataset.lv3Id;
    if (!lv2 || !lv3) return;
    buffer[makeKey(lv2, lv3)] = {
      lv2_id: lv2,
      lv3_id: lv3,
      active: !!tr.querySelector('.js-scope-active')?.checked,
      unit: tr.querySelector('.js-scope-unit')?.value || '',
      design_qty: tr.querySelector('.js-scope-design')?.value || '',
      completed_qty: tr.querySelector('.js-scope-completed')?.value || '',
    };
  });
}

function hydrateDOMFromBuffer(modalEl) {
  const buffer = getScopeBuffer(modalEl);
  modalEl.querySelectorAll('#scope-table tbody tr').forEach((tr) => {
    const key = makeKey(tr.dataset.l2Id, tr.dataset.lv3Id);
    const cached = buffer[key];
    if (cached) {
      const active = tr.querySelector('.js-scope-active');
      const unit = tr.querySelector('.js-scope-unit');
      const design = tr.querySelector('.js-scope-design');
      const completed = tr.querySelector('.js-scope-completed');
      if (active) active.checked = !!cached.active;
      if (unit) unit.value = cached.unit || unit.value || tr.dataset.unitDefault || '';
      if (design) design.value = cached.design_qty || design.value || '';
      if (completed) completed.value = cached.completed_qty || completed.value || '';
    }
    applyScopeRowDisabledState(tr);
  });
}

function attachRowChangeBuffering(modalEl) {
  const buffer = getScopeBuffer(modalEl);
  modalEl.querySelectorAll('#scope-table tbody tr').forEach((tr) => {
    const lv2 = tr.dataset.l2Id;
    const lv3 = tr.dataset.lv3Id;
    if (!lv2 || !lv3) return;
    const key = makeKey(lv2, lv3);
    tr.querySelectorAll('.js-scope-active, .js-scope-unit, .js-scope-design, .js-scope-completed').forEach((el) => {
      const eventName = el.classList.contains('js-scope-active') ? 'change' : 'input';
      el.addEventListener(eventName, () => {
        buffer[key] = {
          lv2_id: lv2,
          lv3_id: lv3,
          active: !!tr.querySelector('.js-scope-active')?.checked,
          unit: tr.querySelector('.js-scope-unit')?.value || '',
          design_qty: tr.querySelector('.js-scope-design')?.value || '',
          completed_qty: tr.querySelector('.js-scope-completed')?.value || '',
        };
        if (el.classList.contains('js-scope-active')) applyScopeRowDisabledState(tr);
      });
    });
  });
}

async function loadCatalogDataOnce(modalEl, projectId) {
  if (modalEl._catalog) return modalEl._catalog;
  const response = await gfFetch(`/projects/${encodeURIComponent(projectId)}/scope-data/`, {
    headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin'
  });
  if (!response.ok) throw new Error('HTTP ' + response.status);
  const data = await response.json();
  modalEl._catalog = data;
  return data;
}

function buildListLink(item, active, extraData) {
  const link = document.createElement('a');
  link.href = '#';
  link.className = 'list-group-item list-group-item-action ' + extraData.className;
  if (active) link.classList.add('active');
  Object.keys(extraData.dataset || {}).forEach((key) => { link.dataset[key] = String(extraData.dataset[key] || ''); });
  const name = document.createTextNode(String(item.name || ''));
  const code = document.createElement('span');
  code.className = 'text-muted small ms-1';
  code.textContent = String(item.code || '');
  link.appendChild(name);
  link.appendChild(code);
  return link;
}

function renderL1List(modalEl, data, activeL1) {
  const pane = modalEl.querySelector('#scope-l1-pane');
  if (!pane) return;
  const group = document.createElement('div');
  group.className = 'list-group list-group-flush';
  (data.l1_list || []).forEach((l1) => {
    group.appendChild(buildListLink(l1, String(l1.id) === String(activeL1), {
      className: 'js-scope-l1-btn', dataset: { l1Id: l1.id }
    }));
  });
  pane.replaceChildren(group);
}

function renderL2List(modalEl, data, l1Id, activeL2) {
  const pane = modalEl.querySelector('#scope-l2-pane');
  if (!pane) return;
  const group = document.createElement('div');
  group.className = 'list-group list-group-flush';
  (data.l2_by_l1?.[l1Id] || []).forEach((l2) => {
    group.appendChild(buildListLink(l2, String(l2.id) === String(activeL2), {
      className: 'js-scope-l2-btn', dataset: { l1Id, l2Id: l2.id }
    }));
  });
  pane.replaceChildren(group);
}

function makeInput(type, className, value) {
  const input = document.createElement('input');
  input.type = type;
  input.className = className;
  if (type === 'number') input.step = '0.001';
  if (value !== undefined && value !== null) input.value = String(value);
  return input;
}

function renderTable(modalEl, data, l2Id) {
  const pane = modalEl.querySelector('#scope-table-pane');
  if (!pane) return;
  const wrapper = document.createElement('div');
  wrapper.className = 'table-responsive';
  const table = document.createElement('table');
  table.className = 'table table-sm align-middle mb-0';
  table.id = 'scope-table';

  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  [['사용', 'text-center'], ['업무(L3)', ''], ['단위', ''], ['설계 물량', 'text-end'], ['완료 물량', 'text-end']].forEach(([label, cls]) => {
    const th = document.createElement('th');
    th.className = cls;
    th.textContent = label;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  const rows = data.l3_by_l2?.[l2Id] || [];
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'text-center text-muted py-4';
    td.textContent = '항목 없음';
    tr.appendChild(td);
    tbody.appendChild(tr);
  } else {
    rows.forEach((row) => {
      const key = makeKey(l2Id, row.id);
      const picked = getScopeBuffer(modalEl)[key] || data.project_items?.[key] || {};
      const tr = document.createElement('tr');
      tr.dataset.l2Id = String(l2Id || '');
      tr.dataset.lv3Id = String(row.id || '');
      tr.dataset.unitDefault = String(row.unit_def || '');

      const activeTd = document.createElement('td');
      activeTd.className = 'text-center';
      const active = makeInput('checkbox', 'form-check-input js-scope-active');
      active.checked = !!picked.active;
      activeTd.appendChild(active);
      tr.appendChild(activeTd);

      const nameTd = document.createElement('td');
      const name = document.createElement('div');
      name.className = 'fw-semibold';
      name.textContent = String(row.name || '');
      const code = document.createElement('div');
      code.className = 'small text-muted';
      code.textContent = String(row.code || '');
      nameTd.appendChild(name);
      nameTd.appendChild(code);
      tr.appendChild(nameTd);

      const unitTd = document.createElement('td');
      unitTd.appendChild(makeInput('text', 'form-control form-control-sm js-scope-unit', picked.unit || row.unit_def || ''));
      tr.appendChild(unitTd);
      const designTd = document.createElement('td');
      designTd.appendChild(makeInput('number', 'form-control form-control-sm text-end js-scope-design', picked.design_qty || ''));
      tr.appendChild(designTd);
      const doneTd = document.createElement('td');
      doneTd.appendChild(makeInput('number', 'form-control form-control-sm text-end js-scope-completed', picked.completed_qty || ''));
      tr.appendChild(doneTd);
      tbody.appendChild(tr);
    });
  }
  table.appendChild(tbody);
  wrapper.appendChild(table);
  pane.replaceChildren(wrapper);
  hydrateDOMFromBuffer(modalEl);
  attachScopeRowToggleHandlers(modalEl);
  attachRowChangeBuffering(modalEl);
}

function initProjectScopeModal() {
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('#btn-scope-modal');
    if (!button) return;
    event.preventDefault();
    const projectId = button.dataset.projectId;
    const template = button.dataset.modalUrlTpl;
    if (!projectId || !template) return;
    try {
      const html = await fetchHtml(template.replace('00000000-0000-0000-0000-000000000000', projectId));
      const modalEl = replaceModalContent(html);
      modalEl.dataset.projectId = projectId;
      modalEl._scopeBuffer = {};
      modalEl._catalog = null;
      const data = await loadCatalogDataOnce(modalEl, projectId);
      const firstL1 = data.l1_list?.[0]?.id;
      const firstL2 = data.l2_by_l1?.[firstL1]?.[0]?.id;
      renderL1List(modalEl, data, firstL1);
      renderL2List(modalEl, data, firstL1, firstL2);
      renderTable(modalEl, data, firstL2);
      modalEl.onclick = (click) => {
        const l1 = click.target.closest('.js-scope-l1-btn');
        const l2 = click.target.closest('.js-scope-l2-btn');
        if (!l1 && !l2) return;
        click.preventDefault();
        seedBufferFromDOM(modalEl);
        if (l1) {
          const l1Id = l1.dataset.l1Id;
          const l2Id = modalEl._catalog.l2_by_l1?.[l1Id]?.[0]?.id;
          renderL1List(modalEl, modalEl._catalog, l1Id);
          renderL2List(modalEl, modalEl._catalog, l1Id, l2Id);
          renderTable(modalEl, modalEl._catalog, l2Id);
        } else {
          renderL2List(modalEl, modalEl._catalog, l2.dataset.l1Id, l2.dataset.l2Id);
          renderTable(modalEl, modalEl._catalog, l2.dataset.l2Id);
        }
      };
      attachScopeSaveHandler(projectId, modalEl);
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } catch (error) {
      console.error('scope modal failed', error);
      alert('업무범위를 불러오지 못했습니다.');
    }
  });
}

function attachScopeSaveHandler(projectId, modalEl) {
  const button = modalEl.querySelector('#btn-scope-save');
  if (!button) return;
  button.onclick = async () => {
    seedBufferFromDOM(modalEl);
    try {
      const response = await gfFetch(`/projects/${encodeURIComponent(projectId)}/scope-save/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
          'X-Requested-With': 'XMLHttpRequest'
        },
        credentials: 'same-origin',
        body: JSON.stringify({ items: Object.values(getScopeBuffer(modalEl)) })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error('save failed');
      location.reload();
    } catch (error) {
      console.error('scope save failed', error);
      alert('저장에 실패했습니다.');
    }
  };
}

function applyScopeRowDisabledState(tr) {
  const active = tr.querySelector('.js-scope-active');
  if (!active) return;
  const disabled = !active.checked;
  const unit = tr.querySelector('.js-scope-unit');
  const design = tr.querySelector('.js-scope-design');
  const completed = tr.querySelector('.js-scope-completed');
  if (unit) {
    if (!disabled && !unit.value && tr.dataset.unitDefault) unit.value = tr.dataset.unitDefault;
    unit.disabled = disabled;
  }
  if (design) design.disabled = disabled;
  if (completed) completed.disabled = disabled;
}

function attachScopeRowToggleHandlers(modalEl) {
  modalEl.querySelectorAll('#scope-table tbody tr').forEach((tr) => {
    const active = tr.querySelector('.js-scope-active');
    if (!active) return;
    applyScopeRowDisabledState(tr);
    active.addEventListener('change', () => applyScopeRowDisabledState(tr));
  });
}

function initProjectSummaryModal() {
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('#btn-summary-modal');
    if (!button) return;
    event.preventDefault();
    const projectId = button.dataset.projectId;
    const template = button.dataset.modalUrlTpl;
    if (!projectId || !template) return;
    try {
      const html = await fetchHtml(template.replace('00000000-0000-0000-0000-000000000000', projectId));
      const modalEl = replaceModalContent(html);
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } catch (error) {
      console.error('summary modal failed', error);
      alert('요약 화면을 불러오지 못했습니다.');
    }
  });
}

document.addEventListener('submit', async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.id !== 'summaryForm') return;
  event.preventDefault();
  try {
    const response = await gfFetch(form.action, {
      method: 'POST', body: new FormData(form),
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin', redirect: 'follow'
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const modalEl = document.querySelector('#projectSummaryModal');
    if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    location.reload();
  } catch (error) {
    console.error('summary save failed', error);
    alert('저장에 실패했습니다.');
  }
}, true);

document.addEventListener('DOMContentLoaded', () => {
  initProjectScopeModal();
  initProjectSummaryModal();
});
