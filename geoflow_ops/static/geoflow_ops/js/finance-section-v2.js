(function(){
  "use strict";

  function num(v){ var n=Number(String(v==null?"":v).replace(/,/g,"")); return Number.isFinite(n)?n:0; }
  function fmt(v){ return Math.round(num(v)).toLocaleString("ko-KR",{maximumFractionDigits:0}); }
  function moneyInput(el){ return el && (el.hasAttribute("data-fin-supply")||el.hasAttribute("data-fin-vat")||el.hasAttribute("data-fin-total")||el.hasAttribute("data-fin-amount")); }
  function prepMoney(el){ if(!el||el.dataset.moneyReady)return; el.dataset.moneyReady="1"; el.type="text"; el.inputMode="numeric"; el.value=fmt(el.value||0); el.addEventListener("input",function(){var raw=String(el.value||"").replace(/[^0-9-]/g,""); if(!raw||raw==="-"){el.value=raw;return;} var neg=raw[0]==="-"; raw=raw.replace(/-/g,"").replace(/^0+(?=\d)/,""); el.value=(neg?"-":"")+Number(raw||0).toLocaleString("ko-KR");}); }
  function bindMoney(form){ var s=form.querySelector("[data-fin-supply]"),v=form.querySelector("[data-fin-vat]"),t=form.querySelector("[data-fin-total]"); if(!s||!v||!t)return; s.addEventListener("input",function(){var a=Math.round(num(s.value)),b=Math.round(a*.1);v.value=fmt(b);t.value=fmt(a+b);}); v.addEventListener("input",function(){t.value=fmt(num(s.value)+num(v.value));}); t.addEventListener("input",function(){var total=Math.round(num(t.value)),supply=Math.round(total/1.1);s.value=fmt(supply);v.value=fmt(total-supply);}); }

  function stripCorp(s){return String(s||"").replace(/^\s*(?:\(\s*[주유합]\s*\)|㈜|주식회사|유한회사|합자회사|합명회사)\s*/g,"").replace(/\s*(?:\(\s*[주유합]\s*\)|㈜|주식회사|유한회사|합자회사|합명회사)\s*$/g,"").trim();}
  function sortPartners(sel){var blank=sel.querySelector("option[value='']"),opts=Array.from(sel.options).filter(function(o){return o.value;});opts.sort(function(a,b){return stripCorp(a.textContent).localeCompare(stripCorp(b.textContent),"ko",{sensitivity:"base"});});sel.innerHTML="";if(blank)sel.appendChild(blank);opts.forEach(function(o){sel.appendChild(o);});}
  function destroyChoice(sel){if(sel&&sel._finChoice){try{sel._finChoice.destroy();}catch(e){} sel._finChoice=null;delete sel.dataset.choiceReady;}}
  function initChoice(sel,kind){if(!sel||sel.dataset.choiceReady||!window.Choices)return;if(kind==="partner")sortPartners(sel);sel.dataset.choiceReady="1";sel._finChoice=new Choices(sel,{searchEnabled:true,shouldSort:false,itemSelectText:"",removeItemButton:false,placeholder:true,searchPlaceholderValue:kind==="contract"?"계약번호 또는 계약명 검색":"회사명 검색",noResultsText:"검색 결과가 없습니다",noChoicesText:"선택 가능한 항목이 없습니다"});}
  function setSelect(sel,value){if(!sel)return;var v=value?String(value):"";if(sel._finChoice){try{sel._finChoice.removeActiveItems();if(v)sel._finChoice.setChoiceByValue(v);}catch(e){sel.value=v;}}else sel.value=v;sel.dispatchEvent(new Event("change",{bubbles:true}));}

  function selectedOption(sel){return sel&&sel.selectedIndex>=0?sel.options[sel.selectedIndex]:null;}
  function applyContractMeta(form,meta){
    var org=form.querySelector(".js-fin-org"),partner=form.querySelector(".js-fin-partner"),hint=form.querySelector(".js-fin-client-hint");
    var orgId=String((meta&&meta.org_unit_id)||""),clientId=String((meta&&meta.client_id)||"");
    if(orgId)setSelect(org,orgId);
    if(clientId)setSelect(partner,clientId);
    if(hint){
      if(clientId)hint.textContent="계약 발주처: "+String((meta&&meta.client_name)||"선택됨")+" · 필요하면 다른 거래처로 변경할 수 있습니다.";
      else hint.textContent="이 계약에 등록된 발주처가 없습니다.";
    }
  }
  async function applyContract(form){
    if(form.dataset.finHydrating==="1")return;
    var c=form.querySelector(".js-fin-contract");
    if(!c||!c.value)return;
    var o=selectedOption(c);
    var fallback={client_id:o?o.dataset.clientId||"":"",org_unit_id:o?o.dataset.orgUnitId||"":"",client_name:""};
    applyContractMeta(form,fallback);
    try{
      var r=await fetch("/finance/contracts/"+encodeURIComponent(c.value)+"/defaults/",{credentials:"same-origin",headers:{"X-Requested-With":"XMLHttpRequest"}});
      if(!r.ok)return;
      var data=await r.json();
      if(String(c.value)!==String(data.contract_id||""))return;
      applyContractMeta(form,data);
    }catch(e){}
  }
  function applyAccount(form){var a=form.querySelector(".js-fin-account"),org=form.querySelector(".js-fin-org");if(!a||!a.value)return;var o=selectedOption(a),orgId=o?o.dataset.orgUnitId||"":"";if(orgId)setSelect(org,orgId);}

  var maps={
    claim:{record_id:"id",claim_date:"date",due_date:"dueDate",expected_receipt_date:"receiptDate",title:"titleValue",contract_id:"contractId",partner_id:"partnerId",my_org_unit_id:"orgUnitId",claim_type:"claimType",supply_amount:"supply",vat_amount:"vat",total_amount:"total",status:"status",memo:"memo"},
    invoice:{record_id:"id",written_date:"writtenDate",issued_date:"issuedDate",invoice_type:"type",contract_id:"contractId",partner_id:"partnerId",my_org_unit_id:"orgUnitId",claim_id:"claimId",payment_request_id:"paymentId",approval_no:"approvalNo",supply_amount:"supply",vat_amount:"vat",total_amount:"total",status:"status",memo:"memo"},
    payment:{record_id:"id",request_date:"date",due_date:"dueDate",title:"titleValue",contract_id:"contractId",partner_id:"partnerId",my_org_unit_id:"orgUnitId",amount:"amount",category_code:"category",status:"status",memo:"memo"},
    transaction:{record_id:"id",transaction_date:"date",transaction_type:"type",amount:"amount",contract_id:"contractId",partner_id:"partnerId",my_org_unit_id:"orgUnitId",account_id:"accountId",description:"description",claim_id:"claimId",payment_request_id:"paymentId",category_code:"category",evidence_type:"evidence",memo:"memo"}
  };
  function setField(form,name,val){var el=form.elements[name];if(!el)return;if(el.tagName==="SELECT")setSelect(el,val);else if(moneyInput(el))el.value=fmt(val||0);else el.value=val==null?"":val;}
  function resetForm(form){form.querySelectorAll(".js-fin-contract,.js-fin-partner").forEach(destroyChoice);form.reset();if(form.elements.record_id)form.elements.record_id.value="";form.querySelectorAll("input").forEach(function(el){if(moneyInput(el))el.value=fmt(0);});form.querySelectorAll("[data-fin-attachment-panel]").forEach(function(panel){panel.classList.add("d-none");panel.dataset.recordId="";});}
  function prepareModal(modal,button,edit){var form=modal.querySelector("form");resetForm(form);if(edit){form.dataset.finHydrating="1";var kind=button.dataset.kind,map=maps[kind]||{};Object.keys(map).forEach(function(name){setField(form,name,button.dataset[map[name]]||"");});delete form.dataset.finHydrating;var panel=form.querySelector("[data-fin-attachment-panel]");if(panel&&button.dataset.id){panel.classList.remove("d-none");panel.dataset.recordId=button.dataset.id;panel.dataset.hasAttachment=button.dataset.attachmentId?"1":"0";var st=panel.querySelector("[data-fin-attachment-status]");if(st)st.textContent=button.dataset.attachmentId?"증빙이 첨부되어 있습니다.":"첨부된 증빙이 없습니다.";}}modal.addEventListener("shown.bs.modal",function once(){modal.querySelectorAll(".js-fin-contract").forEach(function(s){initChoice(s,"contract");});modal.querySelectorAll(".js-fin-partner").forEach(function(s){initChoice(s,"partner");});},{once:true});bootstrap.Modal.getOrCreateInstance(modal).show();}

  function csrf(form){var el=form&&form.querySelector("input[name='csrfmiddlewaretoken']");return el?el.value:"";}
  async function uploadAttachment(panel){
    var fileInput=panel.querySelector("[data-fin-attachment-file]"),file=fileInput&&fileInput.files?fileInput.files[0]:null,id=panel.dataset.recordId,type=panel.dataset.recordType,status=panel.querySelector("[data-fin-attachment-status]");
    if(!id){if(status)status.textContent="먼저 저장한 뒤 수정 화면에서 첨부하세요.";return;}if(!file){if(status)status.textContent="파일을 선택하세요.";return;}
    if(status)status.textContent="업로드 준비 중…";
    var token=csrf(panel.closest("form"));
    var pre=await fetch("/finance/attachments/presign/",{method:"POST",headers:{"Content-Type":"application/json","X-CSRFToken":token},credentials:"same-origin",body:JSON.stringify({record_type:type,record_id:id,filename:file.name,mime_type:file.type||"application/octet-stream",size_bytes:file.size})});
    var pdata=await pre.json();if(!pre.ok)throw new Error(pdata.error||"업로드 준비 실패");
    var putHeaders=Object.assign({},pdata.headers||{});if(!putHeaders["Content-Type"]&&file.type)putHeaders["Content-Type"]=file.type;
    var put=await fetch(pdata.presigned_url,{method:"PUT",headers:putHeaders,body:file});if(!put.ok)throw new Error("S3 업로드 실패");
    var commit=await fetch("/finance/attachments/commit/",{method:"POST",headers:{"Content-Type":"application/json","X-CSRFToken":token},credentials:"same-origin",body:JSON.stringify({record_type:type,record_id:id,object_key:pdata.object_key,filename:file.name})});
    var cdata=await commit.json();if(!commit.ok)throw new Error(cdata.error||"첨부 저장 실패");panel.dataset.hasAttachment="1";if(status)status.textContent="첨부 완료: "+(cdata.original_name||file.name);
  }
  async function downloadAttachment(panel){var id=panel.dataset.recordId,type=panel.dataset.recordType,status=panel.querySelector("[data-fin-attachment-status]");if(!id)return;var r=await fetch("/finance/attachments/"+type+"/"+id+"/download/",{credentials:"same-origin"}),data=await r.json();if(!r.ok){if(status)status.textContent=data.error||"첨부가 없습니다.";return;}window.location.href=data.presigned_url;}

  function applyRefLabels(){var raw=document.getElementById("finance-ref-data");if(!raw)return;var refs={};try{refs=JSON.parse(raw.textContent||"{}");}catch(e){}var refMaps={};Object.keys(refs).forEach(function(key){refMaps[key]={};(refs[key]||[]).forEach(function(o){refMaps[key][String(o.code)]=o.name;});});document.querySelectorAll("[data-ref-field]").forEach(function(el){var key=el.dataset.refField,code=String(el.textContent||"").trim();if(refMaps[key]&&refMaps[key][code])el.textContent=refMaps[key][code];});}

  function injectDeleteButtons(){
    var tokenEl=document.querySelector('input[name="csrfmiddlewaretoken"]'),token=tokenEl?tokenEl.value:'';
    if(!token)return;
    document.querySelectorAll('[data-fin-edit][data-id][data-kind]').forEach(function(btn){
      var kind=String(btn.dataset.kind||''),id=String(btn.dataset.id||'');
      if(['payment','transaction'].indexOf(kind)<0||!id)return;
      var cell=btn.parentElement;if(!cell||cell.querySelector('[data-fin-dynamic-delete="'+kind+'"]'))return;
      var form=document.createElement('form');form.method='post';form.action='/finance/'+encodeURIComponent(kind)+'/'+encodeURIComponent(id)+'/delete/';form.className='d-inline ms-1';form.dataset.finDynamicDelete=kind;
      var csrfInput=document.createElement('input');csrfInput.type='hidden';csrfInput.name='csrfmiddlewaretoken';csrfInput.value=token;form.appendChild(csrfInput);
      var next=document.createElement('input');next.type='hidden';next.name='next';next.value=window.location.pathname+window.location.search;form.appendChild(next);
      var del=document.createElement('button');del.type='submit';del.className='btn btn-sm btn-outline-danger';del.textContent='삭제';form.appendChild(del);
      form.addEventListener('submit',function(e){if(!window.confirm('삭제함으로 이동하시겠습니까?'))e.preventDefault();});
      cell.appendChild(form);
    });
  }

  document.addEventListener("DOMContentLoaded",function(){
    document.querySelectorAll("input").forEach(function(el){if(moneyInput(el))prepMoney(el);});
    document.querySelectorAll("form[data-fin-money-form]").forEach(bindMoney);
    document.querySelectorAll("form").forEach(function(form){var c=form.querySelector(".js-fin-contract"),a=form.querySelector(".js-fin-account");if(c)c.addEventListener("change",function(){applyContract(form);});if(a)a.addEventListener("change",function(){applyAccount(form);});});
    document.querySelectorAll("[data-fin-create]").forEach(function(b){b.addEventListener("click",function(){var m=document.querySelector(b.dataset.target);if(m)prepareModal(m,b,false);});});
    document.querySelectorAll("[data-fin-edit]").forEach(function(b){b.addEventListener("click",function(){var m=document.querySelector(b.dataset.target);if(m)prepareModal(m,b,true);});});
    document.querySelectorAll("[data-fin-attachment-upload]").forEach(function(b){b.addEventListener("click",function(){var p=b.closest("[data-fin-attachment-panel]");uploadAttachment(p).catch(function(e){var s=p.querySelector("[data-fin-attachment-status]");if(s)s.textContent=e.message||"업로드 실패";});});});
    document.querySelectorAll("[data-fin-attachment-download]").forEach(function(b){b.addEventListener("click",function(){downloadAttachment(b.closest("[data-fin-attachment-panel]"));});});
    document.querySelectorAll("[data-fin-import-open]").forEach(function(b){b.addEventListener("click",function(){var f=document.querySelector("[data-fin-import-frame]");if(f)f.src=window.location.origin+"/finance/import/?modal=1&import_type="+encodeURIComponent(b.dataset.importType||"transaction");});});
    window.addEventListener("message",function(event){if(event&&event.origin===window.location.origin&&event.data&&event.data.type==="finance-import-complete")window.location.reload();});
    injectDeleteButtons();
    applyRefLabels();
  });
})();
