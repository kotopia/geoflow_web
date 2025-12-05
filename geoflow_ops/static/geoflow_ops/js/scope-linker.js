// scope-linker.js (통합판)
// - 계약 상세: #scopeMount[data-project] 가 있으면 summary HTML 주입
// - 프로젝트 상세: #btn-scope-modal / #scopeModal 존재 시 모달 로드/버퍼/저장
(function(){
  /* ─────────────────────────────────────────
   *  공통: 계약 상세에서 요약 HTML 주입 (기존 네가 올린 코드)
   * ───────────────────────────────────────── */
  function mountScopeIntoContract() {
    var mnt = document.getElementById("scopeMount");
    if (!mnt) return;
    var pid = mnt.dataset.project;
    if (!pid) return;

    var url = mnt.dataset.url || ("/projects/" + pid + "/scope-summary/");
    fetch(url, {headers: {"X-Requested-With":"XMLHttpRequest"}})
      .then(function(r){ return r.text(); })
      .then(function(html){ mnt.innerHTML = html; })
      .catch(function(err){
        console.error("scope summary load failed:", err);
        mnt.innerHTML = '<div class="text-muted small">업무범위를 불러오지 못했습니다.</div>';
      });
  }

  /* ─────────────────────────────────────────
   *  프로젝트 상세 전용: 모달 로드/버퍼/저장
   * ───────────────────────────────────────── */
  // CSRF 쿠키
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  }

  // 스위치 ON/OFF 에 따라 단위/물량 입력칸 활성/비활성
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

  // 행마다 스위치 토글 핸들러 연결
  function attachScopeRowToggleHandlers() {
    const rows = document.querySelectorAll("#scope-table tbody tr");
    rows.forEach(tr => {
      const chk = tr.querySelector(".js-scope-active");
      if (!chk) return;
      applyScopeRowDisabledState(tr);             // 초기 반영
      chk.addEventListener("change", () => applyScopeRowDisabledState(tr));
    });
  }

  // 🔹 L2별 상태를 기억하기 위한 전역 버퍼
  // scopeBuffer = { [lv2Id]: { [lv3Id]: { active, unit, design_qty, completed_qty } } }
  let scopeBuffer = {};

  // 현재 모달 테이블 상태를 버퍼에 저장
  function snapshotScopeTableToBuffer() {
    const table = document.getElementById("scope-table");
    if (!table) return;
    const rows = table.querySelectorAll("tbody tr");
    rows.forEach(tr => {
      const lv2Id = tr.getAttribute("data-l2-id");
      const lv3Id = tr.getAttribute("data-lv3-id");
      if (!lv2Id || !lv3Id) return;

      const chk = tr.querySelector(".js-scope-active");
      const unitEl = tr.querySelector(".js-scope-unit");
      const designEl = tr.querySelector(".js-scope-design");
      const completedEl = tr.querySelector(".js-scope-completed");

      if (!scopeBuffer[lv2Id]) scopeBuffer[lv2Id] = {};
      scopeBuffer[lv2Id][lv3Id] = {
        active: chk ? chk.checked : false,
        unit: unitEl ? unitEl.value : "",
        design_qty: designEl ? designEl.value : "",
        completed_qty: completedEl ? completedEl.value : "",
      };
    });
  }

  // 버퍼에 저장된 값을 현재 테이블에 적용
  function applyScopeBufferToTable() {
    const table = document.getElementById("scope-table");
    if (!table) return;
    const rows = table.querySelectorAll("tbody tr");
    rows.forEach(tr => {
      const lv2Id = tr.getAttribute("data-l2-id");
      const lv3Id = tr.getAttribute("data-lv3-id");
      if (!lv2Id || !lv3Id) return;

      const byL2 = scopeBuffer[lv2Id];
      const buf = byL2 ? byL2[lv3Id] : null;
      if (!buf) return;

      const chk = tr.querySelector(".js-scope-active");
      const unitEl = tr.querySelector(".js-scope-unit");
      const designEl = tr.querySelector(".js-scope-design");
      const completedEl = tr.querySelector(".js-scope-completed");

      if (chk) chk.checked = !!buf.active;
      if (unitEl && buf.unit != null) unitEl.value = buf.unit;
      if (designEl && buf.design_qty != null) designEl.value = buf.design_qty;
      if (completedEl && buf.completed_qty != null) completedEl.value = buf.completed_qty;
    });
  }

  // 모달 저장 핸들러(전체 버퍼 전송)
  function attachScopeSaveHandler(projectId) {
    const saveBtn = document.getElementById("btn-scope-save");
    if (!saveBtn) return;
    saveBtn.onclick = () => {
      snapshotScopeTableToBuffer();
      const items = [];
      Object.entries(scopeBuffer).forEach(([lv2Id, byLv3]) => {
        Object.entries(byLv3).forEach(([lv3Id, r]) => {
          items.push({
            lv2_id: lv2Id,
            lv3_id: lv3Id,
            active: !!r.active,
            unit: r.unit || "",
            design_qty: r.design_qty || null,
            completed_qty: r.completed_qty || null,
          });
        });
      });
      const csrftoken = getCookie("csrftoken");
      fetch(`/projects/${projectId}/scope-save/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrftoken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({items}),
      })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) {
          alert("저장 실패: " + (data.error || "알 수 없는 오류"));
          return;
        }
        alert("업무범위를 저장했습니다.");
        location.reload();
      })
      .catch(err => {
        console.error(err);
        alert("서버 오류로 저장에 실패했습니다.");
      });
    };
  }

  // 프로젝트 상세: 모달 로더
  function initProjectScopeModal() {
    const scopeBtn = document.getElementById("btn-scope-modal");
    const scopeModalEl = document.getElementById("scopeModal");
    if (!scopeBtn || !scopeModalEl) return;

    const projectId = scopeBtn.dataset.projectId || "";
    if (!projectId) return;

    // Django reverse 템플릿(더미 UUID)을 실제로 치환
    const baseTpl = scopeBtn.dataset.modalUrlTpl; // 템플릿에서 data-modal-url-tpl 로 내려주기 권장
    const scopeBaseUrlTemplate = baseTpl || "/projects/00000000-0000-0000-0000-000000000000/scope-modal/";

    function loadScopeModal(extraQuery) {
      snapshotScopeTableToBuffer();
      let url = scopeBaseUrlTemplate.replace("00000000-0000-0000-0000-000000000000", String(projectId));
      if (extraQuery) url += (url.includes("?") ? "&" : "?") + extraQuery;

      fetch(url)
        .then(r => r.text())
        .then(html => {
          document.getElementById("scope-modal-content").innerHTML = html;
          const modal = bootstrap.Modal.getOrCreateInstance(scopeModalEl);
          modal.show();
          applyScopeBufferToTable();
          attachScopeRowToggleHandlers();
          attachScopeSaveHandler(projectId);
        })
        .catch(err => {
          console.error(err);
          alert("업무범위 정보를 불러오지 못했습니다.");
        });
    }

    // 버튼 → 기본 로드
    scopeBtn.addEventListener("click", () => loadScopeModal(null));

    // 모달 내부 L1/L2 네비게이션 (이벤트 위임)
    document.addEventListener("click", (event) => {
      const asL1 = event.target.closest(".js-scope-l1-btn");
      const asL2 = event.target.closest(".js-scope-l2-btn");
      if (asL1) {
        const l1Id = asL1.dataset.l1Id;
        if (l1Id) loadScopeModal("l1=" + encodeURIComponent(l1Id));
      } else if (asL2) {
        const l1Id = asL2.dataset.l1Id;
        const l2Id = asL2.dataset.l2Id;
        if (l1Id && l2Id) {
          const q = "l1=" + encodeURIComponent(l1Id) + "&l2=" + encodeURIComponent(l2Id);
          loadScopeModal(q);
        }
      }
    });
  }

  /* ─────────────────────────────────────────
   *  초기화: 계약/프로젝트 각각 상황에 맞게 동작
   * ───────────────────────────────────────── */
  document.addEventListener("DOMContentLoaded", function(){
    mountScopeIntoContract();  // 계약 상세면 작동, 아니면 noop
    initProjectScopeModal();   // 프로젝트 상세면 작동, 아니면 noop
  });
})();
