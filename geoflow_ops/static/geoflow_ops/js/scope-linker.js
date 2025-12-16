/* scope-linker.js — preload JSON once, client render, buffer persist */

// ===== Global Spinner helper =====
const GFSpinner = (() => {
  const el = document.getElementById("globalSpinner");
  let depth = 0; // 중첩 호출 대비
  const show = () => { if (!el) return; depth++; el.classList.remove("d-none"); };
  const hide = () => { if (!el) return; depth = Math.max(0, depth-1); if (depth === 0) el.classList.add("d-none"); };
  return { show, hide };
})();

// ===== fetch wrapper with spinner =====
async function gfFetch(url, opts={}){
  GFSpinner.show();
  try{
    const resp = await fetch(url, opts);
    return resp;
  }finally{
    GFSpinner.hide();
  }
}

function $(sel, root) { return (root || document).querySelector(sel); }
async function fetchHtml(url) {
  const r = await gfFetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
  return await r.text();
}
function ensureScopeModal() {
  let el = document.getElementById("scopeModal");
  if (el) return el;
  el = document.createElement("div");
  el.id = "scopeModal";
  el.className = "modal fade";
  el.tabIndex = -1;
  el.innerHTML = `
    <div class="modal-dialog modal-xl modal-dialog-scrollable">
      <div class="modal-content"></div>
    </div>`;
  document.body.appendChild(el);
  return el;
}
function replaceModalContent(html) {
  const modalEl = ensureScopeModal();
  const content = modalEl.querySelector(".modal-content");
  if (content) content.innerHTML = html;
  return modalEl;
}
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
}

/* ---------- buffer ---------- */
function getScopeBuffer(modalEl) {
  if (!modalEl._scopeBuffer) modalEl._scopeBuffer = {};
  return modalEl._scopeBuffer;
}
function makeKey(l2, lv3) { return `${l2}|${lv3}`; }
function seedBufferFromDOM(modalEl) {
  const buf = getScopeBuffer(modalEl);
  const rows = modalEl.querySelectorAll("#scope-table tbody tr");
  rows.forEach(tr => {
    const lv2 = tr.getAttribute("data-l2-id");
    const lv3 = tr.getAttribute("data-lv3-id");
    if (!lv2 || !lv3) return;
    const k = makeKey(lv2, lv3);
    const active = tr.querySelector(".js-scope-active")?.checked || false;
    const unit = tr.querySelector(".js-scope-unit")?.value || "";
    const design_qty = tr.querySelector(".js-scope-design")?.value || "";
    const completed_qty = tr.querySelector(".js-scope-completed")?.value || "";
    buf[k] = { lv2_id: lv2, lv3_id: lv3, active, unit, design_qty, completed_qty };
  });
}
function hydrateDOMFromBuffer(modalEl) {
  const buf = getScopeBuffer(modalEl);
  const rows = modalEl.querySelectorAll("#scope-table tbody tr");
  rows.forEach(tr => {
    const lv2 = tr.getAttribute("data-l2-id");
    const lv3 = tr.getAttribute("data-lv3-id");
    if (!lv2 || !lv3) return;
    const k = makeKey(lv2, lv3);
    const cached = buf[k];
    const chk = tr.querySelector(".js-scope-active");
    const unitEl = tr.querySelector(".js-scope-unit");
    const designEl = tr.querySelector(".js-scope-design");
    const completedEl = tr.querySelector(".js-scope-completed");
    if (cached) {
      if (chk) chk.checked = !!cached.active;
      if (unitEl) unitEl.value = cached.unit || unitEl.value || tr.getAttribute("data-unit-default") || "";
      if (designEl) designEl.value = cached.design_qty || designEl.value || "";
      if (completedEl) completedEl.value = cached.completed_qty || completedEl.value || "";
    }
    applyScopeRowDisabledState(tr);
  });
}
function attachRowChangeBuffering(modalEl) {
  const buf = getScopeBuffer(modalEl);
  modalEl.querySelectorAll("#scope-table tbody tr").forEach(tr => {
    const lv2 = tr.getAttribute("data-l2-id");
    const lv3 = tr.getAttribute("data-lv3-id");
    if (!lv2 || !lv3) return;
    const k = makeKey(lv2, lv3);
    const inputs = tr.querySelectorAll(".js-scope-active, .js-scope-unit, .js-scope-design, .js-scope-completed");
    inputs.forEach(el => {
      const evt = el.classList.contains("js-scope-active") ? "change" : "input";
      el.addEventListener(evt, () => {
        const active = tr.querySelector(".js-scope-active")?.checked || false;
        const unit = tr.querySelector(".js-scope-unit")?.value || "";
        const design_qty = tr.querySelector(".js-scope-design")?.value || "";
        const completed_qty = tr.querySelector(".js-scope-completed")?.value || "";
        buf[k] = { lv2_id: lv2, lv3_id: lv3, active, unit, design_qty, completed_qty };
        if (el.classList.contains("js-scope-active")) applyScopeRowDisabledState(tr);
      });
    });
  });
}

