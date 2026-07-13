/**
 * GeoFlow 첨부파일 업로드 공통 유틸리티
 * 
 * 이미지 파일 업로드, 썸네일 생성, presigned URL 처리 등
 */

/**
 * 파일이 이미지인지 확인
 */
function isImageFile(file) {
  if (!file || !file.type) return false;
  return file.type.startsWith('image/');
}

/**
 * 이미지 썸네일 생성 (Canvas 사용)
 * @param {File} file - 원본 이미지 파일
 * @param {number} maxWidth - 최대 너비
 * @param {number} maxHeight - 최대 높이
 * @returns {Promise<Blob>} 썸네일 Blob
 */
function createImageThumbnail(file, maxWidth, maxHeight) {
  return new Promise(function(resolve, reject) {
    var reader = new FileReader();
    
    reader.onload = function(e) {
      var img = new Image();
      
      img.onload = function() {
        var canvas = document.createElement('canvas');
        var ctx = canvas.getContext('2d');
        
        // 비율 유지하며 크기 조정
        var ratio = Math.min(maxWidth / img.width, maxHeight / img.height);
        var newWidth = img.width * ratio;
        var newHeight = img.height * ratio;
        
        canvas.width = newWidth;
        canvas.height = newHeight;
        
        ctx.drawImage(img, 0, 0, newWidth, newHeight);
        
        canvas.toBlob(function(blob) {
          if (blob) {
            resolve(blob);
          } else {
            reject(new Error('Failed to create thumbnail'));
          }
        }, 'image/jpeg', 0.8);
      };
      
      img.onerror = function() {
        reject(new Error('Failed to load image'));
      };
      
      img.src = e.target.result;
    };
    
    reader.onerror = function() {
      reject(new Error('Failed to read file'));
    };
    
    reader.readAsDataURL(file);
  });
}

/**
 * 이미지 파일 업로드 (원본 + 썸네일)
 * @param {Object} params
 * @param {File} params.file - 업로드할 파일
 * @param {string} params.entityType - "employee", "contract", "orgunit" 등
 * @param {string} params.entityId - UUID
 * @param {string} params.purpose - "photo", "logo" 등
 * @param {string} params.csrfToken - CSRF 토큰
 * @param {number} params.thumbWidth - 썸네일 너비 (기본 300)
 * @param {number} params.thumbHeight - 썸네일 높이 (기본 300)
 * @returns {Promise<Object>} 업로드 결과 { originalId, thumbnailId }
 */
function uploadImageWithThumbnail(params) {
  var file = params.file;
  var entityType = params.entityType;
  var entityId = params.entityId;
  var purpose = params.purpose;
  var csrfToken = params.csrfToken;
  var thumbWidth = params.thumbWidth || 300;
  var thumbHeight = params.thumbHeight || 300;
  
  if (!isImageFile(file)) {
    return Promise.reject(new Error('이미지 파일이 아닙니다.'));
  }
  
  var filename = file.name;
  var originalId = null;
  
  // 1. 원본 업로드
  return uploadSingleFile({
    file: file,
    entityType: entityType,
    entityId: entityId,
    purpose: purpose,
    filename: filename,
    csrfToken: csrfToken
  })
  .then(function(result) {
    originalId = result.attachment_id;
    
    // 2. 썸네일 생성
    return createImageThumbnail(file, thumbWidth, thumbHeight);
  })
  .then(function(thumbBlob) {
    // 3. 썸네일 업로드
    var thumbFile = new File([thumbBlob], 'thumb_' + filename, { type: 'image/jpeg' });
    
    return uploadSingleFile({
      file: thumbFile,
      entityType: entityType,
      entityId: entityId,
      purpose: purpose + '_thumb',
      filename: 'thumb_' + filename,
      csrfToken: csrfToken,
      parentId: originalId
    });
  })
  .then(function(thumbResult) {
    return {
      originalId: originalId,
      thumbnailId: thumbResult.attachment_id
    };
  });
}

/**
 * 단일 파일 업로드 (Presigned PUT 방식)
 * @param {Object} params
 * @param {File} params.file - 업로드할 파일
 * @param {string} params.entityType
 * @param {string} params.entityId
 * @param {string} params.purpose
 * @param {string} params.filename
 * @param {string} params.csrfToken
 * @param {string} params.parentId - 부모 attachment ID (선택)
 * @param {string} params.eventId - 이벤트 ID (entity_type="event"일 때 필수)
 * @param {string} params.presignPutUrl - Presign PUT URL (선택, 기본값: /api/uploads/presign-put/)
 * @param {string} params.commitUrl - Commit URL (선택, 기본값: /api/uploads/commit/)
 * @returns {Promise<Object>} { attachment_id, object_key, event_link_id }
 */
