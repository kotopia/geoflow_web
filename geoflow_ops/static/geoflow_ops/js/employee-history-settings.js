(function(){
  "use strict";

  function toSelect(input, id) {
    if (!input || input.tagName === "SELECT") return input;
    var select = document.createElement("select");
    Array.from(input.attributes).forEach(function(attr){
      if (attr.name === "type" || attr.name === "placeholder") return;
      select.setAttribute(attr.name, attr.value);
    });
    select.id = id || input.id || "";
    select.className = input.className || "form-select";
    if (!select.classList.contains("form-select")) select.classList.add("form-select");
    var placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "- 선택 -";
    select.appendChild(placeholder);
    input.replaceWith(select);
    return select;
  }

  function fillOptions(select, items, selected) {
    if (!select) return;
    var keep = selected != null ? String(selected) : String(select.value || "");
    select.replaceChildren();
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "- 선택 -";
    select.appendChild(blank);
    (items || []).forEach(function(item){
      var option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.text;
      if (keep && String(item.id) === keep) option.selected = true;
      select.appendChild(option);
    });
  }

  function loadOptions(url, select) {
    return fetch(url, {credentials:"same-origin"})
      .then(function(response){ return response.ok ? response.json() : Promise.reject(new Error("option load failed")); })
      .then(function(data){ fillOptions(select, data.results || [], select.value); return select; })
      .catch(function(){ return select; });
  }

  document.addEventListener("DOMContentLoaded", function(){
    var config = document.getElementById("employeeHistorySettingsConfig");
    var modal = document.getElementById("employeeHistoryModal");
    if (!config || !modal) return;

    var education = modal.querySelector('[data-history-fields="education"]');
    var career = modal.querySelector('[data-history-fields="career"]');
    var historyForm = document.getElementById("employee-history-form");

    var degreeSelect = toSelect(education && education.querySelector('[name="degree"]'), "employee-education-degree");
    var statusSelect = toSelect(education && education.querySelector('[name="education_status"]'), "employee-education-status");
    var degreePromise = loadOptions(config.dataset.degreeOptionsUrl || "", degreeSelect);
    var statusPromise = loadOptions(config.dataset.statusOptionsUrl || "", statusSelect);

    // The current employee-detail layout intentionally hides school type.
    // Keep a hidden field so editing an existing education row does not erase
    // a previously stored school_type value.
    var schoolTypeInput = education && education.querySelector('[name="school_type"]');
    if (education && !schoolTypeInput) {
      schoolTypeInput = document.createElement("input");
      schoolTypeInput.type = "hidden";
      schoolTypeInput.name = "school_type";
      education.appendChild(schoolTypeInput);
    }

    if (career && !career.querySelector('[name="certificate_no"]')) {
      var row = career.querySelector(".row");
      var duties = career.querySelector('[name="duties"]');
      var dutiesCol = duties ? duties.closest("div[class*='col-']") : null;
      var col = document.createElement("div");
      col.className = "col-md-6";
      col.innerHTML = '<label class="form-label">발급번호</label><input type="text" name="certificate_no" class="form-control" autocomplete="off">';
      if (row) {
        if (dutiesCol) row.insertBefore(col, dutiesCol);
        else row.appendChild(col);
      }
    }

    document.querySelectorAll('.history-add[data-section="education"]').forEach(function(button){
      button.addEventListener("click", function(){
        Promise.all([degreePromise, statusPromise]).then(function(){
          if (degreeSelect) degreeSelect.value = "";
          if (statusSelect) statusSelect.value = "";
          if (schoolTypeInput) schoolTypeInput.value = "";
        });
      });
    });

    document.querySelectorAll('.history-edit[data-section="education"]').forEach(function(button){
      button.addEventListener("click", function(){
        Promise.all([degreePromise, statusPromise]).then(function(){
          if (degreeSelect) degreeSelect.value = button.dataset.degree || "";
          if (statusSelect) statusSelect.value = button.dataset.educationStatus || "";
          if (schoolTypeInput) schoolTypeInput.value = button.dataset.schoolType || "";
        });
      });
    });

    document.querySelectorAll('.history-edit[data-section="career"]').forEach(function(button){
      button.addEventListener("click", function(){
        var input = career && career.querySelector('[name="certificate_no"]');
        if (!input || !historyForm || !button.dataset.recordId) return;
        input.value = "";
        var url = new URL(historyForm.action, window.location.origin);
        url.searchParams.set("section", "career");
        url.searchParams.set("record_id", button.dataset.recordId);
        fetch(url.toString(), {credentials:"same-origin", headers:{"X-Requested-With":"XMLHttpRequest"}})
          .then(function(response){ return response.ok ? response.json() : Promise.reject(); })
          .then(function(data){ input.value = data.certificate_no || ""; })
          .catch(function(){ input.value = ""; });
      });
    });
  });
})();
