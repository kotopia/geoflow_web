/** GeoFlow private attachment upload helpers. */
(function (window) {
  "use strict";

  function isImageFile(file) {
    return !!(file && ["image/jpeg", "image/png", "image/webp"].indexOf(file.type) >= 0);
  }

  function createImageThumbnail(file, maxWidth, maxHeight) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("Failed to read image")); };
      reader.onload = function (event) {
        var image = new Image();
        image.onerror = function () { reject(new Error("Failed to load image")); };
        image.onload = function () {
          var ratio = Math.min(maxWidth / image.width, maxHeight / image.height, 1);
          var canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(image.width * ratio));
          canvas.height = Math.max(1, Math.round(image.height * ratio));
          var context = canvas.getContext("2d");
          if (!context) { reject(new Error("Canvas unavailable")); return; }
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          canvas.toBlob(function (blob) {
            if (blob) resolve(blob); else reject(new Error("Failed to create thumbnail"));
          }, "image/jpeg", 0.8);
        };
        image.src = event.target.result;
      };
      reader.readAsDataURL(file);
    });
  }

  function requestJson(url, options) {
    options = options || {};
    options.credentials = options.credentials || "same-origin";
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || data.error) throw new Error(data.error || ("HTTP " + response.status));
        return data;
      });
    });
  }

  function uploadSingleFile(params) {
    var file = params.file;
    var entityType = params.entityType;
    var entityId = params.entityId;
    var purpose = params.purpose;
    var filename = params.filename || (file && file.name) || "";
    var csrfToken = params.csrfToken;
    var parentId = params.parentId || null;
    var eventId = params.eventId || null;
    var documentTitle = params.documentTitle || null;
    var presignPutUrl = params.presignPutUrl || "/api/uploads/presign-put/";
    var commitUrl = params.commitUrl || "/api/uploads/commit/";
    if (!file || !entityType || !entityId || !purpose || !filename || !csrfToken) {
      return Promise.reject(new Error("Missing upload parameters"));
    }
    var payload = {
      entity_type: entityType,
      entity_id: entityId,
      purpose: purpose,
      filename: filename,
      mime_type: file.type || "",
      size_bytes: file.size,
      parent_attachment_id: parentId
    };
    if (entityType === "event") payload.event_id = eventId;
    var objectKey = null;
    return requestJson(presignPutUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken},
      body: JSON.stringify(payload)
    }).then(function (data) {
      objectKey = data.object_key;
      return fetch(data.presigned_url, {method: "PUT", body: file, headers: data.headers || {}});
    }).then(function (response) {
      if (!response.ok) throw new Error("S3 upload failed");
      var commitPayload = {
        object_key: objectKey,
        entity_type: entityType,
        entity_id: entityId,
        purpose: purpose,
        original_name: filename,
        mime_type: file.type || "",
        size_bytes: file.size,
        parent_attachment_id: parentId
      };
      if (entityType === "event") commitPayload.event_id = eventId;
      if (documentTitle) commitPayload.document_title = documentTitle;
      return requestJson(commitUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken},
        body: JSON.stringify(commitPayload)
      });
    });
  }

  function uploadImageWithThumbnail(params) {
    if (!isImageFile(params.file)) return Promise.reject(new Error("지원하지 않는 이미지 형식입니다."));
    var originalId = null;
    return uploadSingleFile(params).then(function (result) {
      originalId = result.attachment_id;
      return createImageThumbnail(params.file, params.thumbWidth || 300, params.thumbHeight || 300);
    }).then(function (blob) {
      return uploadSingleFile({
        file: new File([blob], "thumb.jpg", {type: "image/jpeg"}),
        entityType: params.entityType,
        entityId: params.entityId,
        purpose: params.purpose + "_thumb",
        filename: "thumb.jpg",
        csrfToken: params.csrfToken,
        parentId: originalId,
        presignPutUrl: params.presignPutUrl,
        commitUrl: params.commitUrl
      });
    }).then(function (thumbResult) {
      return {originalId: originalId, thumbnailId: thumbResult.attachment_id};
    });
  }

  function getPresignedGetUrl(attachmentId, csrfToken, mode) {
    var safeMode = mode === "download" ? "download" : "inline";
    return requestJson(
      "/api/uploads/presign-get/" + encodeURIComponent(attachmentId) + "/?mode=" + safeMode,
      {method: "GET", headers: {"X-CSRFToken": csrfToken}}
    ).then(function (data) { return data.presigned_url; });
  }

  function deleteAttachment(attachmentId, csrfToken) {
    return requestJson(
      "/api/uploads/delete/" + encodeURIComponent(attachmentId) + "/",
      {method: "DELETE", headers: {"X-CSRFToken": csrfToken}}
    );
  }

  function uploadToEvent(params) {
    if (!params.file || !params.eventId || !params.csrfToken) {
      return Promise.reject(new Error("Missing event upload parameters"));
    }
    return uploadSingleFile({
      file: params.file,
      entityType: "event",
      entityId: params.eventId,
      eventId: params.eventId,
      purpose: params.purpose || "doc",
      filename: params.file.name,
      csrfToken: params.csrfToken,
      presignPutUrl: params.presignPutUrl,
      commitUrl: params.commitUrl
    });
  }

  function initAttachmentActions(options) {
    var root = options.root || document;
    var csrfToken = options.csrfToken || "";
    root.addEventListener("click", function (event) {
      var preview = event.target.closest(".btn-preview-att");
      var download = event.target.closest(".btn-download-att");
      var remove = event.target.closest(".btn-delete-att");
      var button = preview || download || remove;
      if (!button) return;
      event.preventDefault();
      var attachmentId = button.dataset.attId;
      if (!attachmentId) return;
      if (remove) {
        if (!confirm("정말 이 첨부파일을 삭제하시겠습니까?")) return;
        deleteAttachment(attachmentId, csrfToken)
          .then(function () {
            var item = document.querySelector('[data-att-item="' + CSS.escape(attachmentId) + '"]');
            if (item) item.remove();
          })
          .catch(function () { alert("삭제에 실패했습니다."); });
        return;
      }
      getPresignedGetUrl(attachmentId, csrfToken, download ? "download" : "inline")
        .then(function (url) { window.open(url, "_blank", "noopener"); })
        .catch(function () { alert("파일을 열 수 없습니다."); });
    });
  }

  window.isImageFile = isImageFile;
  window.createImageThumbnail = createImageThumbnail;
  window.uploadImageWithThumbnail = uploadImageWithThumbnail;
  window.uploadSingleFile = uploadSingleFile;
  window.getPresignedGetUrl = getPresignedGetUrl;
  window.deleteAttachment = deleteAttachment;
  window.uploadToEvent = uploadToEvent;
  window.initAttachmentActions = initAttachmentActions;
})(window);