function uploadSingleFile(params) {
  var file = params.file;
  var entityType = params.entityType;
  var entityId = params.entityId;
  var purpose = params.purpose;
  var filename = params.filename;
  var csrfToken = params.csrfToken;
  var parentId = params.parentId;
  var eventId = params.eventId;  // event 타입일 때 사용
  var presignPutUrl = params.presignPutUrl || '/api/uploads/presign-put/';
  var commitUrl = params.commitUrl || '/api/uploads/commit/';
  
  // URL 방어 코드
  if (!presignPutUrl || !commitUrl) {
    return Promise.reject(new Error('missing upload endpoints: presignPutUrl or commitUrl is undefined'));
  }
  if (presignPutUrl === 'undefined' || commitUrl === 'undefined') {
    return Promise.reject(new Error('upload endpoint is literal "undefined" string - check template URL generation'));
  }
  
  var objectKey = null;
  var mimeType = file.type || '';
  var sizeBytes = file.size || 0;
  
  // 1. Presigned PUT URL 요청
  var presignPayload = {
    entity_type: entityType,
    entity_id: entityId,
    purpose: purpose,
    filename: filename,
    mime_type: mimeType,
    size_bytes: sizeBytes,
    parent_id: parentId
  };
  
  // event 타입일 때 event_id 추가
  if (entityType === 'event' && eventId) {
    presignPayload.event_id = eventId;
  }
  
  return fetch(presignPutUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken
    },
    body: JSON.stringify(presignPayload)
  })
  .then(function(r) {
    if (!r.ok) {
      console.error('[UPLOAD] Presign-PUT failed:', r.status, r.statusText);
      return r.text().then(function(text) {
        console.error('[UPLOAD] Presign-PUT response:', text);
        throw new Error('Presigned PUT URL 요청 실패: ' + r.status);
      });
    }
    return r.json();
  })
  .then(function(data) {
    if (data.error) throw new Error(data.error);
    objectKey = data.object_key;
    
    // 2. S3에 PUT
    return fetch(data.presigned_url, {
      method: "PUT",
      body: file,
      headers: data.headers
    });
  })
  .then(function(r) {
    if (!r.ok) {
      console.error('[UPLOAD] S3 PUT failed:', r.status, r.statusText);
      return r.text().then(function(text) {
        console.error('[UPLOAD] S3 PUT response:', text);
        throw new Error('S3 업로드 실패: ' + r.status);
      });
    }
    
    // 3. Commit
    var commitPayload = {
      object_key: objectKey,
      entity_type: entityType,
      entity_id: entityId,
      purpose: purpose,
      original_name: filename,
      mime_type: mimeType,
      size_bytes: sizeBytes,
      parent_attachment_id: parentId
    };
    
    // event 타입일 때 event_id 추가 (자동 링크 생성용)
    if (entityType === 'event' && eventId) {
      commitPayload.event_id = eventId;
    }
    
    return fetch(commitUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken
      },
      body: JSON.stringify(commitPayload)
    });
  })
  .then(function(r) {
    if (!r.ok) {
      console.error('[UPLOAD] Commit failed:', r.status, r.statusText);
      return r.text().then(function(text) {
        console.error('[UPLOAD] Commit response:', text);
        throw new Error('Commit 실패: ' + r.status);
      });
    }
    return r.json();
  })
  .then(function(data) {
    if (data.error) throw new Error(data.error);
    return {
      attachment_id: data.attachment_id,
      object_key: data.object_key,
      event_link_id: data.event_link_id  // event 타입일 때만 존재
    };
  });
}

/**
 * Presigned GET URL 가져오기
 * @param {string} attachmentId - Attachment UUID
 * @param {string} csrfToken - CSRF 토큰
 * @param {string} mode - "inline" | "download" (기본 "inline")
 * @returns {Promise<string>} Presigned GET URL
 */
function getPresignedGetUrl(attachmentId, csrfToken, mode) {
  mode = mode || 'inline';
  
  return fetch("/api/uploads/presign-get/" + attachmentId + "/?mode=" + mode, {
    method: "GET",
    headers: {
      "X-CSRFToken": csrfToken
    }
  })
  .then(function(r) {
    if (!r.ok) throw new Error('Presigned GET URL 요청 실패');
    return r.json();
  })
  .then(function(data) {
    if (data.error) throw new Error(data.error);
    return data.presigned_url;
  });
}

/**
 * 첨부파일 삭제 (소프트 삭제)
 * @param {string} attachmentId - Attachment UUID
 * @param {string} csrfToken - CSRF 토큰
 * @returns {Promise<Object>} 삭제 결과
 */
function deleteAttachment(attachmentId, csrfToken) {
  return fetch("/api/uploads/delete/" + attachmentId + "/", {
    method: "DELETE",
    headers: {
      "X-CSRFToken": csrfToken
    }
  })
  .then(function(r) {
    if (!r.ok) throw new Error('삭제 요청 실패');
    return r.json();
  })
  .then(function(data) {
    if (data.error) throw new Error(data.error);
    return data;
  });
}

