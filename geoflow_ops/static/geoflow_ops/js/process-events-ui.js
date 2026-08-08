/** GeoFlow process-event timeline. User/API values are rendered with DOM text APIs. */
(function(window) {
  'use strict';

  var config = {
    scopeType: null,
    scopeId: null,
    csrfToken: null,
    eventListUrl: null,
    eventCreateUrl: null,
    eventUpdateUrl: null,
    eventDeleteUrl: null,
    eventModalUiUrl: null,
    presignPutUrl: null,
    commitUrl: null,
    containerSelector: '#eventModalMount',
    timelineListSelector: '#timelineList',
    timelineEmptySelector: '#timelineEmpty',
    addEventBtnSelector: '#btn-add-event',
    canWrite: false
  };

  var modalEl = null;
  var eventModal = null;
  var elAlert = null;
  var fId = null;
  var fStage = null;
  var fType = null;
  var fStatus = null;
  var fTitle = null;
  var fOcc = null;
  var fMemo = null;
  var fScopeType = null;
  var fScopeId = null;
  var fCreatedAt = null;
  var fCreatedBy = null;
  var btnSave = null;
  var btnDel = null;
  var btnAttach = null;
  var attachSection = null;
  var attachList = null;
  var currentEventId = null;
  var isEditMode = false;

  function loadConfigFromDom(selector) {
    var container = document.querySelector(selector);
    if (!container) return false;
    config.scopeType = container.getAttribute('data-scope-type');
    config.scopeId = container.getAttribute('data-scope-id');
    config.csrfToken = container.getAttribute('data-csrf-token') || container.getAttribute('data-csrf');
    config.eventListUrl = container.getAttribute('data-event-list-url') || container.getAttribute('data-events-list-url');
    config.eventCreateUrl = container.getAttribute('data-event-create-url') || container.getAttribute('data-events-create-url');
    config.eventUpdateUrl = container.getAttribute('data-event-update-url') || container.getAttribute('data-events-update-url');
    config.eventDeleteUrl = container.getAttribute('data-event-delete-url') || container.getAttribute('data-events-delete-url');
    config.eventModalUiUrl = container.getAttribute('data-event-modal-ui-url') || container.getAttribute('data-events-modal-ui-url');
    config.presignPutUrl = container.getAttribute('data-presign-put-url');
    config.commitUrl = container.getAttribute('data-commit-url');
    return !!(
      config.scopeType && config.scopeId && config.csrfToken && config.eventListUrl &&
      config.eventCreateUrl && config.eventUpdateUrl && config.eventDeleteUrl &&
      config.eventModalUiUrl && config.presignPutUrl && config.commitUrl
    );
  }

  function urlWithId(template, id) {
    return template.replace('00000000-0000-0000-0000-000000000000', id);
  }

  function showAlert(message) {
    if (!elAlert) return;
    elAlert.textContent = message;
    elAlert.classList.remove('d-none');
  }

  function clearAlert() {
    if (!elAlert) return;
    elAlert.textContent = '';
    elAlert.classList.add('d-none');
  }

  function bindModalDomRefs() {
    modalEl = document.getElementById('eventModal');
    elAlert = document.getElementById('event-alert');
    fId = document.getElementById('event-id');
    fStage = document.getElementById('event-stage');
    fType = document.getElementById('event-type');
    fStatus = document.getElementById('event-status');
    fTitle = document.getElementById('event-title');
    fOcc = document.getElementById('event-occurred-at');
    fMemo = document.getElementById('event-memo');
    fScopeType = document.getElementById('event-scope-type');
    fScopeId = document.getElementById('event-scope-id');
    fCreatedAt = document.getElementById('event-created-at');
    fCreatedBy = document.getElementById('event-created-by');
    btnSave = document.getElementById('btn-save-event');
    btnDel = document.getElementById('btn-delete-event-modal');
    btnAttach = document.getElementById('btn-timeline-attach');
    attachSection = document.getElementById('event-attach-section');
    attachList = document.getElementById('event-attachment-list');

    var form = modalEl ? modalEl.querySelector('form') : null;
    if (form) form.onsubmit = function(e) { e.preventDefault(); return false; };
    if (btnSave) btnSave.onclick = function(e) { e.preventDefault(); saveEvent(); };
    if (btnDel) btnDel.onclick = function(e) { e.preventDefault(); removeEvent(); };
    if (btnAttach) btnAttach.onclick = function(e) { e.preventDefault(); uploadFilesToEvent(); };
    applyWriteMode();
  }

  function applyWriteMode() {
    var editable = [fStage, fType, fStatus, fTitle, fOcc, fMemo];
    editable.forEach(function(el) { if (el) el.disabled = !config.canWrite; });
    [btnSave, btnDel, btnAttach].forEach(function(el) {
      if (!el) return;
      el.classList.toggle('d-none', !config.canWrite);
      el.disabled = !config.canWrite;
    });
    var add = document.querySelector(config.addEventBtnSelector);
    if (add) {
      add.classList.toggle('d-none', !config.canWrite);
      add.disabled = !config.canWrite;
    }
  }

  function ensureModalLoaded() {
    if (document.getElementById('eventModal')) {
      bindModalDomRefs();
      return Promise.resolve();
    }
    var mount = document.querySelector(config.containerSelector);
    if (!mount) return Promise.reject(new Error('Modal mount container not found'));
    var url = config.eventModalUiUrl + '?scope_type=' + encodeURIComponent(config.scopeType) + '&scope_id=' + encodeURIComponent(config.scopeId);
    return fetch(url, { method: 'GET', headers: { 'X-CSRFToken': config.csrfToken }, credentials: 'same-origin' })
      .then(function(r) {
        if (!r.ok) throw new Error('Modal UI load failed (' + r.status + ')');
        return r.text();
      })
      .then(function(html) {
        // Server-rendered modal shell is trusted application HTML; user/API values below never use HTML parsing sinks.
        mount.innerHTML = html;
        modalEl = document.getElementById('eventModal');
        if (!modalEl) throw new Error('eventModal not found');
        eventModal = bootstrap.Modal.getOrCreateInstance(modalEl);
        bindModalDomRefs();
      });
  }

  function setAttachMode(enabled) {
    if (attachSection) attachSection.classList.toggle('d-none', !enabled);
  }

  function renderAttachments(attachments) {
    if (!attachList) return;
    attachList.replaceChildren();
    if (!attachments || !attachments.length) {
      var empty = document.createElement('div');
      empty.className = 'text-muted small';
      empty.textContent = '첨부파일이 없습니다.';
      attachList.appendChild(empty);
      return;
    }
    attachments.forEach(function(att) {
      var row = document.createElement('div');
      row.className = 'd-flex justify-content-between align-items-center mb-2 p-2 border rounded';
      var name = document.createElement('div');
      name.className = 'text-truncate';
      name.textContent = att.original_name || att.id || '파일';
      name.title = att.original_name || att.id || '파일';
      var actions = document.createElement('div');
      actions.className = 'd-flex gap-2';
      var open = document.createElement('button');
      open.type = 'button';
      open.className = 'btn btn-sm btn-outline-secondary';
      open.textContent = '열기';
      open.addEventListener('click', function() {
        window.getPresignedGetUrl(att.id, config.csrfToken, 'inline')
          .then(function(url) { window.open(url, '_blank', 'noopener'); })
          .catch(function() { showAlert('파일을 열 수 없습니다.'); });
      });
      actions.appendChild(open);
      if (config.canWrite) {
        var remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn-sm btn-outline-danger';
        remove.textContent = '삭제';
        remove.addEventListener('click', function() {
          if (!confirm('첨부파일을 삭제할까요?')) return;
          window.deleteAttachment(att.id, config.csrfToken)
            .then(function() { return loadEvents(true); })
            .catch(function() { showAlert('첨부파일 삭제에 실패했습니다.'); });
        });
        actions.appendChild(remove);
      }
      row.appendChild(name);
      row.appendChild(actions);
      attachList.appendChild(row);
    });
  }

  function resetModal() {
    clearAlert();
    isEditMode = false;
    currentEventId = null;
    [[fId, ''], [fStage, ''], [fType, ''], [fStatus, 'draft'], [fTitle, ''], [fOcc, ''], [fMemo, ''], [fScopeType, config.scopeType], [fScopeId, config.scopeId], [fCreatedAt, ''], [fCreatedBy, '']]
      .forEach(function(pair) { if (pair[0]) pair[0].value = pair[1] || ''; });
    setAttachMode(false);
    if (attachList) attachList.replaceChildren();
    var label = document.getElementById('eventModalLabel');
    if (label) label.textContent = '새 이벤트 추가';
    applyWriteMode();
  }

  function loadEventToModal(ev) {
    clearAlert();
    isEditMode = true;
    currentEventId = ev.id;
    if (fId) fId.value = ev.id || '';
    if (fStage) fStage.value = ev.stage || '';
    if (fType) fType.value = ev.event_type || '';
    if (fStatus) fStatus.value = ev.status || '';
    if (fTitle) fTitle.value = ev.title || '';
    if (fOcc) fOcc.value = ev.occurred_at ? String(ev.occurred_at).slice(0, 10) : '';
    if (fMemo) fMemo.value = ev.memo || '';
    if (fScopeType) fScopeType.value = ev.scope_type || config.scopeType;
    if (fScopeId) fScopeId.value = ev.scope_id || config.scopeId;
    if (fCreatedAt) fCreatedAt.value = ev.created_at || '';
    if (fCreatedBy) fCreatedBy.value = ev.created_by || '';
    setAttachMode(true);
    renderAttachments(ev.attachments || []);
    var label = document.getElementById('eventModalLabel');
    if (label) label.textContent = config.canWrite ? '이벤트 수정' : '이벤트 보기';
    applyWriteMode();
  }

  function openCreateModal() {
    if (!config.canWrite) return;
    ensureModalLoaded().then(function() {
      resetModal();
      if (eventModal) eventModal.show();
    }).catch(function() { alert('이벤트 팝업을 열 수 없습니다.'); });
  }

  function openEditModal(ev) {
    ensureModalLoaded().then(function() {
      loadEventToModal(ev);
      if (eventModal) eventModal.show();
    }).catch(function() { alert('이벤트 팝업을 열 수 없습니다.'); });
  }

  function iconClassForFilename(filename) {
    var ext = String(filename || '').split('.').pop().toLowerCase();
    if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].indexOf(ext) >= 0) return 'fa-file-image';
    if (ext === 'pdf') return 'fa-file-pdf';
    if (['doc', 'docx'].indexOf(ext) >= 0) return 'fa-file-word';
    if (['xls', 'xlsx'].indexOf(ext) >= 0) return 'fa-file-excel';
    if (['zip', 'rar', '7z'].indexOf(ext) >= 0) return 'fa-file-archive';
    return 'fa-file';
  }

  function renderTimeline(events) {
    var list = document.querySelector(config.timelineListSelector);
    var empty = document.querySelector(config.timelineEmptySelector);
    if (!list) return;
    list.replaceChildren();
    var arr = (events || []).slice().sort(function(a, b) {
      var ad = a.occurred_at || a.created_at || '';
      var bd = b.occurred_at || b.created_at || '';
      return bd > ad ? 1 : (bd < ad ? -1 : 0);
    });
    if (!arr.length) {
      if (empty) empty.classList.remove('d-none');
      return;
    }
    if (empty) empty.classList.add('d-none');

    var ul = document.createElement('ul');
    ul.className = 'timeline mt-2 mb-0';
    arr.forEach(function(ev) {
      var li = document.createElement('li');
      li.className = 'timeline-item mb-4';
      li.style.cursor = 'pointer';
      var card = document.createElement('div');
      card.className = 'timeline-card-content';
      var header = document.createElement('div');
      header.className = 'd-flex align-items-start justify-content-between gap-2 flex-wrap mb-1';
      var strong = document.createElement('strong');
      strong.className = 'flex-grow-1 min-w-0';
      strong.textContent = ev.title || '[' + (ev.event_type || '이벤트') + ']';
      header.appendChild(strong);
      var baseDate = ev.occurred_at || ev.created_at;
      if (baseDate) {
        var date = document.createElement('span');
        date.className = 'text-muted small text-nowrap';
        date.textContent = String(baseDate).slice(0, 10);
        header.appendChild(date);
      }
      card.appendChild(header);
      if (ev.memo) {
        var memo = document.createElement('p');
        memo.className = 'mb-1';
        memo.textContent = ev.memo.length > 80 ? ev.memo.slice(0, 80) + '...' : ev.memo;
        card.appendChild(memo);
      }
      if (ev.attachments && ev.attachments.length) {
        var files = document.createElement('div');
        files.className = 'mt-1';
        ev.attachments.forEach(function(att) {
          var filename = att.original_name || att.id || '파일';
          var button = document.createElement('button');
          button.type = 'button';
          button.className = 'btn btn-sm btn-link text-start p-0 me-3 timeline-attachment-link d-inline-flex align-items-center';
          button.dataset.attId = String(att.id || '');
          button.style.maxWidth = '100%';
          var icon = document.createElement('i');
          icon.className = 'fa ' + iconClassForFilename(filename) + ' me-1 flex-shrink-0';
          var span = document.createElement('span');
          span.className = 'timeline-filename';
          span.textContent = filename;
          span.title = filename;
          button.appendChild(icon);
          button.appendChild(span);
          files.appendChild(button);
        });
        card.appendChild(files);
      }
      li.appendChild(card);
      li.addEventListener('click', function(e) {
        if (e.target.closest('.timeline-attachment-link')) return;
        e.preventDefault();
        openEditModal(ev);
      });
      ul.appendChild(li);
    });
    list.appendChild(ul);
  }

  function handleTimelineAttachmentClick(e) {
    var button = e.target.closest('.timeline-attachment-link');
    if (!button) return;
    e.preventDefault();
    e.stopPropagation();
    var id = button.dataset.attId;
    if (!id || typeof window.getPresignedGetUrl !== 'function') return;
    window.getPresignedGetUrl(id, config.csrfToken, 'inline')
      .then(function(url) { window.open(url, '_blank', 'noopener'); })
      .catch(function() { alert('파일 미리보기에 실패했습니다.'); });
  }

  function loadEvents(keepModalOpen) {
    var url = config.eventListUrl + '?scope_type=' + encodeURIComponent(config.scopeType) + '&scope_id=' + encodeURIComponent(config.scopeId);
    return fetch(url, { method: 'GET', headers: { 'X-CSRFToken': config.csrfToken }, credentials: 'same-origin' })
      .then(function(r) { if (!r.ok) throw new Error('load failed'); return r.json(); })
      .then(function(data) {
        config.canWrite = !!data.can_write;
        applyWriteMode();
        var events = data.events || [];
        renderTimeline(events);
        if (keepModalOpen && isEditMode && currentEventId) {
          var ev = events.find(function(item) { return item.id === currentEventId; });
          if (ev) loadEventToModal(ev);
        }
      });
  }

  function saveEvent() {
    if (!config.canWrite) return;
    clearAlert();
    var eventId = (fId && fId.value) ? fId.value : currentEventId;
    var isUpdate = !!eventId;
    var payload = {
      scope_type: config.scopeType,
      scope_id: config.scopeId,
      stage: fStage ? fStage.value : '',
      event_type: fType ? fType.value : '',
      status: fStatus ? fStatus.value : 'draft',
      title: fTitle ? fTitle.value : '',
      occurred_at: fOcc && fOcc.value ? fOcc.value : null,
      memo: fMemo ? fMemo.value : ''
    };
    if (!payload.stage || !payload.event_type) {
      showAlert('단계와 이벤트 유형을 선택하세요.');
      return;
    }
    if (btnSave) btnSave.disabled = true;
    var url = isUpdate ? urlWithId(config.eventUpdateUrl, eventId) : config.eventCreateUrl;
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': config.csrfToken },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).then(function(r) {
      if (!r.ok) throw new Error('save failed');
      return r.json();
    }).then(function(data) {
      currentEventId = data.event_id || (data.event && data.event.id) || currentEventId;
      isEditMode = true;
      if (fId) fId.value = currentEventId || '';
      return loadEvents(true);
    }).catch(function() {
      showAlert('이벤트 저장에 실패했습니다.');
    }).finally(function() {
      if (btnSave) btnSave.disabled = !config.canWrite;
    });
  }

  function removeEvent() {
    if (!config.canWrite || !currentEventId) return;
    if (!confirm('정말 이 이벤트를 삭제하시겠습니까?')) return;
    fetch(urlWithId(config.eventDeleteUrl, currentEventId), {
      method: 'POST',
      headers: { 'X-CSRFToken': config.csrfToken },
      credentials: 'same-origin'
    }).then(function(r) {
      if (!r.ok) throw new Error('delete failed');
      if (eventModal) eventModal.hide();
      currentEventId = null;
      isEditMode = false;
      return loadEvents(false);
    }).catch(function() { showAlert('이벤트 삭제에 실패했습니다.'); });
  }

  function uploadFilesToEvent() {
    if (!config.canWrite || !currentEventId || !window.uploadToEvent) return;
    var input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.onchange = function() {
      var files = Array.prototype.slice.call(input.files || []);
      var chain = Promise.resolve();
      files.forEach(function(file) {
        chain = chain.then(function() {
          return window.uploadToEvent({
            file: file,
            eventId: currentEventId,
            csrfToken: config.csrfToken,
            purpose: 'doc',
            presignPutUrl: config.presignPutUrl,
            commitUrl: config.commitUrl
          });
        });
      });
      chain.then(function() { return loadEvents(true); })
        .catch(function() { showAlert('업로드에 실패했습니다.'); });
    };
    input.click();
  }

  function init(selector) {
    config.containerSelector = selector || config.containerSelector;
    if (!loadConfigFromDom(config.containerSelector)) return;
    var add = document.querySelector(config.addEventBtnSelector);
    if (add) add.addEventListener('click', openCreateModal);
    var list = document.querySelector(config.timelineListSelector);
    if (list) list.addEventListener('click', handleTimelineAttachmentClick);
    loadEvents().catch(function() {
      var empty = document.querySelector(config.timelineEmptySelector);
      if (empty) {
        empty.textContent = '이벤트를 불러올 수 없습니다.';
        empty.classList.remove('d-none');
      }
    });
  }

  window.ProcessEventsUI = {
    init: init,
    loadEvents: loadEvents,
    openCreateModal: openCreateModal,
    openEditModal: openEditModal
  };
})(window);