/* ---------- client render helpers ---------- */
async function loadCatalogDataOnce(modalEl, projectId) {
  if (modalEl._catalog) return modalEl._catalog;
  const resp = await gfFetch(`/projects/${projectId}/scope-data/`, {
    headers: { "X-Requested-With": "XMLHttpRequest" },
    credentials: "same-origin",
  });
  const data = await resp.json();
  modalEl._catalog = data;
  return data;
}
function renderL1List(modalEl, data, activeL1) {
  const pane = modalEl.querySelector("#scope-l1-pane");
  pane.innerHTML = `<div class="list-group list-group-flush">
    ${data.l1_list.map(l1 => `
      <a href="#" class="list-group-item list-group-item-action js-scope-l1-btn ${l1.id===activeL1?'active':''}" data-l1-id="${l1.id}">
        ${l1.name} <span class="text-muted small">${l1.code||''}</span>
      </a>`).join("")}
  </div>`;
}
function renderL2List(modalEl, data, l1Id, activeL2) {
  const pane = modalEl.querySelector("#scope-l2-pane");
  const l2s = data.l2_by_l1[l1Id] || [];
  pane.innerHTML = `<div class="list-group list-group-flush">
    ${l2s.map(l2 => `
      <a href="#" class="list-group-item list-group-item-action js-scope-l2-btn ${l2.id===activeL2?'active':''}"
         data-l1-id="${l1Id}" data-l2-id="${l2.id}">
        ${l2.name} <span class="text-muted small">${l2.code||''}</span>
      </a>`).join("")}
  </div>`;
}
function renderTable(modalEl, data, l2Id) {
  const pane = modalEl.querySelector("#scope-table-pane");
  const rows = data.l3_by_l2[l2Id] || [];
  const tr = rows.map(r => {
    const key = `${l2Id}|${r.id}`;
    const picked = (getScopeBuffer(modalEl)[key]) || data.project_items[key] || {};
    const active = picked.active ? 'checked' : '';
    const unit = picked.unit || r.unit_def || '';
    const design = picked.design_qty || '';
    const done = picked.completed_qty || '';
    return `
      <tr data-l2-id="${l2Id}" data-lv3-id="${r.id}" data-unit-default="${r.unit_def||''}">
        <td class="text-center"><input type="checkbox" class="form-check-input js-scope-active" ${active}></td>
        <td>
          <div class="fw-semibold">${r.name}</div>
          <div class="small text-muted">${r.code||''}</div>
        </td>
        <td><input type="text" class="form-control form-control-sm js-scope-unit" value="${unit}"></td>
        <td><input type="number" step="0.001" class="form-control form-control-sm text-end js-scope-design" value="${design}"></td>
        <td><input type="number" step="0.001" class="form-control form-control-sm text-end js-scope-completed" value="${done}"></td>
      </tr>`;
  }).join("");
  pane.innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm align-middle mb-0" id="scope-table">
        <thead>
          <tr>
            <th class="text-center" style="width:70px;">사용</th>
            <th>업무(L3)</th>
            <th style="width:120px;">단위</th>
            <th style="width:160px;" class="text-end">설계 물량</th>
            <th style="width:160px;" class="text-end">완료 물량</th>
          </tr>
        </thead>
        <tbody>${tr || `<tr><td colspan="5" class="text-center text-muted py-4">항목 없음</td></tr>`}</tbody>
      </table>
    </div>`;
  hydrateDOMFromBuffer(modalEl);
  attachScopeRowToggleHandlers();
  attachRowChangeBuffering(modalEl);
}

/* ---------- modal open (preload once) ---------- */
function initProjectScopeModal() {
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("#btn-scope-modal");
    if (!btn) return; e.preventDefault();

    const pid = btn.dataset.projectId;
    const tpl = btn.dataset.modalUrlTpl;
    if (!pid || !tpl) return;

    const baseUrl = tpl.replace("00000000-0000-0000-0000-000000000000", pid);
    const html = await fetchHtml(baseUrl);
    const modalEl = replaceModalContent(html);
    modalEl.dataset.projectId = pid;
    modalEl._scopeBuffer = {};

    // JSON 1회 프리로드
    const data = await loadCatalogDataOnce(modalEl, pid);

    // 초기 선택
    const firstL1 = (data.l1_list[0] || {}).id;
    const firstL2 = ((data.l2_by_l1[firstL1] || [])[0] || {}).id;

    renderL1List(modalEl, data, firstL1);
    renderL2List(modalEl, data, firstL1, firstL2);
    renderTable(modalEl, data, firstL2);

    // L1/L2 전환(서버 왕복 없음)
    modalEl.addEventListener("click", (ev) => {
      const l1a = ev.target.closest(".js-scope-l1-btn");
      const l2a = ev.target.closest(".js-scope-l2-btn");
      if (!l1a && !l2a) return;
      ev.preventDefault();

      // 전환 직전 현재 DOM → 버퍼 반영
      seedBufferFromDOM(modalEl);

      const cur = modalEl._catalog;
      if (l1a) {
        const l1 = l1a.dataset.l1Id;
        const l2 = ((cur.l2_by_l1[l1] || [])[0] || {}).id;
        renderL1List(modalEl, cur, l1);
        renderL2List(modalEl, cur, l1, l2);
        renderTable(modalEl, cur, l2);
      } else if (l2a) {
        const l1 = l2a.dataset.l1Id;
        const l2 = l2a.dataset.l2Id;
        renderL2List(modalEl, cur, l1, l2);
        renderTable(modalEl, cur, l2);
      }
    });

    attachScopeSaveHandler(pid, modalEl);
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  });
}

/* ---------- save ---------- */
function collectItemsFromBuffer(modalEl) {
  const buf = getScopeBuffer(modalEl);
  return Object.values(buf || {});
}
function attachScopeSaveHandler(projectId, modalEl) {
  const btn = document.getElementById("btn-scope-save");
  if (!btn) return;
  btn.onclick = async () => {
    try {
      seedBufferFromDOM(modalEl);
      const items = collectItemsFromBuffer(modalEl);
      const csrftoken = getCookie("csrftoken");

      const resp = await gfFetch(`/projects/${projectId}/scope-save/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrftoken,
          "X-Requested-With": "XMLHttpRequest",
        },
        credentials: "same-origin",
        body: JSON.stringify({ items }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.ok) {
        console.error("scope-save failed:", data);
        alert("저장 실패: " + (data.error || resp.status));
        return;
      }
      alert("업무범위를 저장했습니다.");
      location.reload();
    } catch (err) {
      console.error(err);
      alert("서버 오류로 저장에 실패했습니다.");
    }
  };
}

