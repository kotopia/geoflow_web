(function (window, document) {
  'use strict';
  if (window.__GEOFLOW_PERIOD_EVENT_CLOSE_LOADED__) return;
  window.__GEOFLOW_PERIOD_EVENT_CLOSE_LOADED__ = true;

  var previousFetch = window.fetch.bind(window);
  var closeRequested = false;
  var successKey = 'geoflow.periodEventCloseSuccess';

  function byId(id) { return document.getElementById(id); }
  function value(id) { var el = byId(id); return el ? String(el.value || '') : ''; }
  function checked(id) { var el = byId(id); return !!(el && el.checked); }
  function isSuspend() { return value('event-type') === 'suspend'; }

  function showModalMessage(message, kind) {
    var el = byId('event-alert');
    if (!el) return;
    el.classList.remove('d-none', 'alert-danger', 'alert-success', 'alert-warning');
    el.classList.add(kind === 'success' ? 'alert-success' : 'alert-danger');
    el.textContent = message;
  }

  function ensurePeriodActionLayout() {
    var checkWrap = byId('event-until-closed-wrap');
    var closeButton = byId('btn-close-period-event');
    if (!checkWrap || !closeButton) return null;

    var row = byId('gf-period-action-row');
    if (!row) {
      row = document.createElement('div');
      row.id = 'gf-period-action-row';
      row.className = 'd-flex align-items-center gap-2 mt-2 d-none';
      var parent = checkWrap.parentNode;
      parent.insertBefore(row, checkWrap);
      checkWrap.classList.remove('mt-2');
      checkWrap.classList.add('mb-0');
      row.appendChild(checkWrap);
      row.appendChild(closeButton);
      closeButton.className = 'btn btn-outline-warning btn-sm d-none';
    }
    return row;
  }

  function syncCloseButton() {
    var row = ensurePeriodActionLayout();
    var checkWrap = byId('event-until-closed-wrap');
    var indefinite = byId('event-until-closed');
    var end = byId('event-end-at');
    var closeButton = byId('btn-close-period-event');
    var saveButton = byId('btn-save-event');
    if (!row || !checkWrap || !indefinite || !end || !closeButton) return;

    var period = isSuspend();
    row.classList.toggle('d-none', !period);
    checkWrap.classList.toggle('d-none', !period);
    if (!period) {
      closeButton.classList.add('d-none');
      closeButton.disabled = true;
      return;
    }

    var readOnly = !!(saveButton && (saveButton.disabled || saveButton.classList.contains('d-none')));
    end.disabled = indefinite.checked || readOnly;

    var eventId = value('event-id');
    var alreadyClosed = value('event-status') === 'done';
    var show = !!eventId && !indefinite.checked && !!end.value && !alreadyClosed && !readOnly;
    closeButton.classList.toggle('d-none', !show);
    closeButton.disabled = !show;
  }

  function bindModalState() {
    ensurePeriodActionLayout();
    syncCloseButton();
  }

  document.addEventListener('shown.bs.modal', function (event) {
    if (event.target && event.target.id === 'eventModal') {
      window.setTimeout(bindModalState, 0);
      window.setTimeout(bindModalState, 120);
    }
  });

  document.addEventListener('change', function (event) {
    if (!event.target) return;
    if (['event-until-closed', 'event-end-at', 'event-type', 'event-stage', 'event-status'].indexOf(event.target.id) !== -1) {
      window.setTimeout(syncCloseButton, 0);
    }
  }, true);

  document.addEventListener('input', function (event) {
    if (event.target && event.target.id === 'event-end-at') window.setTimeout(syncCloseButton, 0);
  }, true);

  document.addEventListener('click', function (event) {
    var button = event.target && event.target.closest ? event.target.closest('#btn-close-period-event') : null;
    if (!button) return;

    if (!isSuspend()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    if (checked('event-until-closed')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      showModalMessage('종료일 미정을 해제한 뒤 종료일을 입력하세요.');
      return;
    }
    if (!value('event-end-at')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      showModalMessage('종료일을 입력해야 중지를 종료할 수 있습니다.');
      return;
    }
    closeRequested = true;
  }, true);

  window.fetch = function (url, options) {
    var opts = options || {};
    var method = String(opts.method || 'GET').toUpperCase();
    var textUrl = String(url || '');
    var isUpdate = method === 'POST' && textUrl.indexOf('/api/events/update/') !== -1;
    var forceClose = closeRequested && isUpdate;

    if (forceClose) {
      try {
        var body = JSON.parse(opts.body || '{}');
        var endAt = value('event-end-at');
        var payload = (body.payload && typeof body.payload === 'object') ? Object.assign({}, body.payload) : {};
        payload.period_end_at = endAt;
        payload.period_closed = true;
        body.payload = payload;
        body.status = 'done';
        body.highlight_enabled = false;
        body.until_closed = false;
        body.end_at = endAt;
        body.due_at = null;
        opts = Object.assign({}, opts, { body: JSON.stringify(body) });
      } catch (error) {
        closeRequested = false;
        showModalMessage('중지 종료 요청을 만들 수 없습니다.');
        return previousFetch(url, options);
      }
      closeRequested = false;
    }

    return previousFetch(url, opts).then(function (response) {
      if (forceClose && response.ok) {
        try { window.sessionStorage.setItem(successKey, '중지가 종료되었습니다.'); } catch (e) {}
        window.setTimeout(function () { window.location.reload(); }, 180);
      }
      return response;
    });
  };

  document.addEventListener('DOMContentLoaded', function () {
    bindModalState();
    var message = '';
    try {
      message = window.sessionStorage.getItem(successKey) || '';
      if (message) window.sessionStorage.removeItem(successKey);
    } catch (e) {}
    if (message) window.setTimeout(function () { window.alert(message); }, 120);
  });
})(window, document);
