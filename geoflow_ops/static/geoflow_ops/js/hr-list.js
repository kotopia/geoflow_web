// GeoFlow — HR list init (employees)
(function(){
  function onReady(fn){ if(document.readyState!=="loading") fn(); else document.addEventListener("DOMContentLoaded", fn); }
  onReady(function(){
    var tableId = "datatables-employees";
    var table = document.getElementById(tableId);
    if(!table) return;

    // 1) 행 클릭 -> 상세 이동 (계약 리스트와 동일 UX)
    var tbody = table.querySelector("tbody");
    if (tbody) {
      tbody.addEventListener("click", function(e){
        var tr = e.target.closest('tr[data-href]');
        if (!tr) return;
        window.location.assign(tr.dataset.href);
      });
    }

    // 2) gf-list-core 공용 초기화(배지/상태탭/DataTables/게이트)
    if (window.GeoFlowListCore && typeof GeoFlowListCore.initTable === "function") {
      GeoFlowListCore.initTable({ tableId: tableId, statusSel: "#statusButtons" });
    } else {
      // 코어가 없다면 최소한 카드만 표시
      var card = document.getElementById("employeesCard");
      if (card && card.hasAttribute("hidden")) card.removeAttribute("hidden");
    }
  });
})();
