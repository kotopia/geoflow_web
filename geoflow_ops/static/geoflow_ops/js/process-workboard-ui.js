/** GeoFlow Phase 4 cross-department workboard UI. */
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
    workflowOptionsUrl: '/api/events/workflow-options/',
    assignmentOptionsUrl: null,
    presignPutUrl: null,
    commitUrl: null,
    containerSelector: '#eventModalMount',
    timelineListSelector: '#timelineList',
    timelineEmptySelector: '#timelineEmpty',
    addEventBtnSelector: '#btn-add-event',
    canWrite: false,
    canAssign: false
  };

  var modalEl = null;
  var eventModal = null;
  var currentEventId = null;
  var currentEvent = null;
  var currentCanWrite = false;
  var assignmentEmployees = [];
  var workflowPromise = null;

  var fId, fStage, fType, fStatus, fTitle, fOcc, fDue, fMemo;
  var fScopeType, fScopeId, fCreatedAt, fCreatedBy, fDept, fAssignee;
  var elAlert, assignmentHelp, btnSave, btnDel, btnAttach, attachSection, attachList;

  var stageLabels = {
    pre_contract: '계약전', contract: '계약', kickoff: '착수', execution: '수행',
    inspection: '검사', closeout: '준공', billing: '청구/정산'
  };
  var statusLabels = { draft: '작성중', open: '진행중', done: '완료', void: '취소' };
  var eventTypeLabels = {};
  var workflowOptions = {
    stages: [
      {code:'pre_contract', label:'계약전'}, {code:'contract', label:'계약'},
      {code:'kickoff', label:'착수'}, {code:'execution', label:'수행'},
      {code:'inspection', label:'검사'}, {code:'closeout', label:'준공'},
      {code:'billing', label:'청구/정산'}
    ],
    statuses: [
      {code:'draft', label:'작성중'}, {code:'open', label:'진행중'},
      {code:'done', label:'완료'}, {code:'void', label:'취소'}
    ],
    types_by_stage: {
      pre_contract: [{code:'estimate',label:'견적제출'},{code:'etc',label:'기타'}],
      contract: [
        {code:'contract_doc',label:'계약체결'},{code:'contract_change',label:'계약변경'},
        {code:'period_extension',label:'기간연장'},{code:'suspend',label:'중지'},
        {code:'resume',label:'재개'},{code:'contract_cancel',label:'계약취소'},
        {code:'etc',label:'기타'}
      ],
      kickoff: [{code:'kickoff',label:'착수'},{code:'kickoff_doc',label:'착수계'},{code:'etc',label:'기타'}],
      execution: [{code:'progress_report',label:'공정보고'},{code:'etc',label:'기타'}],
      inspection: [
        {code:'inspection_request',label:'검사요청'},{code:'inspection',label:'검사완료'},
        {code:'correction_request',label:'보완요청'},{code:'reinspection',label:'재검사'},
        {code:'etc',label:'기타'}
      ],
      closeout: [{code:'completion_doc',label:'준공계'},{code:'delivery',label:'납품완료'},{code:'etc',label:'기타'}],
      billing: [
        {code:'advance_payment',label:'선금'},{code:'progress_invoice',label:'기성청구'},
        {code:'invoice',label:'청구'},{code:'tax_invoice',label:'세금계산서'},
        {code:'payment',label:'입금/지급완료'},{code:'etc',label:'기타'}
      ]
    }
  };

  function refreshWorkflowLabels() {
    stageLabels = {};
    statusLabels = {};
    eventTypeLabels = {};
    (workflowOptions.stages || []).forEach(function(row) { stageLabels[row.code] = row.label || row.code; });
    (workflowOptions.statuses || []).forEach(function(row) { statusLabels[row.code] = row.label || row.code; });
    Object.keys(workflowOptions.types_by_stage || {}).forEach(function(stage) {
      (workflowOptions.types_by_stage[stage] || []).forEach(function(row) {
        eventTypeLabels[row.code] = row.label || row.code;
      });
    });
  }
  refreshWorkflowLabels();

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
    config.workflowOptionsUrl = container.getAttribute('data-workflow-options-url') || config.workflowOptionsUrl;
    config.assignmentOptionsUrl = container.getAttribute('data-assignment-options-url');
    config.presignPutUrl = container.getAttribute('data-presign-put-url');
    config.commitUrl = container.getAttribute('data-commit-url');
    return !!(
      config.scopeType && config.scopeId && config.csrfToken && config.eventListUrl &&
      config.eventCreateUrl && config.eventUpdateUrl && config.eventDeleteUrl &&
      config.eventModalUiUrl && config.assignmentOptionsUrl && config.presignPutUrl && config.commitUrl
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

  function appendOption(select, code, label, selected) {
    if (!select) return;
    var option = document.createElement('option');
    option.value = code;
    option.textContent = label || code;
    option.selected = String(selected || '') === String(code);
    select.appendChild(option);
  }

  function populateEventTypes(stage, selectedType, preserveHistorical) {
    if (!fType) return;
    var rows = (workflowOptions.types_by_stage || {})[stage] || [];
    fType.replaceChildren();
    rows.forEach(function(row) { appendOption(fType, row.code, row.label, selectedType); });
    var found = rows.some(function(row) { return String(row.code) === String(selectedType || ''); });
    if (preserveHistorical && selectedType && !found) {
      appendOption(fType, selectedType, eventTypeLabels[selectedType] || selectedType + ' (기존값)', selectedType);
    }
    if (!fType.value && rows.length) fType.value = rows[0].code;
  }

  function applyWorkflowSelects(selectedStage, selectedType, selectedStatus, preserveHistorical) {
    if (!fStage || !fStatus) return;
    var stages = workflowOptions.stages || [];
    var statuses = workflowOptions.statuses || [];
    fStage.replaceChildren();
    stages.forEach(function(row) { appendOption(fStage, row.code, row.label, selectedStage); });
    var stageFound = stages.some(function(row) { return String(row.code) === String(selectedStage || ''); });
    if (preserveHistorical && selectedStage && !stageFound) {
      appendOption(fStage, selectedStage, stageLabels[selectedStage] || selectedStage + ' (기존값)', selectedStage);
    }
    if (!fStage.value && stages.length) fStage.value = stages[0].code;

    fStatus.replaceChildren();
    statuses.forEach(function(row) { appendOption(fStatus, row.code, row.label, selectedStatus); });
    var statusFound = statuses.some(function(row) { return String(row.code) === String(selectedStatus || ''); });
    if (preserveHistorical && selectedStatus && !statusFound) {
      appendOption(fStatus, selectedStatus, statusLabels[selectedStatus] || selectedStatus + ' (기존값)', selectedStatus);
    }
    if (!fStatus.value && statuses.length) fStatus.value = statuses[0].code;

    populateEventTypes(fStage.value, selectedType, preserveHistorical);
  }

  function loadWorkflowOptions() {
    if (workflowPromise) return workflowPromise;
    workflowPromise = fetch(config.workflowOptionsUrl, {
      method: 'GET',
      headers: { 'X-CSRFToken': config.csrfToken },
      credentials: 'same-origin'
    }).then(function(r) {
      if (!r.ok) throw new Error('workflow options failed');
      return r.json();
    }).then(function(data) {
      if (Array.isArray(data.stages) && data.stages.length) workflowOptions.stages = data.stages;
      if (Array.isArray(data.statuses) && data.statuses.length) workflowOptions.statuses = data.statuses;
      if (data.types_by_stage && typeof data.types_by_stage === 'object') workflowOptions.types_by_stage = data.types_by_stage;
      refreshWorkflowLabels();
      return workflowOptions;
    }).catch(function() {
      return workflowOptions;
    });
    return workflowPromise;
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
    fDue = document.getElementById('event-due-at');
    fMemo = document.getElementById('event-memo');
    fScopeType = document.getElementById('event-scope-type');
    fScopeId = document.getElementById('event-scope-id');
    fCreatedAt = document.getElementById('event-created-at');
    fCreatedBy = document.getElementById('event-created-by');
    fDept = document.getElementById('event-owner-department');
    fAssignee = document.getElementById('event-assignee-employee');
    assignmentHelp = document.getElementById('event-assignment-help');
    btnSave = document.getElementById('btn-save-event');
    btnDel = document.getElementById('btn-delete-event-modal');
    btnAttach = document.getElementById('btn-timeline-attach');
    attachSection = document.getElementById('event-attach-section');
    attachList = document.getElementById('event-attachment-list');

    var form = modalEl ? modalEl.querySelector('form') : null;
    if (form) form.onsubmit = function(e) { e.preventDefault(); return false; };
    if (btnSave) btnSave.onclick = function(e) { e.preventDefault(); saveEvent(); };
    if (btnDel) btnDel.onclick = function(e) { e.preventDefault(); voidEvent(); };
    if (btnAttach) btnAttach.onclick = function(e) { e.preventDefault(); uploadFilesToEvent(); };
    if (fDept) fDept.onchange = filterAssigneesByDepartment;
    if (fStage) {
      fStage.onchange = function() {
        populateEventTypes(fStage.value, '', false);
      };
    }
    applyWriteMode();
  }

  function ensureModalLoaded(scopeType, scopeId) {
    if (document.getElementById('eventModal')) {
      bindModalDomRefs();
      return loadWorkflowOptions();
    }
    var mount = document.querySelector(config.containerSelector);
    if (!mount) return Promise.reject(new Error('Modal mount container not found'));
    var url = config.eventModalUiUrl + '?scope_type=' + encodeURIComponent(scopeType) + '&scope_id=' + encodeURIComponent(scopeId);
    return fetch(url, { method: 'GET', headers: { 'X-CSRFToken': config.csrfToken }, credentials: 'same-origin' })
      .then(function(r) {
        if (!r.ok) throw new Error('Modal UI load failed (' + r.status + ')');
        return r.text();
      })
      .then(function(html) {
        mount.innerHTML = html;
        modalEl = document.getElementById('eventModal');
        if (!modalEl) throw new Error('eventModal not found');
        eventModal = bootstrap.Modal.getOrCreateInstance(modalEl);
        bindModalDomRefs();
        return loadWorkflowOptions();
      });
  }

  function applyWriteMode() {
    [fStage, fType, fStatus, fTitle, fOcc, fDue, fMemo].forEach(function(el) {
      if (el) el.disabled = !currentCanWrite;
    });
    [fDept, fAssignee].forEach(function(el) {
      if (el) el.disabled = !currentCanWrite || !config.canAssign;
    });
    [btnSave, btnDel, btnAttach].forEach(function(el) {
      if (!el) return;
      el.classList.toggle('d-none', !currentCanWrite);
      el.disabled = !currentCanWrite;
    });
    if (assignmentHelp) {
      assignmentHelp.textContent = config.canAssign
        ? '담당 부서와 담당자는 같은 tenant의 직원 디렉터리에서 선택합니다.'
        : '디렉터리 조회 권한이 없어 담당자 배정은 변경할 수 없습니다.';
    }
  }

  function loadAssignmentOptions(scopeType, scopeId, selectedDept, selectedEmployee) {
    config.canAssign = false;
    assignmentEmployees = [];
    if (!config.assignmentOptionsUrl || !currentCanWrite) {
      populateAssignmentSelects([], [], selectedDept, selectedEmployee);
      applyWriteMode();
      return Promise.resolve();
    }
    var url = config.assignmentOptionsUrl + '?scope_type=' + encodeURIComponent(scopeType) + '&scope_id=' + encodeURIComponent(scopeId);
    return fetch(url, { method: 'GET', headers: { 'X-CSRFToken': config.csrfToken }, credentials: 'same-origin' })
      .then(function(r) { if (!r.ok) throw new Error('assignment options failed'); return r.json(); })
      .then(function(data) {
        config.canAssign = !!data.can_assign;
        assignmentEmployees = data.employees || [];
        populateAssignmentSelects(data.departments || [], assignmentEmployees, selectedDept, selectedEmployee);
        applyWriteMode();
      })
      .catch(function() {
        config.canAssign = false;
        populateAssignmentSelects([], [], selectedDept, selectedEmployee);
        applyWriteMode();
      });
  }

  function replaceOptions(select, rows, selected, labelBuilder) {
    if (!select) return;
    select.replaceChildren();
    var empty = document.createElement('option');
    empty.value = '';
    empty.textContent = '미지정';
    select.appendChild(empty);
    rows.forEach(function(row) {
      var option = document.createElement('option');
      option.value = row.id;
      option.textContent = labelBuilder(row);
      if (selected && String(selected) === String(row.id)) option.selected = true;
      select.appendChild(option);
    });
  }

  function populateAssignmentSelects(departments, employees, selectedDept, selectedEmployee) {
    replaceOptions(fDept, departments, selectedDept, function(row) { return row.name || row.id; });
    replaceOptions(fAssignee, employees, selectedEmployee, function(row) {
      return (row.name || row.id) + (row.title ? ' · ' + row.title : '');
    });
  }

  function filterAssigneesByDepartment() {
    if (!fAssignee) return;
    var selectedEmployee = fAssignee.value;
    var departmentId = fDept ? fDept.value : '';
    var rows = assignmentEmployees.filter(function(row) {
      return !departmentId || !row.department_id || String(row.department_id) === String(departmentId);
    });
    replaceOptions(fAssignee, rows, selectedEmployee, function(row) {
      return (row.name || row.id) + (row.title ? ' · ' + row.title : '');
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
      var open = document.createElement('button');
      open.type = 'button';
      open.className = 'btn btn-sm btn-outline-secondary';
      open.textContent = '열기';
      open.onclick = function() {
        window.getPresignedGetUrl(att.id, config.csrfToken, 'inline')
          .then(function(url) { window.open(url, '_blank', 'noopener'); })
          .catch(function() { showAlert('파일을 열 수 없습니다.'); });
      };
      row.appendChild(name);
      row.appendChild(open);
      attachList.appendChild(row);
    });
  }

  function resetModal() {
    clearAlert();
    currentEventId = null;
    currentEvent = null;
    currentCanWrite = config.canWrite;
    var preferredStage = (workflowOptions.types_by_stage || {}).execution ? 'execution' : ((workflowOptions.stages || [])[0] || {}).code;
    var preferredStatus = (workflowOptions.statuses || []).some(function(row) { return row.code === 'draft'; }) ? 'draft' : (((workflowOptions.statuses || [])[0] || {}).code || '');
    var preferredTypes = (workflowOptions.types_by_stage || {})[preferredStage] || [];
    var preferredType = preferredTypes.some(function(row) { return row.code === 'progress_report'; })
      ? 'progress_report'
      : ((preferredTypes[0] || {}).code || '');
    applyWorkflowSelects(preferredStage || '', preferredType, preferredStatus, false);
    [[fId, ''], [fTitle, ''], [fOcc, ''], [fDue, ''], [fMemo, ''], [fScopeType, config.scopeType],
     [fScopeId, config.scopeId], [fCreatedAt, ''], [fCreatedBy, '']]
      .forEach(function(pair) { if (pair[0]) pair[0].value = pair[1] || ''; });
    setAttachMode(false);
    if (attachList) attachList.replaceChildren();
    var label = document.getElementById('eventModalLabel');
    if (label) label.textContent = '새 업무 이벤트';
    applyWriteMode();
  }

  function loadEventToModal(ev) {
    clearAlert();
    currentEvent = ev;
    currentEventId = ev.id;
    currentCanWrite = !!ev.can_write;
    applyWorkflowSelects(ev.stage || '', ev.event_type || '', ev.status || '', true);
    if (fId) fId.value = ev.id || '';
    if (fTitle) fTitle.value = ev.title || '';
    if (fOcc) fOcc.value = ev.occurred_at ? String(ev.occurred_at).slice(0, 10) : '';
    if (fDue) fDue.value = ev.due_at ? String(ev.due_at).slice(0, 10) : '';
    if (fMemo) fMemo.value = ev.memo || '';
    if (fScopeType) fScopeType.value = ev.scope_type || config.scopeType;
    if (fScopeId) fScopeId.value = ev.scope_id || config.scopeId;
    if (fCreatedAt) fCreatedAt.value = ev.created_at || '';
    if (fCreatedBy) fCreatedBy.value = ev.created_by || '';
    setAttachMode(true);
    renderAttachments(ev.attachments || []);
    var label = document.getElementById('eventModalLabel');
    if (label) label.textContent = currentCanWrite ? '업무 이벤트 수정' : '업무 이벤트 보기';
    applyWriteMode();
  }

  function openCreateModal() {
    if (!config.canWrite) return;
    ensureModalLoaded(config.scopeType, config.scopeId)
      .then(function() {
        resetModal();
        return loadAssignmentOptions(config.scopeType, config.scopeId, '', '');
      })
      .then(function() { if (eventModal) eventModal.show(); })
      .catch(function() { alert('업무 이벤트 팝업을 열 수 없습니다.'); });
  }

  function openEditModal(ev) {
    ensureModalLoaded(ev.scope_type || config.scopeType, ev.scope_id || config.scopeId)
      .then(function() {
        loadEventToModal(ev);
        return loadAssignmentOptions(
          ev.scope_type || config.scopeType,
          ev.scope_id || config.scopeId,
          ev.owner_department_id || '',
          ev.assignee_employee_id || ''
        );
      })
      .then(function() { if (eventModal) eventModal.show(); })
      .catch(function() { alert('업무 이벤트 팝업을 열 수 없습니다.'); });
  }

  function renderWorkflowSummary(events) {
    var active = (events || []).filter(function(ev) { return ev.status !== 'void'; });
    active.sort(function(a, b) {
      var ad = a.occurred_at || a.created_at || '';
      var bd = b.occurred_at || b.created_at || '';
      return bd > ad ? 1 : (bd < ad ? -1 : 0);
    });
    var latest = active[0] || null;
    var openTasks = active.filter(function(ev) { return ev.status === 'open' || ev.status === 'draft'; });
    openTasks.sort(function(a, b) {
      var ad = a.due_at || '9999-12-31';
      var bd = b.due_at || '9999-12-31';
      return ad > bd ? 1 : (ad < bd ? -1 : 0);
    });
    var next = openTasks[0] || null;

    var stage = document.getElementById('workflowStage');
    var nextTask = document.getElementById('workflowNextTask');
    var assignee = document.getElementById('workflowAssignee');
    var count = document.getElementById('workflowOpenCount');
    if (stage) stage.textContent = latest ? (stageLabels[latest.stage] || latest.stage || '-') : '등록 전';
    if (nextTask) nextTask.textContent = next ? (next.title || eventTypeLabels[next.event_type] || next.event_type || '업무') : '대기 업무 없음';
    if (assignee) {
      assignee.textContent = next && next.assignee_employee_name
        ? next.assignee_employee_name + (next.owner_department_name ? ' · ' + next.owner_department_name : '')
        : (next && next.owner_department_name ? next.owner_department_name : '미지정');
    }
    if (count) count.textContent = String(openTasks.length);
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
    renderWorkflowSummary(arr);
    if (!arr.length) {
      if (empty) empty.classList.remove('d-none');
      return;
    }
    if (empty) empty.classList.add('d-none');

    arr.forEach(function(ev) {
      var card = document.createElement('div');
      card.className = 'border rounded p-3 mb-2';
      card.style.cursor = 'pointer';

      var header = document.createElement('div');
      header.className = 'd-flex justify-content-between gap-2 flex-wrap';
      var title = document.createElement('strong');
      title.textContent = ev.title || eventTypeLabels[ev.event_type] || ev.event_type || '업무 이벤트';
      var date = document.createElement('span');
      date.className = 'small text-muted';
      date.textContent = String(ev.occurred_at || ev.created_at || '').slice(0, 10);
      header.appendChild(title);
      header.appendChild(date);
      card.appendChild(header);

      var meta = document.createElement('div');
      meta.className = 'small text-muted mt-1';
      var scopeLabel = ev.scope_type === 'contract' ? '계약' : (ev.project_name ? '프로젝트 ' + ev.project_name : '프로젝트');
      meta.textContent = scopeLabel + ' · ' + (stageLabels[ev.stage] || ev.stage || '-') + ' · ' + (statusLabels[ev.status] || ev.status || '-');
      card.appendChild(meta);

      if (ev.owner_department_name || ev.assignee_employee_name || ev.due_at) {
        var assignment = document.createElement('div');
        assignment.className = 'small mt-2';
        var parts = [];
        if (ev.owner_department_name) parts.push('부서 ' + ev.owner_department_name);
        if (ev.assignee_employee_name) parts.push('담당 ' + ev.assignee_employee_name + (ev.assignee_employee_title ? ' ' + ev.assignee_employee_title : ''));
        if (ev.due_at) parts.push('예정 ' + String(ev.due_at).slice(0, 10));
        assignment.textContent = parts.join(' · ');
        card.appendChild(assignment);
      }

      if (ev.memo) {
        var memo = document.createElement('div');
        memo.className = 'small mt-2 text-muted';
        memo.textContent = ev.memo.length > 100 ? ev.memo.slice(0, 100) + '...' : ev.memo;
        card.appendChild(memo);
      }

      card.onclick = function(e) {
        if (e.target.closest('.timeline-attachment-link')) return;
        openEditModal(ev);
      };
      list.appendChild(card);
    });
  }

  function loadEvents(keepModalOpen) {
    var url = config.eventListUrl + '?scope_type=' + encodeURIComponent(config.scopeType) + '&scope_id=' + encodeURIComponent(config.scopeId);
    return fetch(url, { method: 'GET', headers: { 'X-CSRFToken': config.csrfToken }, credentials: 'same-origin' })
      .then(function(r) { if (!r.ok) throw new Error('load failed'); return r.json(); })
      .then(function(data) {
        config.canWrite = !!data.can_write;
        currentCanWrite = config.canWrite;
        var add = document.querySelector(config.addEventBtnSelector);
        if (add) {
          add.classList.toggle('d-none', !config.canWrite);
          add.disabled = !config.canWrite;
        }
        var events = data.events || [];
        renderTimeline(events);
        if (keepModalOpen && currentEventId) {
          var ev = events.find(function(item) { return item.id === currentEventId; });
          if (ev) loadEventToModal(ev);
        }
        return data;
      });
  }

  function saveEvent() {
    if (!currentCanWrite) return;
    clearAlert();
    var eventId = (fId && fId.value) ? fId.value : currentEventId;
    var isUpdate = !!eventId;
    var scopeType = isUpdate && currentEvent ? currentEvent.scope_type : config.scopeType;
    var scopeId = isUpdate && currentEvent ? currentEvent.scope_id : config.scopeId;
    var payload = {
      scope_type: scopeType,
      scope_id: scopeId,
      stage: fStage ? fStage.value : '',
      event_type: fType ? fType.value : '',
      status: fStatus ? fStatus.value : 'draft',
      title: fTitle ? fTitle.value : '',
      occurred_at: fOcc && fOcc.value ? fOcc.value : null,
      due_at: fDue && fDue.value ? fDue.value : null,
      memo: fMemo ? fMemo.value : ''
    };
    if (config.canAssign) {
      payload.owner_department_id = fDept && fDept.value ? fDept.value : null;
      payload.assignee_employee_id = fAssignee && fAssignee.value ? fAssignee.value : null;
    }
    if (!payload.stage || !payload.event_type) {
      showAlert('단계와 업무 유형을 선택하세요.');
      return;
    }
    var allowedTypes = (workflowOptions.types_by_stage || {})[payload.stage] || [];
    if (!allowedTypes.some(function(row) { return String(row.code) === String(payload.event_type); })) {
      showAlert('선택한 업무 단계에서 사용할 수 없는 업무 유형입니다.');
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
      if (!r.ok) return r.json().catch(function() { return {}; }).then(function(data) { throw new Error(data.error || 'save failed'); });
      return r.json();
    }).then(function(data) {
      currentEventId = data.event_id || (data.event && data.event.id) || currentEventId;
      if (!isUpdate && data.event) currentEvent = data.event;
      return loadEvents(true);
    }).catch(function(err) {
      showAlert(err.message || '이벤트 저장에 실패했습니다.');
    }).finally(function() {
      if (btnSave) btnSave.disabled = !currentCanWrite;
    });
  }

  function voidEvent() {
    if (!currentCanWrite || !currentEventId) return;
    if (!confirm('이 이벤트를 취소 처리할까요? 이력은 삭제되지 않습니다.')) return;
    fetch(urlWithId(config.eventDeleteUrl, currentEventId), {
      method: 'POST',
      headers: { 'X-CSRFToken': config.csrfToken },
      credentials: 'same-origin'
    }).then(function(r) {
      if (!r.ok) throw new Error('void failed');
      if (eventModal) eventModal.hide();
      currentEventId = null;
      currentEvent = null;
      return loadEvents(false);
    }).catch(function() { showAlert('이벤트 취소 처리에 실패했습니다.'); });
  }

  function uploadFilesToEvent() {
    if (!currentCanWrite || !currentEventId || !window.uploadToEvent) return;
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
    loadWorkflowOptions()
      .then(function() { return loadEvents(); })
      .catch(function() {
        var empty = document.querySelector(config.timelineEmptySelector);
        if (empty) {
          empty.textContent = '업무 이벤트를 불러올 수 없습니다.';
          empty.classList.remove('d-none');
        }
      });
  }

  window.ProcessWorkboardUI = {
    init: init,
    loadEvents: loadEvents,
    openCreateModal: openCreateModal,
    openEditModal: openEditModal
  };
})(window);
