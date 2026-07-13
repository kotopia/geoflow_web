/**
 * GeoFlow Process Events UI - 공통 이벤트 타임라인 모듈
 * 
 * 계약/프로젝트/직원 등 모든 엔티티에서 이벤트 타임라인을 표시하는 공통 모듈
 * 
 * 의존성: 
 *   - upload-utils.js (업로드 기능)
 *   - bootstrap 5 (모달)
 * 
 * 사용법:
 *   1. HTML 컨테이너에 data-* 속성으로 설정 주입
 *   2. ProcessEventsUI.init(containerSelector) 호출
 */

(function(window) {
  'use strict';

  // ========================================
  // 설정 및 상태
  // ========================================
  
  var config = {
    scopeType: null,      // 'contract', 'project', 'employee' 등
    scopeId: null,        // 엔티티 ID
    csrfToken: null,
    
    // API URLs
    eventListUrl: null,
    eventCreateUrl: null,
    eventUpdateUrl: null,
    eventDeleteUrl: null,
    eventModalUiUrl: null,
    presignPutUrl: null,
    commitUrl: null,
    
    // DOM selectors
    containerSelector: '#eventModalMount',
    timelineListSelector: '#timelineList',
    timelineEmptySelector: '#timelineEmpty',
    addEventBtnSelector: '#btn-add-event'
  };

  // 모달 인스턴스
  var modalEl = null;
  var eventModal = null;
  var elAlert = null;

  // 모달 폼 필드들
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

  // 모달 버튼들
  var btnSave = null;
  var btnDel = null;
  var btnAttach = null;

  // 첨부파일 영역
  var attachSection = null;
  var attachList = null;

  // 상태 변수
  var currentEventId = null;
  var isEditMode = false;

  // ========================================
  // 설정 로드
  // ========================================
  
  /**
   * 컨테이너에서 data-* 속성으로 설정값 읽기
   * @param {string} selector - 컨테이너 셀렉터
   * @returns {boolean} 성공 여부
   */
  function loadConfigFromDom(selector) {
    var container = document.querySelector(selector);
    if (!container) {
      console.error('[ProcessEventsUI] Container not found:', selector);
      return false;
    }

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

    // 필수 값 검증
    if (!config.scopeType || !config.scopeId) {
      console.error('[ProcessEventsUI] Missing scopeType or scopeId');
      return false;
    }
    
    if (!config.csrfToken) {
      console.error('[ProcessEventsUI] Missing CSRF token');
      return false;
    }

    if (!config.eventListUrl || !config.eventCreateUrl || !config.eventUpdateUrl || 
        !config.eventDeleteUrl || !config.eventModalUiUrl) {
      console.error('[ProcessEventsUI] Missing required API URLs');
      return false;
    }

    if (!config.presignPutUrl || !config.commitUrl) {
      console.error('[ProcessEventsUI] Missing upload URLs');
      return false;
    }

    return true;
  }

  /**
   * URL 템플릿에 실제 ID를 삽입
   */
  function urlWithId(urlTemplate, id) {
    return urlTemplate.replace('00000000-0000-0000-0000-000000000000', id);
  }

  // ========================================
  // 모달 동적 로딩 및 DOM 바인딩
  // ========================================
  
  /**
   * 모달 UI HTML 동적 로드
   */
  function ensureModalLoaded() {
    if (document.getElementById('eventModal')) {
      return Promise.resolve();
    }

    var mount = document.querySelector(config.containerSelector);
    if (!mount) {
      return Promise.reject(new Error('Modal mount container not found'));
    }

    var url = config.eventModalUiUrl + '?scope_type=' + encodeURIComponent(config.scopeType) + 
              '&scope_id=' + encodeURIComponent(config.scopeId);
    
    return fetch(url, {
      method: 'GET',
      headers: { 'X-CSRFToken': config.csrfToken }
    })
    .then(function(r) {
      if (!r.ok) {
        return r.text().then(function(t) {
          throw new Error('Modal UI load failed: ' + t);
        });
      }
      return r.text();
    })
    .then(function(html) {
      mount.innerHTML = html;
      modalEl = document.getElementById('eventModal');
      if (!modalEl) {
        throw new Error('eventModal not found in loaded HTML');
      }
      eventModal = new bootstrap.Modal(modalEl);
      bindModalDomRefs();
      return true;
    });
  }

  /**
   * 모달 DOM 요소 참조 바인딩
   */
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

    // 폼 submit 기본 동작 방지 (중복 요청 방지)
    var modalForm = modalEl ? modalEl.querySelector('form') : null;
    if (modalForm) {
      modalForm.onsubmit = function(e) {
        e.preventDefault();
        return false;
      };
    }

    // 버튼 이벤트 바인딩 (onclick으로 중복 방지)
    if (btnSave) {
      btnSave.onclick = function(e) {
        e.preventDefault();
        saveEvent();
      };
    }
    if (btnDel) btnDel.onclick = function() { removeEvent(); };
    if (btnAttach) btnAttach.onclick = function() { uploadFilesToEvent(); };
  }

  // ========================================
  // 알림 메시지
  // ========================================
  
  function showAlert(msg) {
    if (!elAlert) return;
    elAlert.textContent = msg;
    elAlert.classList.remove('d-none');
  }

  function clearAlert() {
    if (!elAlert) return;
    elAlert.textContent = '';
    elAlert.classList.add('d-none');
  }

  // ========================================
  // 첨부파일 영역 제어
  // ========================================
  
  function setAttachMode(enabled) {
    if (!attachSection) return;
    if (enabled) {
      attachSection.classList.remove('d-none');
    } else {
      attachSection.classList.add('d-none');
    }
  }

  /**
   * 첨부파일 목록 렌더링
   */
  function renderAttachments(attachments) {
    if (!attachList) return;
    attachList.innerHTML = '';

    if (!attachments || !attachments.length) {
      var empty = document.createElement('div');
      empty.className = 'text-muted small';
      empty.textContent = '첨부파일이 없습니다.';
      attachList.appendChild(empty);
      return;
    }

    attachments.forEach(function(a) {
      var row = document.createElement('div');
      row.className = 'd-flex justify-content-between align-items-center mb-2 p-2 border rounded';

      var left = document.createElement('div');
      left.className = 'text-truncate';
      left.textContent = a.original_name || a.id;

      var right = document.createElement('div');
      right.className = 'd-flex gap-2';

      // 열기 버튼
      var btnOpen = document.createElement('button');
      btnOpen.type = 'button';
      btnOpen.className = 'btn btn-sm btn-outline-secondary';
      btnOpen.textContent = '열기';
      btnOpen.addEventListener('click', function() {
        window.getPresignedGetUrl(a.id, config.csrfToken, 'inline')
          .then(function(url) { window.open(url, '_blank'); })
          .catch(function(e) { alert('다운로드 URL 실패: ' + e.message); });
      });

      // 삭제 버튼
      var btnRm = document.createElement('button');
      btnRm.type = 'button';
      btnRm.className = 'btn btn-sm btn-outline-danger';
      btnRm.textContent = '삭제';
      btnRm.addEventListener('click', function() {
        if (!confirm('첨부파일을 삭제할까요?')) return;
        window.deleteAttachment(a.id, config.csrfToken)
          .then(function() { return loadEvents(true); })
          .catch(function(e) { alert('삭제 실패: ' + e.message); });
      });

      right.appendChild(btnOpen);
      right.appendChild(btnRm);
      row.appendChild(left);
      row.appendChild(right);
      attachList.appendChild(row);
    });
  }

  // ========================================
  // 모달 초기화 및 데이터 로드
  // ========================================
  
  /**
   * 모달 초기화 (생성 모드)
   */
  function resetModal() {
    clearAlert();
    isEditMode = false;
    currentEventId = null;

    if (fId) fId.value = '';
    if (fStage) fStage.value = '';
    if (fType) fType.value = '';
    if (fStatus) fStatus.value = '';
    if (fTitle) fTitle.value = '';
    if (fOcc) fOcc.value = '';
    if (fMemo) fMemo.value = '';
    if (fScopeType) fScopeType.value = config.scopeType;
    if (fScopeId) fScopeId.value = config.scopeId;
    if (fCreatedAt) fCreatedAt.value = '';
    if (fCreatedBy) fCreatedBy.value = '';

    if (btnDel) btnDel.classList.add('d-none');
    setAttachMode(false);
    if (attachList) attachList.innerHTML = '';

    var modalLabel = document.getElementById('eventModalLabel');
    if (modalLabel) modalLabel.textContent = '새 이벤트 추가';
  }

  /**
   * 모달에 이벤트 데이터 로드 (수정 모드)
   */
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
    if (fCreatedBy) fCreatedBy.value = ev.created_by_name || '';

    if (btnDel) btnDel.classList.remove('d-none');
    setAttachMode(true);
    renderAttachments(ev.attachments || []);

    var modalLabel = document.getElementById('eventModalLabel');
    if (modalLabel) modalLabel.textContent = '이벤트 수정';
  }

  /**
   * 생성 모달 열기
   */
  function openCreateModal() {
    ensureModalLoaded()
      .then(function() {
        resetModal();
        if (eventModal) eventModal.show();
      })
      .catch(function(e) {
        alert('이벤트 팝업 로드 실패: ' + e.message);
      });
  }

  /**
   * 수정 모달 열기
   */
  function openEditModal(ev) {
    ensureModalLoaded()
      .then(function() {
        loadEventToModal(ev);
        if (eventModal) eventModal.show();
      })
      .catch(function(e) {
        alert('이벤트 팝업 로드 실패: ' + e.message);
      });
  }

  // ========================================
  // 타임라인 렌더링
  // ========================================
  
  /**
   * 타임라인 렌더링 (AdminKit Pro Activity 스타일)
   */
  function renderTimeline(events) {
    var list = document.querySelector(config.timelineListSelector);
    var empty = document.querySelector(config.timelineEmptySelector);
    if (!list) return;

    var arr = events || [];

    if (!arr.length) {
      list.innerHTML = '';
      if (empty) empty.classList.remove('d-none');
      return;
    }
    if (empty) empty.classList.add('d-none');

    // 정렬: occurred_at 우선 → created_at fallback, 내림차순 (최신이 위)
    arr = arr.slice().sort(function(a, b) {
      var aDate = a.occurred_at || a.created_at || '';
      var bDate = b.occurred_at || b.created_at || '';
      if (!aDate && !bDate) return 0;
      if (!aDate) return 1;  // aDate 없으면 아래로
      if (!bDate) return -1; // bDate 없으면 아래로
      return bDate > aDate ? 1 : (bDate < aDate ? -1 : 0); // 내림차순
    });

    var ul = document.createElement('ul');
    ul.className = 'timeline mt-2 mb-0';

    arr.forEach(function(ev) {
      var li = document.createElement('li');
      // B. event 간 간격 넓히기
      li.className = 'timeline-item mb-4';
      li.style.cursor = 'pointer';

      var title = ev.title || '[' + (ev.event_type || '이벤트') + ']';
      
      // C. 날짜 표시: occurred_at 우선, YYYY-MM-DD 고정
      var dateText = '';
      var baseDate = ev.occurred_at || ev.created_at;
      if (baseDate) {
        // YYYY-MM-DD 형식으로 고정
        dateText = String(baseDate).slice(0, 10);
      }

      // 카드 컨테이너
      var html = '<div class="timeline-card-content">';
      
      // 2) 상단 헤더: 제목 + 날짜 (flex wrap으로 반응형)
      html += '<div class="d-flex align-items-start justify-content-between gap-2 flex-wrap mb-1">';
      html += '<strong class="flex-grow-1 min-w-0">' + title + '</strong>';
      if (dateText) {
        html += '<span class="text-muted small text-nowrap">' + dateText + '</span>';
      }
      html += '</div>';
      
      // 메모가 있을 때만 <p> 렌더링
      if (ev.memo) {
        var memoText = ev.memo.length > 80 ? ev.memo.slice(0, 80) + '...' : ev.memo;
        html += '<p class="mb-1">' + memoText + '</p>';
      }

      // 1) 첨부파일 표시 (CSS 기반 ellipsis + title 속성)
      if (ev.attachments && ev.attachments.length > 0) {
        html += '<div class="mt-1">';
        ev.attachments.forEach(function(att) {
          var fileName = att.original_name || att.id || '파일';
          var extension = fileName.split('.').pop().toLowerCase();
          var iconClass = 'fa-file';

          if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp'].indexOf(extension) >= 0) {
            iconClass = 'fa-file-image';
          } else if (extension === 'pdf') {
            iconClass = 'fa-file-pdf';
          } else if (['doc', 'docx'].indexOf(extension) >= 0) {
            iconClass = 'fa-file-word';
          } else if (['xls', 'xlsx'].indexOf(extension) >= 0) {
            iconClass = 'fa-file-excel';
          } else if (['zip', 'rar', '7z'].indexOf(extension) >= 0) {
            iconClass = 'fa-file-archive';
          }

          // 1) title 속성 추가 + CSS ellipsis 클래스
          html += '<button type="button" class="btn btn-sm btn-link text-start p-0 me-3 timeline-attachment-link d-inline-flex align-items-center" data-att-id="' + att.id + '" style="max-width: 100%;">';
          html += '<i class="fa ' + iconClass + ' me-1 flex-shrink-0"></i>';
          html += '<span class="timeline-filename" title="' + fileName + '">' + fileName + '</span>';
          html += '</button>';
        });
        html += '</div>';
      }
      
      html += '</div>'; // timeline-card-content 끝

      li.innerHTML = html;

      // 클릭 시 수정 모달 (첨부파일 링크는 제외)
      li.addEventListener('click', function(e) {
        if (e.target.closest('.timeline-attachment-link')) {
          return;
        }
        e.preventDefault();
        openEditModal(ev);
      });

      ul.appendChild(li);
    });

    list.innerHTML = '';
    list.appendChild(ul);
  }

  /**
   * 타임라인 첨부파일 클릭 핸들러 (이벤트 위임)
   */
  function bindTimelineAttachmentListeners() {
    var list = document.querySelector(config.timelineListSelector);
    if (!list) return;

    // 기존 리스너 제거
    list.removeEventListener('click', handleTimelineAttachmentClick);
    // 새 리스너 등록
    list.addEventListener('click', handleTimelineAttachmentClick);
  }

  function handleTimelineAttachmentClick(e) {
    var btn = e.target.closest('.timeline-attachment-link');
    if (!btn) return;

    e.stopPropagation();
    e.preventDefault();

    var attId = btn.getAttribute('data-att-id');
    if (!attId) {
      console.error('첨부파일 ID를 찾을 수 없습니다.');
      return;
    }

    if (typeof window.getPresignedGetUrl !== 'function') {
      alert('파일 미리보기 기능이 로드되지 않았습니다.');
      return;
    }

    window.getPresignedGetUrl(attId, config.csrfToken, 'inline')
      .then(function(url) {
        if (!url) throw new Error('URL을 받지 못했습니다.');
        window.open(url, '_blank', 'noopener');
      })
      .catch(function(err) {
        alert('파일 미리보기 실패: ' + err.message);
      });
  }

  // ========================================
  // API 호출
  // ========================================
  
  /**
   * 이벤트 목록 로드
   */
  function loadEvents(keepModalOpen) {
    var url = config.eventListUrl + '?scope_type=' + encodeURIComponent(config.scopeType) + 
              '&scope_id=' + encodeURIComponent(config.scopeId);
    
    return fetch(url, {
      method: 'GET',
      headers: { 'X-CSRFToken': config.csrfToken }
    })
    .then(function(r) {
      if (!r.ok) throw new Error('이벤트 목록 로드 실패: ' + r.status);
      return r.json();
    })
    .then(function(data) {
      if (data.error) throw new Error(data.error);
      var events = data.events || data.results || [];

      renderTimeline(events);
      bindTimelineAttachmentListeners();

      // 모달이 열려 있으면 첨부 목록도 갱신
      if (keepModalOpen && isEditMode && currentEventId) {
        var ev = events.find(function(e) { return e.id === currentEventId; });
        if (ev) {
          renderAttachments(ev.attachments || []);
        }
      }
    });
  }

  /**
   * 이벤트 저장 (생성 또는 수정)
   */
  function saveEvent() {
    clearAlert();

    // 더블클릭 방지: 버튼 비활성화
    if (btnSave) {
      if (btnSave.disabled) return; // 이미 처리 중이면 무시
      btnSave.disabled = true;
      btnSave.textContent = '저장 중...';
    }

    var stage = fStage ? fStage.value : '';
    var eventType = fType ? fType.value : '';
    var status = fStatus ? fStatus.value : '';
    var title = fTitle ? fTitle.value : '';
    var occurredAt = fOcc ? fOcc.value : '';
    var memo = fMemo ? fMemo.value : '';

    if (!eventType) {
      showAlert('이벤트 유형을 선택하세요.');
      if (btnSave) {
        btnSave.disabled = false;
        btnSave.textContent = '저장';
      }
      return;
    }

    var payload = {
      scope_type: config.scopeType,
      scope_id: config.scopeId,
      stage: stage,
      event_type: eventType,
      status: status,
      title: title,
      occurred_at: occurredAt || null,
      memo: memo
    };

    // create vs update 분기 강화 (fId hidden 값 또는 currentEventId 우선)
    var eventId = (fId && fId.value) ? fId.value : currentEventId;
    var isUpdate = !!(eventId && eventId.trim());
    
    var url = isUpdate ? urlWithId(config.eventUpdateUrl, eventId) : config.eventCreateUrl;
    // 중요: UPDATE도 POST로 변경 (서버 엔드포인트 통일)
    var method = 'POST';

    fetch(url, {
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': config.csrfToken
      },
      body: JSON.stringify(payload)
    })
    .then(function(r) {
      if (!r.ok) {
        return r.text().then(function(text) {
          console.error('[saveEvent] HTTP ' + r.status + ':', text);
          throw new Error('이벤트 저장 실패 (HTTP ' + r.status + ')');
        });
      }
      return r.json();
    })
    .then(function(data) {
      if (data.error) throw new Error(data.error);

      // 생성 모드였다면 수정 모드로 전환 (중복 생성 방지)
      if (!isUpdate && data.event && data.event.id) {
        currentEventId = data.event.id;
        isEditMode = true;
        if (fId) fId.value = currentEventId; // hidden에 즉시 세팅
        setAttachMode(true);
        if (btnDel) btnDel.classList.remove('d-none');
        var modalLabel = document.getElementById('eventModalLabel');
        if (modalLabel) modalLabel.textContent = '이벤트 수정';
      }

      // 성공 피드백
      showAlert('저장되었습니다.');
      
      return loadEvents(true);
    })
    .then(function() {
      // 버튼 복원
      if (btnSave) {
        btnSave.disabled = false;
        btnSave.textContent = '저장';
      }
    })
    .catch(function(e) {
      console.error('[saveEvent] Error:', e);
      showAlert('저장 실패: ' + e.message);
      // 버튼 복원
      if (btnSave) {
        btnSave.disabled = false;
        btnSave.textContent = '저장';
      }
    });
  }

  /**
   * 이벤트 삭제
   */
  function removeEvent() {
    clearAlert();
    if (!currentEventId) {
      showAlert('삭제할 이벤트가 없습니다.');
      return;
    }

    if (!confirm('정말 이 이벤트를 삭제하시겠습니까?')) return;

    // 중요: DELETE → POST로 변경 (서버 엔드포인트 통일)
    fetch(urlWithId(config.eventDeleteUrl, currentEventId), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': config.csrfToken
      },
      body: JSON.stringify({}) // 빈 객체
    })
    .then(function(r) {
      if (!r.ok) {
        return r.text().then(function(text) {
          console.error('[removeEvent] HTTP ' + r.status + ':', text);
          throw new Error('삭제 실패 (HTTP ' + r.status + ')');
        });
      }
      return r.json();
    })
    .then(function(data) {
      if (data.error) throw new Error(data.error);
      if (eventModal) eventModal.hide();
      showAlert('삭제되었습니다.');
      return loadEvents();
    })
    .catch(function(e) {
      console.error('[removeEvent] Error:', e);
      showAlert('삭제 실패: ' + e.message);
    });
  }

  /**
   * 이벤트 첨부파일 업로드
   */
  function uploadFilesToEvent() {
    clearAlert();
    if (!currentEventId) {
      showAlert('먼저 이벤트를 저장하세요.');
      return;
    }
    if (!window.uploadToEvent) {
      showAlert('업로드 모듈이 로드되지 않았습니다.');
      return;
    }

    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.multiple = true;
    fileInput.onchange = function() {
      var files = Array.prototype.slice.call(fileInput.files || []);
      if (!files.length) return;

      var p = Promise.resolve();
      files.forEach(function(file) {
        p = p.then(function() {
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

      p.then(function() {
        return loadEvents(true);
      }).catch(function(e) {
        showAlert('업로드 실패: ' + e.message);
      });
    };
    fileInput.click();
  }

  // ========================================
  // 초기화
  // ========================================
  
  /**
   * 공통 초기화 함수
   * @param {string} containerSelector - 설정 컨테이너 셀렉터 (기본: '#eventModalMount')
   */
  function init(containerSelector) {
    config.containerSelector = containerSelector || config.containerSelector;

    // 설정 로드
    if (!loadConfigFromDom(config.containerSelector)) {
      console.error('[ProcessEventsUI] 설정 로드 실패');
      return;
    }

    // "이벤트 추가" 버튼 바인딩
    var btnOpen = document.querySelector(config.addEventBtnSelector);
    if (!btnOpen) {
      console.error('[ProcessEventsUI] 이벤트 추가 버튼을 찾을 수 없습니다:', config.addEventBtnSelector);
      return;
    }

    btnOpen.addEventListener('click', openCreateModal);

    // 초기 타임라인 로드
    loadEvents();
  }

  // ========================================
  // Public API
  // ========================================
  
  window.ProcessEventsUI = {
    init: init,
    loadEvents: loadEvents,
    openCreateModal: openCreateModal,
    openEditModal: openEditModal
  };

})(window);
