(function (window, document) {
  'use strict';

  function directField(row, labelText) {
    return Array.from(row.children).find(function (child) {
      var label = child.querySelector && child.querySelector('label.small.text-muted');
      return label && String(label.textContent || '').trim() === labelText;
    }) || null;
  }

  function makeRow(labelText, valueNode) {
    var row = document.createElement('div');
    row.className = 'row py-2 border-top';
    var label = document.createElement('div');
    label.className = 'col-sm-4 col-lg-3 small text-muted';
    label.textContent = labelText;
    var value = document.createElement('div');
    value.className = 'col-sm-8 col-lg-9';
    if (valueNode) {
      while (valueNode.firstChild) value.appendChild(valueNode.firstChild);
    } else {
      value.textContent = '-';
    }
    row.appendChild(label);
    row.appendChild(value);
    return row;
  }

  function valueOf(field) {
    return field ? field.querySelector('.form-control-plaintext') : null;
  }

  function alignProjectContractCard() {
    if (!document.getElementById('projectDetailTabs')) return;
    var view = document.getElementById('view-mode');
    var grid = view && view.querySelector(':scope > .row.g-3');
    if (!view || !grid || view.dataset.gfContractCardParity === '1') return;
    view.dataset.gfContractCardParity = '1';

    var card = view.closest('.card');
    var body = view.closest('.card-body');
    if (card && body && !card.querySelector(':scope > .card-header')) {
      var header = document.createElement('div');
      header.className = 'card-header';
      header.innerHTML = '<h5 class="card-title mb-0">계약정보</h5>';
      card.insertBefore(header, body);
      body.classList.add('pt-0');
    }

    var contractName = directField(grid, '계약명');
    var contractNumber = directField(grid, '계약번호');
    var client = directField(grid, '발주처');
    var contractor = directField(grid, '계약자');
    var start = directField(grid, '시작일');
    var end = directField(grid, '종료일');
    var kind = directField(grid, '계약형태');
    var stage = directField(grid, '업무단계');
    var other = directField(grid, '기타정보');

    var periodValue = document.createElement('div');
    var startText = valueOf(start) ? String(valueOf(start).textContent || '').trim() : '-';
    var endText = valueOf(end) ? String(valueOf(end).textContent || '').trim() : '-';
    periodValue.textContent = startText + ' ~ ' + endText;

    var fragment = document.createDocumentFragment();
    fragment.appendChild(makeRow('계약명', valueOf(contractName)));
    fragment.appendChild(makeRow('계약번호', valueOf(contractNumber)));
    fragment.appendChild(makeRow('발주처', valueOf(client)));
    fragment.appendChild(makeRow('계약자', valueOf(contractor)));
    fragment.appendChild(makeRow('계약기간', periodValue));
    fragment.appendChild(makeRow('계약형태', valueOf(kind)));
    fragment.appendChild(makeRow('현재 업무단계', valueOf(stage)));
    fragment.appendChild(makeRow('기타정보', valueOf(other)));

    view.replaceChildren(fragment);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', alignProjectContractCard, {once:true});
  } else {
    alignProjectContractCard();
  }
})(window, document);
