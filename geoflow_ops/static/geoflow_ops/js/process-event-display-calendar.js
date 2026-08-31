(function (window, document) {
  'use strict';
  var originalFetch = window.fetch.bind(window);
  var lastEditingEvent = null;
  var EVENT_LABELS = {
    estimate:'견적', bid:'입찰', award:'낙찰',
    contract_signed:'체결', contract_change:'변경', contract_cancel:'취소',
    kickoff_submitted:'착수계', kickoff_meeting:'착수회의', kickoff_approved:'착수승인',
    progress_report:'업무보고', suspend:'중지', resume:'재개',
    closeout_submitted:'준공계', closeout_inspection:'준공검사', closeout_approved:'준공승인',
    advance_payment:'선급금', progress_payment:'기성금', final_payment:'준공금'
  };
  function byId(id){return document.getElementById(id);}
  function bool(id){var el=byId(id);return !!(el&&el.checked);}
  function value(id){var el=byId(id);return el?el.value:'';}

  function syncCalendar(){
    var calendar=byId('event-calendar-enabled'),label=byId('event-calendar-label'),button=byId('btn-event-calendar-toggle');
    if(calendar&&label&&button){
      label.textContent=calendar.checked?'캘린더에서 제거':'캘린더에 추가';
      button.classList.toggle('btn-primary',calendar.checked);
      button.classList.toggle('btn-outline-primary',!calendar.checked);
    }
  }
  function installModalControls(){
    var button=byId('btn-event-calendar-toggle'),calendar=byId('event-calendar-enabled');
    if(button&&calendar&&button.dataset.gfBound!=='1'){
      button.dataset.gfBound='1';
      button.addEventListener('click',function(){calendar.checked=!calendar.checked;syncCalendar();});
    }
    syncCalendar();
  }
  function fillDisplay(ev){
    installModalControls();
    var p=ev||{},end=byId('event-end-at'),calendar=byId('event-calendar-enabled');
    if(end)end.value=p.end_at||'';
    if(calendar)calendar.checked=!!p.calendar_enabled;
    syncCalendar();
  }
  function resetDisplay(){fillDisplay({end_at:null,calendar_enabled:false});}

  function augmentBody(url,options){
    if(!options||String(options.method||'GET').toUpperCase()!=='POST'||!options.body)return options;
    var textUrl=String(url||'');
    if(textUrl.indexOf('/api/events/create/')===-1&&textUrl.indexOf('/api/events/update/')===-1)return options;
    try{
      var body=JSON.parse(options.body);
      if(!body||typeof body!=='object'||!byId('event-end-at'))return options;
      var eventType=String(body.event_type||'');
      var endAt=value('event-end-at')||null;
      var existing=lastEditingEvent||{};
      body.end_at=endAt;
      body.calendar_enabled=bool('event-calendar-enabled');
      body.highlight_enabled=(typeof existing.highlight_enabled==='boolean')?existing.highlight_enabled:true;
      body.highlight_days=parseInt(existing.highlight_days||'7',10)||7;
      body.until_closed=(eventType==='suspend'&&!endAt);
      // 완료예정일(due_at)은 더 이상 사용자 데이터가 아니다. 기존 값은
      // migration에서 종료일로 이관되고, 이후 쓰기에서는 비운다.
      body.due_at=null;
      return Object.assign({},options,{body:JSON.stringify(body)});
    }catch(e){return options;}
  }
  window.fetch=function(url,options){return originalFetch(url,augmentBody(url,options));};

  function markProcessTimeline(){
    document.querySelectorAll('[aria-label="업무 프로세스"]').forEach(function(flow){
      var stages=Array.from(flow.querySelectorAll(':scope > span[aria-label]'));
      var current=stages.findIndex(function(stage){return stage.classList.contains('text-primary');});
      stages.forEach(function(stage,index){stage.classList.toggle('gf-stage-complete',current>=0&&index<current);});
    });
  }
  function currentStageLabel(){
    var flow=document.querySelector('[aria-label="업무 프로세스"]');
    if(!flow)return '';
    var current=Array.from(flow.querySelectorAll(':scope > span[aria-label]')).find(function(stage){return stage.classList.contains('text-primary');});
    return current?String(current.textContent||'').trim():'';
  }
  function targetStageContainers(){
    var result=[];
    document.querySelectorAll('.row').forEach(function(row){
      var label=row.querySelector('.small.text-muted');
      if(!label)return;
      var text=String(label.textContent||'').trim();
      if(text==='현재 업무단계'){
        var cols=row.children;
        if(cols&&cols.length>1)result.push(cols[1]);
      }
    });
    document.querySelectorAll('label.small.text-muted').forEach(function(label){
      if(String(label.textContent||'').trim()!=='업무단계')return;
      var parent=label.parentElement;
      var valueEl=parent&&parent.querySelector('.form-control-plaintext');
      if(valueEl)result.push(valueEl);
    });
    return result;
  }
  function renderStageBadges(activeEvents){
    var stage=currentStageLabel();
    if(!stage)return;
    var labels=[];
    (activeEvents||[]).forEach(function(ev){
      var label=EVENT_LABELS[ev.event_type]||ev.event_type||'';
      if(label&&labels.indexOf(label)===-1)labels.push(label);
    });
    targetStageContainers().forEach(function(container){
      container.replaceChildren();
      var stageBadge=document.createElement('span');
      stageBadge.className='badge bg-primary me-1';
      stageBadge.textContent=stage;
      container.appendChild(stageBadge);
      labels.forEach(function(label){
        var badge=document.createElement('span');
        badge.className='badge bg-warning-subtle text-warning-emphasis border me-1';
        badge.textContent=label;
        container.appendChild(badge);
      });
    });
  }
  function loadCurrentStageBadges(){
    var mount=byId('eventModalMount');
    if(!mount)return;
    var url=mount.getAttribute('data-events-list-url')||mount.getAttribute('data-event-list-url');
    var scopeType=mount.getAttribute('data-scope-type'),scopeId=mount.getAttribute('data-scope-id');
    if(!url||!scopeType||!scopeId)return;
    originalFetch(url+'?scope_type='+encodeURIComponent(scopeType)+'&scope_id='+encodeURIComponent(scopeId),{credentials:'same-origin'})
      .then(function(r){if(!r.ok)throw new Error();return r.json();})
      .then(function(data){renderStageBadges((data.events||[]).filter(function(ev){return !!ev.highlight_active;}));})
      .catch(function(){renderStageBadges([]);});
  }
  function fixSettingsCopy(){
    var card=byId('workflow-standard-settings');if(!card)return;
    var note=card.querySelector('.card-body > .small.text-muted.mt-3');
    if(note)note.textContent='업무단계는 준비 → 계약 → 착수 → 수행 → 준공 → 완료의 Process Stage와 동일합니다. 정산(선급금·기성금·준공금)은 이벤트 전용 분류이며 Process Stage를 변경하지 않습니다.';
  }

  var observer=new MutationObserver(function(){installModalControls();});
  observer.observe(document.documentElement,{childList:true,subtree:true});
  document.addEventListener('DOMContentLoaded',function(){
    markProcessTimeline();
    loadCurrentStageBadges();
    fixSettingsCopy();
    var add=byId('btn-add-event');if(add)add.addEventListener('click',function(){window.setTimeout(resetDisplay,70);window.setTimeout(resetDisplay,200);});
  });
  var attempts=0,timer=window.setInterval(function(){
    attempts+=1;var api=window.ProcessWorkboardUI;
    if(api&&!api.__displayCalendarWrapped){
      var create=api.openCreateModal,edit=api.openEditModal;
      api.openCreateModal=function(){lastEditingEvent=null;var result=create.apply(api,arguments);window.setTimeout(resetDisplay,80);window.setTimeout(resetDisplay,220);return result;};
      api.openEditModal=function(ev){lastEditingEvent=ev||null;var result=edit.apply(api,arguments);window.setTimeout(function(){fillDisplay(lastEditingEvent);},80);window.setTimeout(function(){fillDisplay(lastEditingEvent);},220);return result;};
      api.__displayCalendarWrapped=true;window.clearInterval(timer);
    }else if(attempts>200){window.clearInterval(timer);}
  },25);
})(window,document);
