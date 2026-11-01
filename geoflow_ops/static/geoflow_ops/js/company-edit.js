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
    const status = document.getElementById('company-save-status');
    const queue = new Map();
    const picker = document.getElementById('evidence-files');
    const add = document.getElementById('evidence-add');
    let busy = false;
    function renderQueue() {
      const list = document.getElementById('evidence-queue');
      if (!list) return;
      list.replaceChildren();
      for (const [key,item] of queue) {
        const row=document.createElement('div');row.className='company-file';
        const name=document.createElement('span');name.className='company-file-name';name.textContent=item.file.name;
        const state=document.createElement('small');state.className='text-muted';state.textContent=item.input?'업로드 완료 · 저장 대기':'선택됨';
        const remove=document.createElement('button');remove.type='button';remove.className='btn btn-light btn-sm';remove.textContent='제거';remove.disabled=busy;
        remove.addEventListener('click',()=>{item.input?.remove();queue.delete(key);renderQueue();});
        row.append(name,state,remove);list.append(row);
      }
    }
    add?.addEventListener('click',()=>picker.click());
    picker?.addEventListener('change',()=>{
      for(const file of picker.files){
        if(file.size>25*1024*1024){status.textContent='파일당 최대 25MB까지 첨부할 수 있습니다.';continue;}
        const key=`${file.name}:${file.size}:${file.lastModified}`;
        if(queue.has(key)) continue;
        if(queue.size>=50){status.textContent='최대 50개까지 선택할 수 있습니다.';break;}
        queue.set(key,{file,input:null});
      }
      picker.value='';renderQueue();
    });
    const nodeKind = form.elements.node_kind;
    function parentLabel(){const label=document.getElementById('parent-label');if(label)label.textContent=nodeKind?.value==='branch'?'소속 기업':'모기업';}
    nodeKind?.addEventListener('change',parentLabel);parentLabel();
    const itemsInput=form.elements.items,itemsRoot=document.getElementById('company-items');
    let itemSequence=0;
    function addItem(item={}) {
      const id=++itemSequence;
      const row=document.createElement('div');row.className='company-item row g-2';
      for(const [key,label,type] of [['name','세부품명','text'],['code','품목 코드','text'],['valid_from','유효기간 시작','date'],['expires_on','유효기간 종료','date']]){
        const col=document.createElement('div');col.className='col-md-6';
        const lab=document.createElement('label');lab.className='form-label';lab.htmlFor=`item-${id}-${key}`;lab.textContent=label;
        const input=document.createElement('input');input.id=lab.htmlFor;input.className='form-control';input.type=type;input.dataset.itemField=key;input.value=item[key]||'';input.required=key==='name';if(type==='text')input.maxLength=key==='name'?200:100;
        col.append(lab,input);row.append(col);
      }
      const remove=document.createElement('button');remove.type='button';remove.className='btn btn-light btn-sm mt-2';remove.textContent='품목 제거';remove.addEventListener('click',()=>row.remove());row.append(remove);itemsRoot.append(row);
    }
    if(itemsInput&&itemsRoot){
      try{const existing=JSON.parse(itemsInput.value||'[]');if(Array.isArray(existing))existing.forEach(addItem);}catch(_){status.textContent='품목 데이터를 확인하세요.';}
      document.getElementById('company-item-add')?.addEventListener('click',()=>addItem());
    }
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      if(busy) return;
      if(itemsInput&&itemsRoot){
        const items=[...itemsRoot.children].map(row=>Object.fromEntries([...row.querySelectorAll('[data-item-field]')].map(input=>[input.dataset.itemField,input.value])));
        if(items.some(item=>item.valid_from&&item.expires_on&&item.expires_on<item.valid_from)){status.textContent='품목 종료일은 시작일 이후여야 합니다.';return;}
        itemsInput.value=JSON.stringify(items);
      }
      if(!form.reportValidity()) return;
      const count=form.querySelectorAll('input[name=evidence]:checked').length+queue.size;
      if(count>50){status.textContent='증빙은 최대 50개까지 연결할 수 있습니다.';return;}
      const button = form.querySelector('[type="submit"]');
      busy=true;button.disabled=true;if(add)add.disabled=true;renderQueue();status.textContent='저장 중…';
      try {
        for (const item of queue.values()) {
          if (item.input) continue;
          const result = await upload(item.file, form.dataset.purpose, form.elements.name?.value || form.elements.agency?.value || '기업 증빙', form.elements.csrfmiddlewaretoken.value);
          if(!result.attachment_id)throw new Error('업로드 결과를 확인할 수 없습니다.');
          const input = document.createElement('input');
          input.type='hidden';input.name='evidence';input.value=result.attachment_id;
          form.appendChild(input);item.input=input;renderQueue();
        }
        HTMLFormElement.prototype.submit.call(form);
      } catch (error) {
        status.textContent=error.message||'저장에 실패했습니다. 입력값을 유지했습니다. 다시 시도하세요.';
        busy=false;button.disabled=false;if(add)add.disabled=false;renderQueue();
      }
    });
  }
  document.querySelectorAll('.company-document-form').forEach(function (form) {
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const button=form.querySelector('[type="submit"]'),status=form.querySelector('.upload-message');
      button.disabled=true;
      try {
        for(const file of form.elements.files.files)await upload(file,form.dataset.purpose,form.elements.document_title.value,form.elements.csrfmiddlewaretoken.value);
        window.location.reload();
      } catch(error){status.textContent=error.message;button.disabled=false;}
    });
  });
})();
