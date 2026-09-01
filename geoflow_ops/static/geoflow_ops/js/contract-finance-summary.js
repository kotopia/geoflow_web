(function () {
  function money(value) {
    var n = Number(value || 0);
    return '₩' + (Number.isFinite(n) ? n : 0).toLocaleString('ko-KR');
  }
  function run() {
    var path = window.location.pathname;
    var match = path.match(/\/contracts\/([0-9a-f-]{36})\/?$/i);
    if (!match || document.querySelector('[data-gf-contract-finance]')) return;
    var heading = Array.from(document.querySelectorAll('h1,h2,h3')).find(function (el) { return (el.textContent || '').trim() === '계약 상세'; });
    if (!heading) return;
    var contractBase = path.endsWith('/') ? path : path + '/';
    var summaryUrl = contractBase + 'finance-summary/';
    var financeUrl = contractBase.replace(/contracts\/[0-9a-f-]{36}\/$/i, 'finance/');
    fetch(summaryUrl, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) throw new Error('finance summary'); return r.json(); })
      .then(function (d) {
        var anchor = heading.closest('div') && heading.closest('div').parentElement;
        var host = anchor && anchor.parentElement ? anchor.parentElement : document.querySelector('main .container-fluid');
        if (!host) return;
        var card = document.createElement('div');
        card.className = 'card mb-3';
        card.setAttribute('data-gf-contract-finance', '1');
        card.innerHTML = '<div class="card-header d-flex align-items-center justify-content-between"><h5 class="card-title mb-0">Finance 요약</h5><a class="btn btn-sm btn-outline-primary" href="' + financeUrl + '">Finance 열기</a></div>' +
          '<div class="card-body pt-0"><div class="row g-0 text-center border-top">' +
          [['계약금액',d.contract_amount],['청구',d.claimed],['수금',d.received],['미청구',d.unclaimed],['미수금',d.receivable],['미지급',d.payable]].map(function(x){return '<div class="col-6 col-md-2 py-3 border-end"><div class="small text-muted">'+x[0]+'</div><div class="fw-semibold">'+money(x[1])+'</div></div>';}).join('') +
          '</div></div>';
        var firstCard = host.querySelector('.card');
        if (firstCard && firstCard.parentNode === host) host.insertBefore(card, firstCard.nextSibling); else host.insertBefore(card, host.firstChild);
      }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
