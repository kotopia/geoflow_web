(function(window, document) {
  'use strict';

  var labels = {draft:'작성중', open:'진행중', done:'완료', void:'취소'};

  function refreshStatusUi(modal) {
    if (!modal || modal.id !== 'eventModal') return;
    var status = modal.querySelector('#event-status');
    var display = modal.querySelector('#event-status-display');
    var complete = modal.querySelector('#btn-complete-event-modal');
    var save = modal.querySelector('#btn-save-event');
    var eventId = modal.querySelector('#event-id');
    var value = status ? status.value : '';
    var isExisting = !!(eventId && eventId.value);

    if (display) {
      display.textContent = isExisting ? (labels[value] || value || '자동 관리') : '저장 시 자동 결정';
    }
    if (complete) {
      var canWrite = !!(save && !save.classList.contains('d-none') && !save.disabled);
      var completable = isExisting && value !== 'done' && value !== 'void';
      complete.classList.toggle('d-none', !(canWrite && completable));
      complete.disabled = !(canWrite && completable);
    }
  }

  document.addEventListener('shown.bs.modal', function(event) {
    if (event.target && event.target.id === 'eventModal') {
      window.setTimeout(function() { refreshStatusUi(event.target); }, 0);
    }
  });

  document.addEventListener('click', function(event) {
    var button = event.target.closest('#btn-complete-event-modal');
    if (!button) return;
    event.preventDefault();
    var modal = button.closest('#eventModal');
    if (!modal) return;
    var status = modal.querySelector('#event-status');
    var save = modal.querySelector('#btn-save-event');
    if (!status || !save) return;
    status.value = 'done';
    refreshStatusUi(modal);
    save.click();
  });

  // Existing workboard code refreshes the hidden select after AJAX reloads.
  // A short observer keeps the read-only label synchronized without making
  // status a user-editable field again.
  var observer = new MutationObserver(function() {
    var modal = document.getElementById('eventModal');
    if (modal && modal.classList.contains('show')) refreshStatusUi(modal);
  });
  observer.observe(document.documentElement, {childList:true, subtree:true});
})(window, document);
