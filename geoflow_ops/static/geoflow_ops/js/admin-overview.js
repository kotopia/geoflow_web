(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var root = document.getElementById('overview');
    if (!root) return;
    var status = document.getElementById('calendar-status');
    var details = document.getElementById('calendar-details');
    var selected = root.dataset.today, events = [], loading = true;
    function renderDetails() {
      document.getElementById('selected-date').textContent = selected + ' 일정';
      details.replaceChildren();
      var rows = events.filter(function (e) { return e.start.slice(0, 10) === selected; });
      if (!rows.length) { details.textContent = loading ? '일정을 불러오는 중…' : '선택한 날짜에 등록된 일정이 없습니다.'; return; }
      rows.forEach(function (e) {
        var p = e.extendedProps, row = document.createElement('div');
        row.className = 'border-bottom py-3';
        var title = document.createElement(e.url ? 'a' : 'span');
        title.textContent = p.scope_name; if (e.url) title.href = e.url;
        var meta = document.createElement('div'); meta.className = 'small text-muted mt-1';
        meta.textContent = p.kind + ' · ' + p.assignee + ' · ' + (p.history ? '완료 이력' : '예정');
        row.append(title, meta); details.appendChild(row);
      });
    }
    if (!window.FullCalendar) { status.textContent = '달력 모듈을 불러오지 못했습니다.'; details.textContent = '일정을 조회할 수 없습니다.'; return; }
    var calendar = new FullCalendar.Calendar(document.getElementById('overview-calendar'), {
      initialView: 'dayGridMonth', initialDate: selected, locale: 'ko', height: 'auto',
      headerToolbar: { left: 'prev,next', center: 'title', right: 'today' }, buttonText: { today: '오늘' },
      dayCellClassNames: function (arg) { return arg.date.getFullYear() + '-' + String(arg.date.getMonth()+1).padStart(2,'0') + '-' + String(arg.date.getDate()).padStart(2,'0') === selected ? ['bg-primary-subtle'] : []; },
      dateClick: function (info) { selected = info.dateStr; renderDetails(); calendar.render(); },
      events: function (range, success, failure) {
        loading = true; status.textContent = '일정을 불러오는 중…'; renderDetails();
        var url = root.dataset.calendarUrl + '?overview=1&start=' + range.startStr.slice(0,10) + '&end=' + range.endStr.slice(0,10);
        fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { if (!r.ok) throw Error(); return r.json(); }).then(function (rows) {
          events = rows; loading = false; status.textContent = rows.length ? rows.length + '개 일정' : '이 기간에 등록된 일정이 없습니다.';
          var days = {};
          rows.forEach(function (r) { var key = r.start.slice(0,10); (days[key] || (days[key] = [])).push(r); });
          success(Object.keys(days).map(function (day) { return { start: day, allDay: true, title: String(days[day].length), extendedProps: { items: days[day] } }; }));
          renderDetails();
        }).catch(function (error) { loading = false; events = []; failure(error); status.textContent = '일정 조회에 실패했습니다. 월을 다시 선택해 주세요.'; details.textContent = '일정을 조회하지 못했습니다.'; });
      },
      eventContent: function (info) {
        var node = document.createElement('span'); node.className = 'small';
        var kinds = {};
        info.event.extendedProps.items.forEach(function (row) {
          var props = row.extendedProps;
          var key = props.event_type + ':' + props.history;
          if (kinds[key]) return; kinds[key] = true;
          var dot = document.createElement('span');
          var colors = { preparation: 'text-warning', contract: 'text-primary', kickoff: 'text-info', execution: 'text-success', closeout: 'text-info' };
          dot.className = 'me-1 ' + (props.history ? 'text-secondary' : colors[props.stage] || 'text-primary');
          dot.textContent = '●'; dot.title = props.kind + (props.history ? ' · 완료 이력' : ' · 예정');
          dot.setAttribute('aria-label', dot.title); node.appendChild(dot);
        });
        node.appendChild(document.createTextNode(info.event.title));
        return { domNodes: [node] };
      },
      eventClick: function (info) { selected = info.event.startStr.slice(0,10); renderDetails(); }
    });
    calendar.render();
  });
})();
