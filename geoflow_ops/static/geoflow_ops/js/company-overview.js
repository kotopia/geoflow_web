(function () {
  'use strict';
  const switcher = document.getElementById('company-switch');
  if (switcher) switcher.addEventListener('change', () => { window.location.assign(switcher.value); });
  if (window.initAttachmentActions) window.initAttachmentActions({root: document});
  const el = document.getElementById('company-series');
  if (!el || !window.Chart) return;
  const rows = JSON.parse(el.textContent);
  function chart(id, values, label, type) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    if (values.every(value => value === null)) {
      const note = document.createElement('p');
      note.className = 'text-muted text-center pt-5';
      note.textContent = '선택 기간에 등록된 자료가 없습니다.';
      canvas.replaceWith(note);
      return;
    }
    new Chart(canvas, {type, data: {labels: rows.map(row => row.year), datasets: [{label, data: values, borderColor: '#3b7ddd', backgroundColor: type === 'bar' ? '#3b7ddd' : 'rgba(59,125,221,.1)', borderWidth: 2, spanGaps: false, fill: false}]}, options: {responsive: true, maintainAspectRatio: false, legend: {display: false}, scales: {yAxes: [{ticks: {beginAtZero: true, precision: 0}}]}}});
  }
  chart('company-revenue-chart', rows.map(row => row.revenue ? Number(row.revenue.amount) : null), '매출액(원)', 'bar');
  chart('company-headcount-chart', rows.map(row => row.headcount), '연말 사원수(명)', 'line');
})();
