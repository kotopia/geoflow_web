/* GeoFlow — gf-list-core.js (stable build)
 * - 배지 렌더 + 상태 탭/카운트 + DataTables 연동/가드 + hidden 게이트
 */
window.GeoFlow = window.GeoFlow || {};
GeoFlow.utils = GeoFlow.utils || {};

GeoFlow.utils.stripCorp = function (s) {
  return (s || "")
    .replace(/^\s*(?:\(\s*[주유합]\s*\)|㈜|주식회사|유한회사|합자회사|합명회사)\s*/g, "")
    .trim();
};

GeoFlow.utils.sortOptionsByCompany = function (items) {
  const strip = GeoFlow.utils.stripCorp;
  return (items || []).slice().sort((a, b) =>
    strip(a.text || a.label || "").localeCompare(
      strip(b.text || b.label || ""),
      "ko",
      { sensitivity: "base" }
    )
  );
};

(function () {
  (function injectStyle() {
    if (document.getElementById("gf-status-tabs-style")) return;
    var s = document.createElement("style");
    s.id = "gf-status-tabs-style";
    s.textContent =
      ".gf-tabs{display:flex;gap:14px;flex-wrap:wrap;align-items:center}" +
      ".gf-tab{cursor:pointer;border:0;background:none;padding:6px 2px;font-weight:500;color:#6c757d}" +
      ".gf-tab .count{margin-left:3px;vertical-align:middle;font-size:.65rem;color:#6c757d}" +
      ".gf-tab::after{content:\"\";display:block;height:2px;background:transparent;margin-top:4px}" +
      ".gf-tab.active{color:#111827}" +
      ".gf-tab.active::after{background:#111827;height:3px}" +
      ".gf-tab:hover{color:#111827}" +
      ".badge-xs{font-size:.65rem;padding:.25em .5em;line-height:1.1;}" +
      ".gf-tab.gf-k-all{color:rgba(var(--bs-secondary-rgb),.65)}" +
      ".gf-tab.gf-k-all .count{color:rgba(var(--bs-secondary-rgb),.65)}" +
      ".gf-tab.gf-k-planned{color:rgba(var(--bs-warning-rgb),.65)}" +
      ".gf-tab.gf-k-planned .count{color:rgba(var(--bs-warning-rgb),.65)}" +
      ".gf-tab.gf-k-active{color:rgba(var(--bs-success-rgb),.65)}" +
      ".gf-tab.gf-k-active .count{color:rgba(var(--bs-success-rgb),.65)}" +
      ".gf-tab.gf-k-pause{color:rgba(var(--bs-info-rgb),.65)}" +
      ".gf-tab.gf-k-pause .count{color:rgba(var(--bs-info-rgb),.65)}" +
      ".gf-tab.gf-k-cancel{color:rgba(var(--bs-danger-rgb),.65)}" +
      ".gf-tab.gf-k-cancel .count{color:rgba(var(--bs-danger-rgb),.65)}" +
      ".gf-tab.gf-k-complete{color:rgba(var(--bs-secondary-rgb),.65)}" +
      ".gf-tab.gf-k-complete .count{color:rgba(var(--bs-secondary-rgb),.65)}" +
      ".gf-tab.gf-k-all.active{color:var(--bs-secondary)} .gf-tab.gf-k-all.active .count{color:var(--bs-secondary)} .gf-tab.gf-k-all.active::after{background:var(--bs-secondary)}" +
      ".gf-tab.gf-k-planned.active{color:var(--bs-warning)} .gf-tab.gf-k-planned.active .count{color:var(--bs-warning)} .gf-tab.gf-k-planned.active::after{background:var(--bs-warning)}" +
      ".gf-tab.gf-k-active.active{color:var(--bs-success)} .gf-tab.gf-k-active.active .count{color:var(--bs-success)} .gf-tab.gf-k-active.active::after{background:var(--bs-success)}" +
      ".gf-tab.gf-k-pause.active{color:var(--bs-info)} .gf-tab.gf-k-pause.active .count{color:var(--bs-info)} .gf-tab.gf-k-pause.active::after{background:var(--bs-info)}" +
      ".gf-tab.gf-k-cancel.active{color:var(--bs-danger)} .gf-tab.gf-k-cancel.active .count{color:var(--bs-danger)} .gf-tab.gf-k-cancel.active::after{background:var(--bs-danger)}" +
      ".gf-tab.gf-k-complete.active{color:var(--bs-secondary)} .gf-tab.gf-k-complete.active .count{color:var(--bs-secondary)} .gf-tab.gf-k-complete.active::after{background:var(--bs-secondary)}";
    document.head.appendChild(s);
  })();

  var BADGE = {
    planned:  { label:"계약전", icon:"fa-spinner",      cls:"badge bg-warning text-dark", iconCls:"text-warning" },
    active:   { label:"진행",   icon:"fa-play",         cls:"badge bg-success",           iconCls:"text-success" },
    pause:    { label:"중지",   icon:"fa-pause",        cls:"badge bg-info",              iconCls:"text-info" },
    cancel:   { label:"취소",   icon:"fa-ban",          cls:"badge bg-danger",            iconCls:"text-danger" },
    complete: { label:"완료",   icon:"fa-check-circle", cls:"badge bg-secondary",         iconCls:"text-secondary" }
  };

  function norm(v){ return (v||"").toString().trim().toLowerCase(); }

  function canonicalStatus(v) {
    var s = norm(v);
    var aliases = {
      completed:"complete", "완료":"complete",
      paused:"pause", "중지":"pause", "보류":"pause",
      canceled:"cancel", cancelled:"cancel", "취소":"cancel",
      "진행":"active", "진행중":"active", "계약전":"planned"
    };
    return aliases[s] || s;
  }

  function contractLabels() {
    var vocab = window.GEOFLOW_TENANT_VOCABULARY || {};
    return vocab.contractStatus || {};
  }

  function renderBadge(el){
    if (!el || el.getAttribute("data-gf-decorated")==="1") return;
    var rawStatus = el.getAttribute("data-status") || el.textContent;
    var status = canonicalStatus(rawStatus);
    var mode = norm(el.getAttribute("data-render")) || "badge";
    var info = BADGE[status];
    var contractVocabulary = el.getAttribute("data-vocabulary") === "contract";
    var contractTable = !!(el.closest && el.closest("#datatables-contracts"));
    var custom = (contractVocabulary || contractTable) ? contractLabels()[status] : null;
    var label = custom || (info ? info.label : (status || "—"));
    var cls = info ? info.cls : "badge bg-light text-dark border";
    var icon = info ? info.icon : "fa-question-circle";

    if (mode === "icon") {
      var color = info ? (info.iconCls || "text-secondary") : "text-muted";
      el.className = "gf-status-icon " + color;
      el.innerHTML = '<i class="align-middle fas fa-fw ' + icon + '" title="' + label + '"></i>';
    } else if (mode === "text") {
      el.className = "gf-status-text";
      el.textContent = label;
    } else {
      var size = (el.getAttribute("data-size")||"").toLowerCase();
      el.className = cls + (size==="sm" ? " badge-xs" : "");
      el.textContent = label;
    }
    el.setAttribute("aria-label", label);
    el.setAttribute("data-gf-decorated", "1");
  }

  function renderBadges(root){
    var r = root || document;
    var list = r.querySelectorAll(".gf-status,[data-status].gf-badge,[data-status].gf-status-icon,[data-status].gf-status-text");
    for (var i=0;i<list.length;i++) renderBadge(list[i]);
  }

  var ORDER = ["all","planned","active","pause","cancel","complete"];
  var SYN = {
    planned:["planned"], active:["active"], pause:["pause"],
    cancel:["cancel"], complete:["complete"]
  };
  var LABEL = { all:"전체", planned:"계약전", active:"진행", pause:"중지", cancel:"취소", complete:"완료" };

  function datasetCounts(cont){
    if (!cont) return null;
    var any = cont.dataset.countAll!=null || cont.dataset.countPlanned!=null;
    if (!any) return null;
    function v(k){ return parseInt(cont.dataset[k],10)||0; }
    return {
      all:v("countAll"), planned:v("countPlanned"), active:v("countActive"),
      pause:v("countPause"), cancel:v("countCancel"), complete:v("countComplete")
    };
  }

  function countFromTable(tableEl){
    var c = {all:0,planned:0,active:0,pause:0,cancel:0,complete:0};
    var rows = tableEl.querySelectorAll("tbody tr");
    for (var i=0;i<rows.length;i++){
      var s = canonicalStatus(rows[i].dataset.status);
      c.all++;
      if (SYN.planned.indexOf(s)>-1) c.planned++;
      else if (SYN.active.indexOf(s)>-1) c.active++;
      else if (SYN.pause.indexOf(s)>-1) c.pause++;
      else if (SYN.cancel.indexOf(s)>-1) c.cancel++;
      else if (SYN.complete.indexOf(s)>-1) c.complete++;
    }
    return c;
  }

  function buildTabs(container, counts, onSelect, initial, labels){
    container.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.className = "gf-tabs";
    var initKey = initial || "all";
    labels = labels || {};

    for (var i=0;i<ORDER.length;i++){
      var k = ORDER[i];
      var b = document.createElement("button");
      b.type = "button";
      b.className = "gf-tab gf-k-" + k;
      b.setAttribute("data-k", k);
      b.innerHTML = (k === "all" ? LABEL[k] : (labels[k] || LABEL[k])) + ' <span class="count">' + (counts[k]||0) + '</span>';
      if (k===initKey) b.classList.add("active");
      b.addEventListener("click", (function(key){
        return function(){
          var all = wrap.querySelectorAll(".gf-tab");
          for (var j=0;j<all.length;j++) all[j].classList.remove("active");
          this.classList.add("active");
          onSelect(key);
        };
      })(k));
      wrap.appendChild(b);
    }
    container.appendChild(wrap);
  }

  function revealCardBy(tableEl){
    var card = document.getElementById("contractsCard") || tableEl.closest(".card");
    if (card && card.hasAttribute("hidden")) card.removeAttribute("hidden");
  }

  function waitThenReveal(tableEl, statusSel){
    var sel = statusSel || "#statusButtons";
    var card = tableEl.closest(".card");
    if (!card) return;
    function ready(){
      var hasWrapper = !!card.querySelector(".dataTables_wrapper");
      var hasTabs = !!card.querySelector(sel + " .gf-tabs");
      return hasWrapper && hasTabs;
    }
    function loop(){
      if (ready()) revealCardBy(tableEl);
      else requestAnimationFrame(loop);
    }
    loop();
  }

  function text(tr, col){
    if (!tr) return "-";
    var el = tr.querySelector('[data-col="'+col+'"]');
    if (el) return (el.textContent || "").trim() || "-";
    var ds = tr.dataset || {};
    if (ds[col] != null) return (ds[col] || "").toString().trim() || "-";
    return "-";
  }

  function initTable(opts){
    var tableId = opts && opts.tableId ? opts.tableId : null;
    var statusSel = opts && opts.statusSel ? opts.statusSel : "#statusButtons";
    var emptyTableText = opts && typeof opts.emptyTable === "string" ? opts.emptyTable : null;
    if (!tableId) return;

    var tableEl = document.getElementById(tableId);
    if (!tableEl) return;
    var isContract = tableId === "datatables-contracts";

    renderBadges(tableEl);

    var hasDT = (typeof window.$==="function") && $.fn && (typeof $.fn.DataTable==="function");
    var dt = null, already = false;
    if (hasDT && $.fn.DataTable.isDataTable(tableEl)) {
      dt = $("#"+tableId).DataTable();
      already = true;
    } else if (hasDT) {
      dt = $("#"+tableId).DataTable({
        responsive:true, paging:true, deferRender:true, stateSave:false,
        order:[[0,'desc']], pageLength:100, lengthMenu:[15,30,50,100],
        language: {
          lengthMenu: "_MENU_개씩 보기",
          info: "총 _TOTAL_개 중 _START_–_END_",
          infoEmpty: "표시할 항목이 없습니다",
          infoFiltered: "(총 _MAX_개에서 필터링됨)",
          zeroRecords: "일치하는 결과가 없습니다",
          emptyTable: (emptyTableText || undefined),
          search: "검색:",
          paginate: { first:"처음", last:"마지막", next:"다음", previous:"이전" }
        },
        initComplete: function () { waitThenReveal(tableEl, statusSel); }
      });
    }

    var cont = document.querySelector(statusSel);
    var counts = (cont && datasetCounts(cont)) || countFromTable(tableEl);
    var applyDT = null, applyDOM = null;

    if (dt) {
      var sel = "all";
      var fn = function (settings, data, idx) {
        if (settings.nTable !== tableEl) return true;
        if (!sel || sel==="all") return true;
        var node = dt.row(idx).node();
        var s = canonicalStatus(node && node.dataset ? node.dataset.status : "");
        var arr = SYN[sel] || [];
        return arr.indexOf(s) > -1;
      };
      $.fn.dataTable.ext.search.push(fn);
      applyDT = function (k) { sel = k || "all"; dt.draw(); };
    } else {
      var sel2 = "all";
      var run = function(){
        var rows = tableEl.querySelectorAll("tbody tr");
        for (var i=0;i<rows.length;i++){
          var s = canonicalStatus(rows[i].dataset.status);
          var arr = SYN[sel2] || [];
          var ok = (!sel2 || sel2==="all") ? true : (arr.indexOf(s) > -1);
          rows[i].style.display = ok ? "" : "none";
        }
      };
      applyDOM = function (k) { sel2 = k || "all"; run(); };
    }

    if (cont) {
      var onSelect = function (k) { if (applyDT) applyDT(k); else applyDOM(k); };
      buildTabs(cont, counts, onSelect, "all", isContract ? contractLabels() : {});
    }

    if (already && cont) waitThenReveal(tableEl, statusSel);
    if (!dt && cont) revealCardBy(tableEl);
  }

  document.addEventListener("DOMContentLoaded", function(){
    if (document.getElementById("datatables-contracts")) initTable({ tableId:"datatables-contracts", statusSel:"#statusButtons" });
    if (document.getElementById("datatables-projects")) initTable({ tableId:"datatables-projects", statusSel:"#statusButtons" });
  });

  window.GeoFlowListCore = { initTable:initTable, renderBadges:renderBadges, canonicalStatus:canonicalStatus };
})();