/* ---------- row enable/disable ---------- */
function applyScopeRowDisabledState(tr) {
  const chk = tr.querySelector(".js-scope-active");
  if (!chk) return;
  const disabled = !chk.checked;

  const unitEl = tr.querySelector(".js-scope-unit");
  const designEl = tr.querySelector(".js-scope-design");
  const completedEl = tr.querySelector(".js-scope-completed");

  if (unitEl) {
    if (!disabled && !unitEl.value) {
      const defUnit = tr.getAttribute("data-unit-default");
      if (defUnit) unitEl.value = defUnit;
    }
    unitEl.disabled = disabled;
  }
  if (designEl) designEl.disabled = disabled;
  if (completedEl) completedEl.disabled = disabled;
}
function attachScopeRowToggleHandlers() {
  const rows = document.querySelectorAll("#scope-table tbody tr");
  rows.forEach(tr => {
    const chk = tr.querySelector(".js-scope-active");
    if (!chk) return;
    applyScopeRowDisabledState(tr);
    chk.addEventListener("change", () => applyScopeRowDisabledState(tr));
  });
}

// ▼ 추가: 요약(현재 업무 편집) 모달 오픈
function initProjectSummaryModal() {
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("#btn-summary-modal");
    if (!btn) return;
    e.preventDefault();

    const pid = btn.dataset.projectId;
    const tpl = btn.dataset.modalUrlTpl;
    if (!pid || !tpl) return;

    const url = tpl.replace("00000000-0000-0000-0000-000000000000", pid);
    const html = await fetchHtml(url);                 // 서버에서 project_summary.html 조각 수신
    const modalEl = replaceModalContent(html);         // #scopeModal .modal-content 교체
    bootstrap.Modal.getOrCreateInstance(modalEl).show(); // 모달 표시
  });
}

// 전역 캡처: 모달 편집 폼(#summaryForm) 제출을 항상 AJAX로 처리
document.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.id !== "summaryForm") return;

  e.preventDefault(); // ← 브라우저 네비게이션(302 따라가기) 차단

  try {
    const fd = new FormData(form);
    const resp = await gfFetch(form.action, {
      method: "POST",
      body: fd,
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      redirect: "follow",
    });
    if (!resp.ok) {
      alert("저장 실패(" + resp.status + ")");
      return;
    }
  } catch (err) {
    console.error("summary save error:", err);
    alert("저장 중 오류가 발생했어요.");
    return;
  }

  // 성공: 모달 닫고 화면 새로고침(또는 요약 카드만 갱신)
  const modalEl = document.querySelector("#projectSummaryModal");
  if (modalEl) {
    const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
    inst.hide();
  }
  location.reload(); // 필요하면 여기만 부분갱신으로 바꿔도 됨
}, true);

/* ---------- init ---------- */
document.addEventListener("DOMContentLoaded", () => {
  initProjectScopeModal();
  initProjectSummaryModal();
});
