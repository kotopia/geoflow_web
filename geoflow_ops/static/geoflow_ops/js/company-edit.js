(function () {
  'use strict';
  const root = document.getElementById('company-editor');
  if (!root) return;
  const companyId = root.dataset.company;
  if (window.initAttachmentActions) window.initAttachmentActions({root: document, csrfToken: document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''});
  const legacy = document.getElementById('legacy-business');
  if (legacy) legacy.classList.add('show', 'active');
  async function upload(file, purpose, title, csrf) {
    if (file.size > 25 * 1024 * 1024) throw new Error('파일당 최대 25MB까지 첨부할 수 있습니다.');
    return window.uploadSingleFile({file, entityType: 'orgunit', entityId: companyId, purpose, documentTitle: title, csrfToken: csrf});
  }
  const form = document.getElementById('company-fact-form');
  if (form) {
    const uploaded = new Map();
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      if (button.disabled) return;
      button.disabled = true;
      const status = document.getElementById('company-save-status');
      status.textContent = '저장 중…';
      try {
        const files = document.getElementById('evidence-files');
        for (const file of (files ? files.files : [])) {
          const key = `${file.name}:${file.size}:${file.lastModified}`;
          if (uploaded.has(key)) continue;
          const result = await upload(file, form.dataset.purpose, form.elements.name?.value || form.elements.agency?.value || '기업 증빙', form.elements.csrfmiddlewaretoken.value);
          uploaded.set(key, result.attachment_id);
          const input = document.createElement('input');
          input.type = 'hidden'; input.name = 'evidence'; input.value = result.attachment_id;
          form.appendChild(input);
        }
        HTMLFormElement.prototype.submit.call(form);
      } catch (error) {
        status.textContent = error.message || '저장에 실패했습니다. 다시 시도하세요.';
        button.disabled = false;
      }
    });
  }
  document.querySelectorAll('.company-document-form').forEach(function (form) {
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const status = form.querySelector('.upload-message');
      button.disabled = true;
      try {
        for (const file of form.elements.files.files) await upload(file, form.dataset.purpose, form.elements.document_title.value, form.elements.csrfmiddlewaretoken.value);
        window.location.reload();
      } catch (error) { status.textContent = error.message; button.disabled = false; }
    });
  });
})();
