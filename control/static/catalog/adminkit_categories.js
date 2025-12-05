(function () {
  function $(s, r = document) { return r.querySelector(s); }
  function el(tag, attrs = {}, ...children) {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'class') n.className = v;
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2).toLowerCase(), v);
      else n.setAttribute(k, v);
    });
    children.forEach(c => n.append(c));
    return n;
  }
  async function getJSON(url) {
    const r = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    return r.json();
  }
  function getCsrfToken() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(body || {})
    });
    return r.json();
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const root = $('#cat-root');
    if (!root) return;

    const L1_URL = root.dataset.l1Url;
    const L2_URL = root.dataset.l2Url;
    const MAPPED_FACETS_URL = root.dataset.mappedFacetsUrl;
    const FACET_OPTIONS_URL = root.dataset.facetOptionsUrl;

    const NODE_LINKS_URL_T = root.dataset.nodeLinksUrlTemplate;
    const NODE_LINKS_CREATE_URL_T = root.dataset.nodeLinksCreateUrlTemplate;
    const RULES_LIST_URL_T = root.dataset.rulesListUrlTemplate;
    const RULES_MATRIX_URL_T = root.dataset.rulesMatrixUrlTemplate;
    const RULES_MATRIX_PATCH_URL_T = root.dataset.rulesMatrixPatchUrlTemplate;
    const L1_EDIT_URL_T = root.dataset.l1EditUrlTemplate;

    function pathWith(tpl, id) {
      return (tpl || '').replace('00000000-0000-0000-0000-000000000000', id);
    }

    const table = $('#l1-table');
    const tbody = table.querySelector('tbody');
    const ocEl = $('#oc-l2');
    let bsOffcanvas = null;
    function ensureOffcanvas() {
      if (!ocEl) return null;
      if (window.bootstrap && window.bootstrap.Offcanvas) {
        if (!bsOffcanvas) bsOffcanvas = window.bootstrap.Offcanvas.getOrCreateInstance(ocEl);
        return bsOffcanvas;
      }
      // Fallback: 부트스트랩 JS가 아직 없어도 패널을 보이게 처리
      ocEl.classList.add('show');
      ocEl.style.visibility = 'visible';
      ocEl.style.transform = 'none';
      return { show(){}, hide(){ ocEl.classList.remove('show'); } };
    }

    const l2Caption = $('#l2-caption');
    const l2ListEl = $('#l2-list');
    const btnNodeLinks = $('#btn-open-node-links');
    const btnAddOptionSet = $('#btn-add-option-set');
    const modalEl = $('#modalAddFacet');
    let bsModal = null;
    function ensureModal() {
    if (!modalEl) return null;
    if (!window.bootstrap || !window.bootstrap.Modal) return null;
    if (!bsModal) bsModal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
    return bsModal;
    }
    const afLevel = $('#af-level');
    const afFacet = $('#af-facet');

    const btnOpenRulesList = $('#btn-open-rules-list');
    const btnRulesAllowAll = $('#btn-rules-allow-all');
    const btnRulesClear    = $('#btn-rules-clear');

    const rulesHint = $('#rules-hint');
    const rulesWrap = $('#rules-matrix-wrap');
    const rulesTable = $('#rules-matrix');

    let currentL1 = null;
    let currentL2 = null;

    // L1 목록
    async function loadL1() {
      tbody.innerHTML = `<tr><td colspan="4" class="text-muted">불러오는 중…</td></tr>`;
      const j = await getJSON(L1_URL);
      if (!j.ok) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-danger">L1 로드 실패</td></tr>`;
        return;
      }
      if (!j.results.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-muted">등록된 L1이 없습니다.</td></tr>`;
        return;
      }
      tbody.innerHTML = '';
      j.results.forEach((item, idx) => {
        const tr = el('tr', {},
          el('td', {}, String(idx + 1)),
          el('td', {}, item.code || '-'),
          el('td', {}, item.name || ''),
          el('td', { class: 'text-center' },
            el('div', { class: 'btn-group btn-group-sm' },
              el('a', { class: 'btn btn-outline-secondary', href: pathWith(L1_EDIT_URL_T, item.id), title: 'L1 수정' }, '수정'),
              el('button', { type:'button', class: 'btn btn-primary btn-manage', onClick: () => openL2Panel(item) }, '관리')
            )
          )
        );
        tbody.append(tr);
      });
    }

    // L2 오프캔버스 열기
    async function openL2Panel(l1) {
      currentL1 = l1;
      l2Caption.textContent = `기준 L1: ${l1.name || l1.code || ''}`;
      l2ListEl.innerHTML = `<li class="list-group-item text-muted">불러오는 중…</li>`;
      btnNodeLinks.removeAttribute('href');

      const u = new URL(L2_URL, window.location.origin);
      u.searchParams.set('l1_id', l1.id);
      const j = await getJSON(u.toString());

      if (!j.ok) {
        l2ListEl.innerHTML = `<li class="list-group-item text-danger">L2 로드 실패</li>`;
      } else if (!j.results.length) {
        l2ListEl.innerHTML = `<li class="list-group-item text-muted">연결된 L2가 없습니다.</li>`;
      } else {
        l2ListEl.innerHTML = '';
        j.results.forEach(l2 => {
          const li = el('li', { class: 'list-group-item d-flex justify-content-between align-items-center' },
            el('div', {},
              el('div', { class: 'fw-semibold' }, l2.name || ''),
              el('div', { class: 'text-muted small' }, l2.code ? `코드: ${l2.code}` : '')
            ),
            el('div', { class: 'btn-group btn-group-sm' },
              el('a', { class: 'btn btn-outline-secondary',
                        href: pathWith(NODE_LINKS_URL_T, l2.id),
                        title: 'L2 연결 관리' }, '수정'),
              el('button', { type:'button', class: 'btn btn-primary', onClick: () => selectL2(l2) }, '설정')
            )
          );
          l2ListEl.append(li);
        });
      }
      const oc = ensureOffcanvas();
      if (oc) oc.show();
    }

    // L2 선택 → 탭 데이터 로드
    async function selectL2(l2) {
      currentL2 = l2;
      btnNodeLinks.href = pathWith(NODE_LINKS_URL_T, l2.id);
      btnAddOptionSet.href = pathWith(NODE_LINKS_CREATE_URL_T, l2.id);
      btnOpenRulesList.href = pathWith(RULES_LIST_URL_T, l2.id);

      await renderMappedFacets(l2);
      await renderRulesMatrix(l2);
      // 빠른 추가 버튼 핸들러 바인딩(중복 방지 위해 매번 최신 컨텍스트로)
      btnAddOptionSet.onclick = (e) => { e.preventDefault(); openAddFacetModal(); };
      // 일괄 버튼 바인딩
      if (btnRulesAllowAll) btnRulesAllowAll.onclick = () => bulkAllowAll();
      if (btnRulesClear)    btnRulesClear.onclick    = () => bulkClearAll();
    }

    // 탭 A: 옵션팩 연결 표시
    async function renderMappedFacets(l2) {
      const lv3 = $('#facet-list-lv3');
      const lv4 = $('#facet-list-lv4');
      lv3.innerHTML = `<li class="list-group-item text-muted">불러오는 중…</li>`;
      lv4.innerHTML = `<li class="list-group-item text-muted">불러오는 중…</li>`;

      const u = new URL(MAPPED_FACETS_URL, window.location.origin);
      u.searchParams.set('l2_id', l2.id);
      const j = await getJSON(u.toString());

      lv3.innerHTML = ''; lv4.innerHTML = '';
      if (!j.ok || !j.results) {
        lv3.innerHTML = `<li class="list-group-item text-danger">조회 실패</li>`;
        lv4.innerHTML = `<li class="list-group-item text-danger">조회 실패</li>`;
        return;
      }

      const list3 = j.results.filter(x => x.level_no === 3);
      const list4 = j.results.filter(x => x.level_no === 4);

      if (!list3.length) lv3.innerHTML = `<li class="list-group-item text-muted">연결된 L3 옵션팩 없음</li>`;
      if (!list4.length) lv4.innerHTML = `<li class="list-group-item text-muted">연결된 L4 옵션팩 없음</li>`;

      const linkBtn = (href) => el('a', { class: 'btn btn-sm btn-outline-secondary', href, target: '_blank', rel: 'noopener' }, '관리');

      list3.forEach(x => {
        const li = el('li', { class: 'list-group-item d-flex justify-content-between align-items-center' },
          el('span', {}, `${x.facet.name} (${x.facet.code})`),
          el('div', { class: 'btn-group btn-group-sm' },
                linkBtn(btnNodeLinks.href),
                el('button', { class:'btn btn-outline-secondary', onClick: () => quickMoveSet(x.set_id, 'up') }, '▲'),
                el('button', { class:'btn btn-outline-secondary', onClick: () => quickMoveSet(x.set_id, 'down') }, '▼'),
                el('button', { class:'btn btn-outline-danger', onClick: () => quickDeleteSet(x.set_id) }, '삭제')
            )
        );
        lv3.append(li);
      });
      list4.forEach(x => {
        const li = el('li', { class: 'list-group-item d-flex justify-content-between align-items-center' },
            el('span', {}, `${x.facet.name} (${x.facet.code})`),
            el('div', { class: 'btn-group btn-group-sm' },
                linkBtn(btnNodeLinks.href),
                el('button', { class:'btn btn-outline-secondary', onClick: () => quickMoveSet(x.set_id, 'up') }, '▲'),
                el('button', { class:'btn btn-outline-secondary', onClick: () => quickMoveSet(x.set_id, 'down') }, '▼'),
                el('button', { class:'btn btn-outline-danger', onClick: () => quickDeleteSet(x.set_id) }, '삭제')
            )
        );
        lv4.append(li);
      });
    }

    // ── 순서 이동
    async function quickMoveSet(setId, dir) {
      const url = root.dataset.optionSetMoveUrlTemplate.replace('00000000-0000-0000-0000-000000000000', setId);
      const res = await postJSON(url, { dir });
      if (!res.ok) { alert(res.error || '이동 실패'); return; }
      await renderMappedFacets(currentL2);
    }

    // ── 규칙 일괄 처리
    async function bulkAllowAll() {
      if (!currentL2) return;
      const url = root.dataset.rulesAllowAllUrlTemplate.replace('00000000-0000-0000-0000-000000000000', currentL2.id);
      const res = await postJSON(url, {});
      if (!res.ok) { alert(res.error || '실패'); return; }
      await renderRulesMatrix(currentL2);
    }
    async function bulkClearAll() {
      if (!currentL2) return;
      const url = root.dataset.rulesClearUrlTemplate.replace('00000000-0000-0000-0000-000000000000', currentL2.id);
      const res = await postJSON(url, {});
      if (!res.ok) { alert(res.error || '실패'); return; }
      await renderRulesMatrix(currentL2);
    }

    // ───────── 빠른 추가 모달
    async function openAddFacetModal() {
        if (!currentL2) return;
        afLevel.value = '3';
        await reloadAvailableFacets();
        const m = ensureModal();
        if (m) m.show();
    }
    afLevel?.addEventListener('change', reloadAvailableFacets);
    async function reloadAvailableFacets() {
        if (!currentL2) return;
        const url = new URL(root.dataset.availableFacetsUrlTemplate.replace('00000000-0000-0000-0000-000000000000', currentL2.id), window.location.origin);
        url.searchParams.set('level_no', afLevel.value);
        const j = await getJSON(url.toString());
        afFacet.innerHTML = '';
        if (!j.ok || !j.results.length) {
            afFacet.innerHTML = `<option value="">선택 가능 항목 없음</option>`;
            return;
        }
        j.results.forEach(f => {
            const o = document.createElement('option');
            o.value = f.id; o.textContent = `${f.name} (${f.code || '-'})`;
            afFacet.append(o);
        });
    }
    $('#af-submit')?.addEventListener('click', async () => {
        if (!currentL2) return;
        const facetId = afFacet.value;
        const levelNo = parseInt(afLevel.value, 10);
        if (!facetId) return;
        const url = root.dataset.optionSetAddUrlTemplate.replace('00000000-0000-0000-0000-000000000000', currentL2.id);
        const res = await postJSON(url, { level_no: levelNo, facet_id: facetId });
        if (!res.ok) { alert(res.error || '추가 실패'); return; }
        ensureModal()?.hide();
        await renderMappedFacets(currentL2);
        await renderRulesMatrix(currentL2);
    });

    // ───────── 빠른 삭제
    async function quickDeleteSet(setId) {
        if (!currentL2) return;
        const url = root.dataset.optionSetDeleteUrlTemplate.replace('00000000-0000-0000-0000-000000000000', setId);
        const res = await postJSON(url, {}); // DELETE를 쓰고 싶으면 fetch로 method:'DELETE' 적용
        if (!res.ok) { alert(res.error || '삭제 실패'); return; }
        await renderMappedFacets(currentL2);
        await renderRulesMatrix(currentL2);
    }

    // 탭 B: 규칙 매트릭스 표시/토글
    async function renderRulesMatrix(l2) {
      rulesHint.style.display = '';
      rulesWrap.style.display = 'none';
      rulesTable.querySelector('thead').innerHTML = '';
      rulesTable.querySelector('tbody').innerHTML = '';

      const url = RULES_MATRIX_URL_T.replace('00000000-0000-0000-0000-000000000000', l2.id);
      const j = await getJSON(url);
      if (!j.ok) {
        rulesHint.className = 'alert alert-danger';
        rulesHint.textContent = '규칙 정보를 불러오지 못했습니다.';
        return;
      }
      if (!j.l3_facet || !j.l4_facet) {
        rulesHint.className = 'alert alert-info';
        rulesHint.textContent = 'L3/L4 옵션팩을 먼저 연결해주세요.';
        return;
      }

      const thead = rulesTable.querySelector('thead');
      const hRow = el('tr', {});
      hRow.append(el('th', {}, `${j.l3_facet.name} ▼ / ${j.l4_facet.name} ▶`));
      j.l4_options.forEach(o4 => hRow.append(el('th', { 'data-o4': o4.id }, `${o4.name}`)));
      thead.append(hRow);

      const allowedSet = new Set((j.allowed || []).map(pair => pair.join('|')));

      const tbodyM = rulesTable.querySelector('tbody');
      j.l3_options.forEach(o3 => {
        const tr = el('tr', {});
        tr.append(el('th', {}, `${o3.name}`));
        j.l4_options.forEach(o4 => {
          const key = `${o3.id}|${o4.id}`;
          const allowed = allowedSet.has(key);
          const td = el('td', {
            class: `matrix-cell ${allowed ? 'cell-allowed' : 'cell-denied'}`,
            'data-o3': o3.id,
            'data-o4': o4.id,
            onClick: () => toggleRuleCell(td)
          }, allowed ? '✔' : '');
          tr.append(td);
        });
        tbodyM.append(tr);
      });

      rulesHint.style.display = 'none';
      rulesWrap.style.display = '';
    }

    async function toggleRuleCell(td) {
      if (!currentL2) return;
      const o3 = td.getAttribute('data-o3');
      const o4 = td.getAttribute('data-o4');
      const nowAllowed = td.classList.contains('cell-allowed');

      const url = RULES_MATRIX_PATCH_URL_T.replace('00000000-0000-0000-0000-000000000000', currentL2.id);
      const payload = nowAllowed
        ? { allow: [], disallow: [[o3, o4]] }
        : { allow: [[o3, o4]], disallow: [] };

      const res = await postJSON(url, payload);
      if (!res.ok) {
        alert('저장 실패');
        return;
      }
      td.classList.toggle('cell-allowed', !nowAllowed);
      td.classList.toggle('cell-denied',  nowAllowed);
      td.textContent = !nowAllowed ? '✔' : '';
    }

    await loadL1();
  });
})();
