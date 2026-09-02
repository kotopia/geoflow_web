(function(){
  "use strict";
  function isFinancePage(){return window.top===window.self && /^\/finance(?:\/|$)/.test(window.location.pathname) && !/^\/finance\/import\//.test(window.location.pathname);}
  function makeOption(value,label,selected){var o=document.createElement('option');o.value=value;o.textContent=label;if(selected)o.selected=true;return o;}
  async function init(){
    if(!isFinancePage())return;
    var res;
    try{res=await fetch('/finance/org-options/',{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}});}catch(e){return;}
    if(!res||!res.ok)return;
    var data;try{data=await res.json();}catch(e){return;}
    var root=document.querySelector('.content .container-fluid');if(!root)return;
    if(document.getElementById('financeCompanyFilter'))return;
    var wrap=document.createElement('div');wrap.id='financeCompanyFilter';wrap.className='d-flex align-items-center gap-2 mb-3 flex-wrap';
    var label=document.createElement('span');label.className='text-muted small';label.textContent='귀속회사';wrap.appendChild(label);
    var sel=document.createElement('select');sel.className='form-select form-select-sm';sel.style.maxWidth='320px';
    var selected=String(data.selected||'');sel.appendChild(makeOption('all','전체 회사',!selected));
    (data.options||[]).forEach(function(item){var text=String(item.name||'');if(item.biz_no)text+=' · '+item.biz_no;sel.appendChild(makeOption(String(item.id||''),text,String(item.id||'')===selected));});
    sel.addEventListener('change',function(){var u=new URL(window.location.href);u.searchParams.set('org',sel.value||'all');window.location.href=u.toString();});
    wrap.appendChild(sel);
    var first=root.firstElementChild;if(first)root.insertBefore(wrap,first.nextSibling);else root.appendChild(wrap);
  }
  document.addEventListener('DOMContentLoaded',init);
})();