/**
 * 이벤트에 파일 업로드 (이벤트 기반 업로드 헬퍼)
 * @param {Object} params
 * @param {File} params.file - 업로드할 파일
 * @param {string} params.eventId - 이벤트 UUID
 * @param {string} params.csrfToken - CSRF 토큰
 * @param {string} params.purpose - 목적 (기본값: "doc")
 * @param {string} params.presignPutUrl - Presign PUT URL (선택)
 * @param {string} params.commitUrl - Commit URL (선택)
 * @returns {Promise<Object>} 업로드 결과
 */
function uploadToEvent(params) {
  var file = params.file;
  var eventId = params.eventId;
  var csrfToken = params.csrfToken;
  var purpose = params.purpose || 'doc';
  var presignPutUrl = params.presignPutUrl;
  var commitUrl = params.commitUrl;
  
  if (!file || !eventId || !csrfToken) {
    return Promise.reject(new Error('file, eventId, csrfToken are required'));
  }
  
  if (!presignPutUrl || !commitUrl) {
    return Promise.reject(new Error('missing upload endpoints: presignPutUrl or commitUrl is undefined'));
  }
  
  return uploadSingleFile({
    file: file,
    entityType: "event",
    entityId: eventId,  // event의 scope_id를 entity_id로 사용
    purpose: purpose,
    filename: file.name,
    csrfToken: csrfToken,
    eventId: eventId,  // commit 시 자동 링크용
    presignPutUrl: presignPutUrl,
    commitUrl: commitUrl
  });
}

// ========================================
// 첨부파일 버튼 공통 바인딩 (이벤트 위임)
// ========================================

/**
 * 첨부파일 미리보기/다운로드/삭제 버튼을 공통으로 처리
 * @param {Object} options
 * @param {HTMLElement|Document} options.root - 이벤트 위임 루트 (기본: document)
 * @param {string} options.csrfToken - CSRF 토큰
 */
function initAttachmentActions(options) {
  var root = options.root || document;
  var csrfToken = options.csrfToken;

  if (!csrfToken) {
    // CSRF 토큰 fallback: DOM에서 찾기
    var csrfInput = document.querySelector('input[name=csrfmiddlewaretoken]');
    csrfToken = csrfInput ? csrfInput.value : '';
  }

  if (!csrfToken) {
    console.error('[initAttachmentActions] CSRF token not found');
    return;
  }

  // 이벤트 위임: 미리보기 버튼
  root.addEventListener('click', function(e) {
    var btn = e.target.closest('.btn-preview-att');
    if (!btn) return;

    e.preventDefault();
    var attId = btn.getAttribute('data-att-id');
    var filename = btn.getAttribute('data-filename') || '';
    if (!attId) return;

    // Excel 파일은 전용 미리보기 페이지
    var ext = filename.toLowerCase().split('.').pop();
    if (ext === 'xlsx' || ext === 'xls') {
      window.open('/uploads/excel-preview/' + attId + '/', '_blank', 'noopener');
      return;
    }

    // 일반 파일은 presigned URL로 미리보기
    getPresignedGetUrl(attId, csrfToken, 'inline')
      .then(function(url) { window.open(url, '_blank', 'noopener'); })
      .catch(function(err) { alert('미리보기 실패: ' + err.message); });
  });

  // 이벤트 위임: 다운로드 버튼
  root.addEventListener('click', function(e) {
    var btn = e.target.closest('.btn-download-att');
    if (!btn) return;

    e.preventDefault();
    var attId = btn.getAttribute('data-att-id');
    if (!attId) return;

    getPresignedGetUrl(attId, csrfToken, 'download')
      .then(function(url) { window.open(url, '_blank', 'noopener'); })
      .catch(function(err) { alert('다운로드 실패: ' + err.message); });
  });

  // 이벤트 위임: 삭제 버튼
  root.addEventListener('click', function(e) {
    var btn = e.target.closest('.btn-delete-att');
    if (!btn) return;

    e.preventDefault();
    var attId = btn.getAttribute('data-att-id');
    if (!attId) return;

    if (!confirm('정말 이 첨부파일을 삭제하시겠습니까?')) return;

    deleteAttachment(attId, csrfToken)
      .then(function() {
        // DOM에서 제거 (data-att-item 속성으로 찾기)
        var item = document.querySelector('[data-att-item="' + attId + '"]');
        if (item) item.remove();
        alert('삭제되었습니다.');
      })
      .catch(function(err) { alert('삭제 실패: ' + err.message); });
  });
}

// ========================================
// 전역 스코프에 노출 (ReferenceError 방지)
// ========================================
window.isImageFile = isImageFile;
window.createImageThumbnail = createImageThumbnail;
window.uploadImageWithThumbnail = uploadImageWithThumbnail;
window.uploadSingleFile = uploadSingleFile;
window.getPresignedGetUrl = getPresignedGetUrl;
window.deleteAttachment = deleteAttachment;
window.uploadToEvent = uploadToEvent;
window.initAttachmentActions = initAttachmentActions;
