(function (window, document) {
  'use strict';

  var originalFetch = window.fetch.bind(window);
  var lastEditingEvent = null;

  function byId(id) { return document.getElementById(id); }
  function bool(id) { var el = byId(id); return !!(el && el.checked); }
  function value(id) { var el = byId(id); return el ? el.value : ''; }

  function syncControls() {
    var highlight = byId('event-highlight-enabled');
    var days = byId('event-highlight-days');
    var end = byId('event-end-at');
    var indefinite = byId('event-until-closed');
    var calendar = byId('event-calendar-enabled');
    var label = byId('event-calendar-label');
    var button = byId('btn-event-calendar-toggle');
    if (!highlight || !days || !end || !indefinite) return;
    days.disabled = !highlight.checked || indefinite.checked || !!end.value;
    end.disabled = indefinite.checked;
    if (calendar && label && button) {
      label.textContent = calendar.checked ? '캘린더에서 제거' : '캘린더에 추가';
      button.classList.toggle('btn-primary', calendar.checked);
      button.classList.toggle('btn-outline-primary', !calendar.checked);
    }
  }

  function installModalControls() {
    var highlight = byId('event-highlight-enabled');
    if (!highlight || highlight.dataset.gfBound === '1') return;
    highlight.dataset.gfBound = '1';
    ['event-highlight-enabled', 'event-highlight-days', 'event-end-at', 'event-until-closed'].forEach(function (id) {
      var el = byId(id); if (el) { el.addEventListener('change', syncControls); el.addEventListener('input', syncControls); }
    });
    var button = byId('btn-event-calendar-toggle');
    var calendar = byId('event-calendar-enabled');
    if (button && calendar) button.addEventListener('click', function () { calendar.checked = !calendar.checked; syncControls(); });
    syncControls();
  }

  function fillDisplay(ev) {
    installModalControls();
    var p = ev || {};
    var highlight = byId('event-highlight-enabled');
    var days = byId('event-highlight-days');
    var end = byId('event-end-at');
    var indefinite = byId('event-until-closed');
    var calendar = byId('event-calendar-enabled');
    if (highlight) highlight.checked = !!p.highlight_enabled;
    if (days) days.value = p.highlight_days || 7;
    if (end) end.value = p.end_at || '';
    if (indefinite) indefinite.checked = !!p.until_closed;
    if (calendar) calendar.checked = !!p.calendar_enabled;
    syncControls();
  }

  function resetDisplay() {
    fillDisplay({highlight_enabled:false, highlight_days:7, end_at:null, until_closed:false, calendar_enabled:false});
  }

  function augmentBody(url, options) {
    if (!options || String(options.method || 'GET').toUpperCase() !== 'POST' || !options.body) return options;
    var textUrl = String(url || '');
    if (textUrl.indexOf('/api/events/create/') === -1 && textUrl.indexOf('/api/events/update/') === -1) return options;
    try {
      var body = JSON.parse(options.body);
      if (!body || typeof body !== 'object') return options;
      if (!byId('event-highlight-enabled')) return options;
      body.highlight_enabled = bool('event-highlight-enabled');
      body.highlight_days = parseInt(value('event-highlight-days') || '7', 10) || 7;
      body.end_at = value('event-end-at') || null;
      body.until_closed = bool('event-until-closed');
      body.calendar_enabled = bool('event-calendar-enabled');
      var cloned = Object.assign({}, options, {body: JSON.stringify(body)});
      return cloned;
    } catch (e) { return options; }
  }

  window.fetch = function (url, options) { return originalFetch(url, augmentBody(url, options)); };

  var observer = new MutationObserver(function () { installModalControls(); });
  observer.observe(document.documentElement, {childList:true, subtree:true});

  var attempts = 0;
  var timer = window.setInterval(function () {
    attempts += 1;
    var api = window.ProcessWorkboardUI;
    if (api && !api.__displayCalendarWrapped) {
      var create = api.openCreateModal;
      var edit = api.openEditModal;
      api.openCreateModal = function () {
        lastEditingEvent = null;
        var result = create.apply(api, arguments);
        window.setTimeout(resetDisplay, 80);
        window.setTimeout(resetDisplay, 220);
        return result;
      };
      api.openEditModal = function (ev) {
        lastEditingEvent = ev || null;
        var result = edit.apply(api, arguments);
        window.setTimeout(function () { fillDisplay(lastEditingEvent); }, 80);
        window.setTimeout(function () { fillDisplay(lastEditingEvent); }, 220);
        return result;
      };
      api.__displayCalendarWrapped = true;
      window.clearInterval(timer);
    } else if (attempts > 200) {
      window.clearInterval(timer);
    }
  }, 25);
})(window, document);
