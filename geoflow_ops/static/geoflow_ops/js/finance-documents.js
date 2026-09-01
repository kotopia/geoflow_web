(function () {
  function csrf() {
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }
  function basePath() {
    var path = window.location.pathname;
    var marker = '/finance/';
    var index = path.indexOf(marker);
    return index >= 0 ? path.slice(0, index) : '';
  }
  function api(path) { return basePath() + path; }
  function alertBox(message, kind) {
    var host = document.getElementById('financeDocumentAlert');
    if (!host) return;
    host.innerHTML = '<div class="alert alert-' + (kind || 'info') + ' py-2">' + message + '</div>';
  }
  async function postJson(url, payload) {
    var response = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type':'application/json','X-CSRFToken':csrf()},
      body: JSON.stringify(payload)
    });
    var data = await response.json().catch(function(){ return {}; });
    if (!response.ok) throw new Error(data.error || '요청에 실패했습니다.');
    return data;
  }
  document.addEventListener('change', async function (event) {
    var input = event.target.closest('.js-fin-doc-upload');
    if (!input || !input.files || !input.files[0]) return;
    var file = input.files[0];
    input.disabled = true;
    try {
      alertBox('증빙 파일을 업로드하고 있습니다.', 'info');
      var common = {record_type: input.dataset.recordType, record_id: input.dataset.recordId, filename:file.name, mime_type:file.type || 'application/octet-stream', size_bytes:file.size};
      var signed = await postJson(api('/finance/attachments/presign/'), common);
      var put = await fetch(signed.presigned_url, {method:'PUT', headers:signed.headers || {}, body:file});
      if (!put.ok) throw new Error('S3 업로드에 실패했습니다.');
      await postJson(api('/finance/attachments/commit/'), Object.assign({}, common, {object_key:signed.object_key}));
      alertBox('증빙 파일을 연결했습니다.', 'success');
      window.location.reload();
    } catch (error) {
      alertBox(error.message || '업로드에 실패했습니다.', 'danger');
      input.disabled = false;
      input.value = '';
    }
  });
  document.addEventListener('click', async function (event) {
    var button = event.target.closest('.js-fin-doc-download');
    if (!button) return;
    button.disabled = true;
    try {
      var response = await fetch(api('/finance/attachments/' + button.dataset.recordType + '/' + button.dataset.recordId + '/download/'), {credentials:'same-origin'});
      var data = await response.json().catch(function(){ return {}; });
      if (!response.ok) throw new Error(data.error || '파일을 열 수 없습니다.');
      window.location.href = data.presigned_url;
    } catch (error) {
      alertBox(error.message || '파일을 열 수 없습니다.', 'danger');
      button.disabled = false;
    }
  });
})();
