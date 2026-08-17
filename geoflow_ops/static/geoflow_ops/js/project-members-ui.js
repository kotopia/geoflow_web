(function () {
  "use strict";

  function projectDetailId() {
    var match = window.location.pathname.match(/\/projects\/([0-9a-fA-F-]{36})\/?$/);
    return match ? match[1] : null;
  }

  function findTargetColumn() {
    var rows = document.querySelectorAll(".container-fluid.px-0 > .row");
    if (!rows.length) return null;
    var columns = rows[0].querySelectorAll(":scope > .col-md-6.col-lg-6");
    return columns.length > 1 ? columns[1] : null;
  }

  async function loadProjectMembers() {
    var projectId = projectDetailId();
    if (!projectId || document.getElementById("projectMembersCard")) return;

    var target = findTargetColumn();
    if (!target) return;

    var url = window.location.pathname.replace(/\/$/, "") + "/members/";
    try {
      var response = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });
      if (!response.ok) return;
      var html = await response.text();
      var holder = document.createElement("div");
      holder.innerHTML = html;
      var card = holder.firstElementChild;
      if (!card) return;

      var firstCard = target.querySelector(":scope > .card");
      if (firstCard && firstCard.nextSibling) {
        target.insertBefore(card, firstCard.nextSibling);
      } else {
        target.appendChild(card);
      }
    } catch (error) {
      console.warn("Project member panel could not be loaded.", error);
    }
  }

  document.addEventListener("DOMContentLoaded", loadProjectMembers);
})();
