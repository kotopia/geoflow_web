// GeoFlow — employee directory list
(function () {
  function onReady(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  function statusOptions() {
    var source = document.getElementById("employee-status-options");
    if (!source) return [];
    try { return JSON.parse(source.textContent || "[]"); }
    catch (_error) { return []; }
  }

  function normalize(value) {
    return String(value || "").trim();
  }

  onReady(function () {
    var table = document.getElementById("datatables-employees");
    if (!table) return;
    var card = document.getElementById("employeesCard");
    var tabs = document.getElementById("statusButtons");
    var options = statusOptions();
    var selected = "";
    var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr"));

    var tbody = table.querySelector("tbody");
    if (tbody) {
      tbody.addEventListener("click", function (event) {
        var row = event.target.closest("tr[data-href]");
        if (row) window.location.assign(row.dataset.href);
      });
    }

    var counts = {"": rows.length};
    rows.forEach(function (row) {
      var code = normalize(row.dataset.status);
      counts[code] = (counts[code] || 0) + 1;
    });

    var hasDataTables = typeof window.$ === "function" && $.fn && typeof $.fn.DataTable === "function";
    var dataTable = null;
    if (hasDataTables) {
      dataTable = $(table).DataTable({
        responsive: true,
        paging: true,
        deferRender: true,
        stateSave: false,
        order: [[0, "desc"]],
        pageLength: 100,
        lengthMenu: [15, 30, 50, 100],
        language: {
          lengthMenu: "_MENU_개씩 보기",
          info: "총 _TOTAL_개 중 _START_–_END_",
          infoEmpty: "표시할 항목이 없습니다",
          infoFiltered: "(총 _MAX_개에서 필터링됨)",
          zeroRecords: "일치하는 결과가 없습니다",
          emptyTable: "직원이 없습니다.",
          search: "검색:",
          paginate: {first: "처음", last: "마지막", next: "다음", previous: "이전"}
        }
      });
      $.fn.dataTable.ext.search.push(function (settings, _data, index) {
        if (settings.nTable !== table || !selected) return true;
        var row = dataTable.row(index).node();
        return normalize(row && row.dataset ? row.dataset.status : "") === selected;
      });
    }

    function applyFilter() {
      if (dataTable) {
        dataTable.draw();
        return;
      }
      rows.forEach(function (row) {
        row.style.display = !selected || normalize(row.dataset.status) === selected ? "" : "none";
      });
    }

    function select(button, code) {
      selected = code;
      if (tabs) tabs.querySelectorAll(".gf-tab").forEach(function (item) {
        item.classList.toggle("active", item === button);
      });
      applyFilter();
    }

    function addTab(label, code) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "gf-tab" + (code ? "" : " active");
      button.textContent = label + " ";
      var count = document.createElement("span");
      count.className = "count";
      count.textContent = counts[code] || 0;
      button.appendChild(count);
      button.addEventListener("click", function () { select(button, code); });
      return button;
    }

    if (tabs) {
      var wrap = document.createElement("div");
      wrap.className = "gf-tabs";
      wrap.appendChild(addTab("전체", ""));
      options.forEach(function (item) {
        var code = normalize(item.code);
        if (code) wrap.appendChild(addTab(item.name || code, code));
      });
      tabs.replaceChildren(wrap);
    }

    var deletedToggle = document.getElementById("showDeletedEmployees");
    if (deletedToggle) deletedToggle.addEventListener("change", function () {
      window.location.assign(deletedToggle.checked ? deletedToggle.dataset.onUrl : deletedToggle.dataset.offUrl);
    });

    if (card) card.removeAttribute("hidden");
  });
})();
