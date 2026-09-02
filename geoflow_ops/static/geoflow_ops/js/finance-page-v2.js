(function () {
  "use strict";

  function num(v) {
    var n = Number(String(v == null ? "" : v).replace(/,/g, ""));
    return Number.isFinite(n) ? n : 0;
  }

  function roundWon(v) {
    return Math.round(num(v));
  }

  function stripCorp(s) {
    return String(s || "")
      .replace(/^\s*(?:\(\s*[주유합]\s*\)|㈜|주식회사|유한회사|합자회사|합명회사)\s*/g, "")
      .replace(/\s*(?:\(\s*[주유합]\s*\)|㈜|주식회사|유한회사|합자회사|합명회사)\s*$/g, "")
      .trim();
  }

  function sortPartnerOptions(select) {
    if (!select) return;
    var first = select.querySelector("option[value='']");
    var options = Array.from(select.querySelectorAll("option")).filter(function (o) { return o.value; });
    options.sort(function (a, b) {
      return stripCorp(a.textContent).localeCompare(stripCorp(b.textContent), "ko", { sensitivity: "base" });
    });
    select.innerHTML = "";
    if (first) select.appendChild(first);
    options.forEach(function (o) { select.appendChild(o); });
  }

  function initChoices(select, kind) {
    if (!select || select.dataset.choicesInited === "1" || !window.Choices) return;
    if (kind === "partner") sortPartnerOptions(select);
    select.dataset.choicesInited = "1";
    select._financeChoices = new Choices(select, {
      searchEnabled: true,
      shouldSort: false,
      itemSelectText: "",
      removeItemButton: false,
      placeholder: true,
      placeholderValue: select.getAttribute("data-placeholder") || "검색 또는 선택",
      searchPlaceholderValue: kind === "contract" ? "계약번호 또는 계약명 검색" : "회사명 검색"
    });
  }

  function setSelectValue(select, value) {
    if (!select) return;
    var v = value == null ? "" : String(value);
    if (select._financeChoices) {
      select._financeChoices.removeActiveItems();
      if (v) select._financeChoices.setChoiceByValue(v);
      else select._financeChoices.setChoiceByValue("");
    } else {
      select.value = v;
    }
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setField(form, name, value) {
    var el = form.elements[name];
    if (!el) return;
    if (el.tagName === "SELECT") setSelectValue(el, value || "");
    else el.value = value == null ? "" : value;
  }

  function resetForm(form) {
    form.reset();
    Array.from(form.querySelectorAll("select")).forEach(function (sel) {
      setSelectValue(sel, "");
    });
    if (form.elements.record_id) form.elements.record_id.value = "";
    Array.from(form.querySelectorAll("[data-fin-total]")).forEach(function (el) { el.value = "0"; });
  }

  function applyContractDefault(form, force) {
    var contract = form.querySelector(".js-fin-contract");
    var partner = form.querySelector(".js-fin-partner");
    if (!contract || !partner || !contract.value) return;
    var opt = contract.options[contract.selectedIndex];
    if (!opt) return;
    var clientId = opt.getAttribute("data-client-id") || "";
    if (!clientId) return;
    var recordId = form.elements.record_id ? form.elements.record_id.value : "";
    if (force || (!recordId && !partner.value) || !partner.value) setSelectValue(partner, clientId);
  }

  function bindContractDefaults(root) {
    root.querySelectorAll(".js-fin-contract").forEach(function (contract) {
      contract.addEventListener("change", function () {
        applyContractDefault(contract.closest("form"), false);
      });
    });
  }

  function bindMoney(form) {
    var supply = form.querySelector("[data-fin-supply]");
    var vat = form.querySelector("[data-fin-vat]");
    var total = form.querySelector("[data-fin-total]");
    if (!supply || !vat || !total) return;

    supply.addEventListener("input", function () {
      var s = roundWon(supply.value);
      var v = roundWon(s * 0.1);
      vat.value = String(v);
      total.value = String(s + v);
    });

    vat.addEventListener("input", function () {
      total.value = String(roundWon(supply.value) + roundWon(vat.value));
    });

    total.addEventListener("input", function () {
      var t = roundWon(total.value);
      var s = Math.round(t / 1.1);
      supply.value = String(s);
      vat.value = String(t - s);
    });
  }

  function modalInstance(el) {
    if (!window.bootstrap || !el) return null;
    return bootstrap.Modal.getOrCreateInstance(el);
  }

  function prepareCreate(button) {
    var modal = document.querySelector(button.getAttribute("data-target"));
    if (!modal) return;
    var form = modal.querySelector("form");
    resetForm(form);
    var title = modal.querySelector("[data-fin-modal-title]");
    if (title) title.textContent = button.getAttribute("data-title") || "등록";
    var submit = modal.querySelector("[data-fin-submit-label]");
    if (submit) submit.textContent = "저장";
    modalInstance(modal).show();
  }

  var fieldMaps = {
    claim: ["record_id:id", "claim_date:date", "due_date:dueDate", "expected_receipt_date:receiptDate", "contract_id:contractId", "partner_id:partnerId", "claim_type:claimType", "supply_amount:supply", "vat_amount:vat", "total_amount:total", "status:status", "memo:memo"],
    invoice: ["record_id:id", "written_date:writtenDate", "issued_date:issuedDate", "invoice_type:type", "contract_id:contractId", "partner_id:partnerId", "claim_id:claimId", "payment_request_id:paymentId", "approval_no:approvalNo", "supply_amount:supply", "vat_amount:vat", "total_amount:total", "status:status", "memo:memo"],
    payment: ["record_id:id", "request_date:date", "due_date:dueDate", "contract_id:contractId", "partner_id:partnerId", "amount:amount", "category_code:category", "status:status", "memo:memo"],
    transaction: ["record_id:id", "transaction_date:date", "transaction_type:type", "amount:amount", "contract_id:contractId", "partner_id:partnerId", "account_id:accountId", "description:description", "claim_id:claimId", "payment_request_id:paymentId", "category_code:category", "evidence_type:evidence", "memo:memo"]
  };

  var editTitles = {
    claim: "청구 수정",
    invoice: "세금계산서 수정",
    payment: "지급 수정",
    transaction: "입출금 수정"
  };

  function rowTitle(button, kind) {
    var row = button.closest("tr");
    if (!row) return "";
    if (kind === "claim" || kind === "payment") {
      return row.children[1] ? row.children[1].textContent.trim() : "";
    }
    return "";
  }

  function prepareEdit(button) {
    var kind = button.getAttribute("data-kind");
    var modal = document.querySelector(button.getAttribute("data-target"));
    if (!modal || !fieldMaps[kind]) return;
    var form = modal.querySelector("form");
    resetForm(form);
    fieldMaps[kind].forEach(function (pair) {
      var parts = pair.split(":");
      setField(form, parts[0], button.dataset[parts[1]] || "");
    });
    if (kind === "claim" || kind === "payment") {
      setField(form, "title", rowTitle(button, kind));
    }
    var title = modal.querySelector("[data-fin-modal-title]");
    if (title) title.textContent = editTitles[kind] || "수정";
    var submit = modal.querySelector("[data-fin-submit-label]");
    if (submit) submit.textContent = "수정 저장";
    modalInstance(modal).show();
  }

  function bindDeleteConfirm(root) {
    root.querySelectorAll("form[data-fin-delete-form]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        var label = form.getAttribute("data-label") || "이 항목";
        if (!window.confirm(label + "을(를) 삭제하시겠습니까? 삭제함에서 복원할 수 있습니다.")) e.preventDefault();
      });
    });
    root.querySelectorAll("form[data-fin-purge-form]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        var label = form.getAttribute("data-label") || "이 항목";
        if (!window.confirm(label + "을(를) 완전 삭제하시겠습니까? 이 작업은 복원할 수 없습니다.")) e.preventDefault();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-fin-contract").forEach(function (s) { initChoices(s, "contract"); });
    document.querySelectorAll(".js-fin-partner").forEach(function (s) { initChoices(s, "partner"); });

    bindContractDefaults(document);
    document.querySelectorAll("form[data-fin-money-form]").forEach(bindMoney);

    document.querySelectorAll("[data-fin-create]").forEach(function (button) {
      button.addEventListener("click", function () { prepareCreate(button); });
    });
    document.querySelectorAll("[data-fin-edit]").forEach(function (button) {
      button.addEventListener("click", function () { prepareEdit(button); });
    });

    bindDeleteConfirm(document);
  });
})();
