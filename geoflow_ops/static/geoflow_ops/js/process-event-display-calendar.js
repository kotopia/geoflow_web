(function (window, document) {
  'use strict';
  // base_tenant.html is the canonical loader. Guard against accidental duplicate
  // execution so window.fetch and ProcessWorkboardUI are never wrapped twice.
  if (window.__GEOFLOW_EVENT_DISPLAY_CALENDAR_LOADED__) return;
  window.__GEOFLOW_EVENT_DISPLAY_CALENDAR_LOADED__ = true;

  var originalFetch = window.fetch.bind(window);
  var lastEditingEvent = null;
  var closingPeriodEvent = false;
  var EVENT_LABELS = {
    estimate:'견적', bid:'입찰', award:'낙찰',
    contract_signed:'체결', contract_change:'변경', contract_cancel:'취소',
    kickoff_submitted:'착수계', kickoff_meeting:'착수회의', kickoff_approved:'착수승인',
    progress_report:'업무보고', suspend:'중지', resume:'재개',
    closeout_submitted:'준공계', closeout_inspection:'준공검사', closeout_approved:'준공승인',
    advance_payment:'선급금', progress_payment:'기성금', final_payment:'준공금'
  };
  // Period-event behavior is kept in one registry so another event type can opt in
  // later without changing the shared event API or creating a separate table.
  // Closing is always explicit; an entered end date never closes the period itself.
  var PERIOD_EVENT_TYPES = {
    suspend: { closeLabel: '중지 종료' }
  };

  function byId(id){return document.getElementById(id);}
  function bool(id){var el=byId(id);return !!(el&&el.checked);}
  function value(id){var el=byId(id);return el?el.value:'';}
  function periodConfig(eventType){return PERIOD_EVENT_TYPES[String(eventType||'')]||null;}
  function eventPayload(ev){return (ev&&ev.payload&&typeof ev.payload==='object')?ev.payload:{};}
  function periodDraftEnd(ev){
    var payload=eventPayload(ev);
    return (ev&&ev.end_at)||payload.period_end_at||'';
  }
  function periodClosed(ev){
    if(!ev||!periodConfig(ev.event_type))return false;
    var payload=eventPayload(ev);
    return ev.status==='done'||payload.period_closed===true;
  }

  function showModalAlert(message){
    var alert=byId('event-alert');
    if(!alert)return;
    alert.textContent=message;
    alert.classList.remove('d-none');
  }

  function syncCalendar(){
    var calendar=byId('event-calendar-enabled'),label=byId('event-calendar-label'),button=byId('btn-event-calendar-toggle');
    if(calendar&&label&&button){
      var nextLabel=calendar.checked?'캘린더에서 제거':'캘린더에 추가';
      if(label.textContent!==nextLabel)label.textContent=nextLabel;
      button.classList.toggle('btn-primary',calendar.checked);
      button.classList.toggle('btn-outline-primary',!calendar.checked);
    }
  }

  function editingOpenPeriodEvent(eventType){
    var ev=lastEditingEvent||null;
    var currentId=value('event-id');
    if(ev&&ev.id){
      if(String(ev.event_type||'')!==String(eventType||''))return false;
      return !periodClosed(ev);
    }
    // After a newly created period event is saved the workboard assigns event-id
    // before the modal is closed. Treat that saved record as editable/open too.
    return !!currentId&&value('event-status')!=='done';
  }

  function syncPeriodControls(){
    var eventType=value('event-type');
    var cfg=periodConfig(eventType);
    var wrap=byId('event-until-closed-wrap');
    var indefinite=byId('event-until-closed');
    var end=byId('event-end-at');
    var closeButton=byId('btn-close-period-event');
    var saveButton=byId('btn-save-event');
    var readOnly=!!(saveButton&&(saveButton.disabled||saveButton.classList.contains('d-none')));

    if(wrap)wrap.classList.toggle('d-none',!cfg);
    if(!cfg){
      if(end)end.disabled=readOnly;
      if(closeButton){closeButton.classList.add('d-none');closeButton.disabled=true;}
      return;
    }

    var noEndDate=!!(indefinite&&indefinite.checked);
    if(end)end.disabled=noEndDate||readOnly;
    if(closeButton){
      closeButton.textContent=cfg.closeLabel;
      var showClose=editingOpenPeriodEvent(eventType)&&!noEndDate&&!!(end&&end.value)&&!readOnly;
      closeButton.classList.toggle('d-none',!showClose);
      closeButton.disabled=!showClose;
    }
  }

  function applyNewPeriodDefault(){
    var eventType=value('event-type');
    var indefinite=byId('event-until-closed');
    var end=byId('event-end-at');
    if(periodConfig(eventType)&&!lastEditingEvent&&!value('event-id')&&indefinite&&!(end&&end.value))indefinite.checked=true;
    syncPeriodControls();
  }

  function validatePeriodEvent(e){
    var eventType=value('event-type');
    if(!periodConfig(eventType))return true;
    if(bool('event-until-closed')||value('event-end-at'))return true;
    if(e){e.preventDefault();e.stopImmediatePropagation();}
    showModalAlert('중지 이벤트는 종료일을 입력하거나 종료일 미정을 체크하세요.');
    return false;
  }

  function bindPeriodControls(){
    var indefinite=byId('event-until-closed');
    var end=byId('event-end-at');
    var type=byId('event-type');
    var stage=byId('event-stage');
    var save=byId('btn-save-event');
    var closeButton=byId('btn-close-period-event');

    if(indefinite&&indefinite.dataset.gfPeriodBound!=='1'){
      indefinite.dataset.gfPeriodBound='1';
      indefinite.addEventListener('change',syncPeriodControls);
    }
    if(end&&end.dataset.gfPeriodBound!=='1'){
      end.dataset.gfPeriodBound='1';
      end.addEventListener('input',syncPeriodControls);
      end.addEventListener('change',syncPeriodControls);
    }
    if(type&&type.dataset.gfPeriodBound!=='1'){
      type.dataset.gfPeriodBound='1';
      type.addEventListener('change',applyNewPeriodDefault);
    }
    if(stage&&stage.dataset.gfPeriodBound!=='1'){
      stage.dataset.gfPeriodBound='1';
      stage.addEventListener('change',function(){window.setTimeout(applyNewPeriodDefault,0);});
    }
    if(save&&save.dataset.gfPeriodValidationBound!=='1'){
      save.dataset.gfPeriodValidationBound='1';
      save.addEventListener('click',function(e){validatePeriodEvent(e);},true);
    }
    if(closeButton&&closeButton.dataset.gfPeriodBound!=='1'){
      closeButton.dataset.gfPeriodBound='1';
      closeButton.addEventListener('click',function(e){
        e.preventDefault();
        if(!validatePeriodEvent(e))return;
        closingPeriodEvent=true;
        var saveButton=byId('btn-save-event');
        if(saveButton&&!saveButton.disabled)saveButton.click();
      });
    }
    syncPeriodControls();
  }

  function installModalControls(){
    var button=byId('btn-event-calendar-toggle'),calendar=byId('event-calendar-enabled');
    if(button&&calendar&&button.dataset.gfBound!=='1'){
      button.dataset.gfBound='1';
      button.addEventListener('click',function(e){
        e.preventDefault();
        calendar.checked=!calendar.checked;
        syncCalendar();
      });
    }
    bindPeriodControls();
    syncCalendar();
    syncPeriodControls();
  }

  function scheduleModalControls(){
    // The event modal is fetched asynchronously. Two bounded callbacks are enough
    // for both a warm modal and its first AJAX insertion; unlike MutationObserver
    // they cannot feed back on DOM writes or monopolize the browser main thread.
    window.setTimeout(installModalControls,80);
    window.setTimeout(installModalControls,240);
  }

  function fillDisplay(ev){
    installModalControls();
    var p=ev||{},end=byId('event-end-at'),calendar=byId('event-calendar-enabled'),indefinite=byId('event-until-closed');
    var displayEnd=periodDraftEnd(p);
    if(end)end.value=displayEnd||'';
    if(calendar)calendar.checked=!!p.calendar_enabled;
    if(indefinite){
      var eventType=String(p.event_type||value('event-type')||'');
      indefinite.checked=!!periodConfig(eventType)&&!displayEnd;
    }
    syncCalendar();
    syncPeriodControls();
  }

  function resetDisplay(){
    var eventType=value('event-type');
    fillDisplay({event_type:eventType,end_at:null,payload:{},calendar_enabled:false});
  }

  function augmentBody(url,options){
    if(!options||String(options.method||'GET').toUpperCase()!=='POST'||!options.body)return options;
    var textUrl=String(url||'');
    if(textUrl.indexOf('/api/events/create/')===-1&&textUrl.indexOf('/api/events/update/')===-1)return options;
    try{
      var body=JSON.parse(options.body);
      if(!body||typeof body!=='object'||!byId('event-end-at'))return options;
      var eventType=String(body.event_type||'');
      var isPeriod=!!periodConfig(eventType);
      var noEndDate=isPeriod&&bool('event-until-closed');
      var endAt=noEndDate?null:(value('event-end-at')||null);
      var existing=lastEditingEvent||{};

      body.calendar_enabled=bool('event-calendar-enabled');
      body.highlight_days=parseInt(existing.highlight_days||'7',10)||7;
      body.due_at=null;

      if(isPeriod){
        var payload=Object.assign({},eventPayload(existing),(body.payload&&typeof body.payload==='object')?body.payload:{});
        payload.period_end_at=endAt;
        if(closingPeriodEvent){
          payload.period_closed=true;
          body.status='done';
          body.highlight_enabled=false;
          body.until_closed=false;
          body.end_at=endAt;
        }else if(periodClosed(existing)){
          payload.period_closed=true;
          body.status=existing.status||'done';
          body.highlight_enabled=false;
          body.until_closed=false;
          body.end_at=existing.end_at||endAt;
        }else{
          // Entering an end date never ends a suspension. The explicit close
          // button is the only operation that changes the active suspension state.
          payload.period_closed=false;
          body.status='open';
          body.highlight_enabled=true;
          body.until_closed=true;
          body.end_at=null;
        }
        body.payload=payload;
        closingPeriodEvent=false;
      }else{
        body.end_at=endAt;
        body.highlight_enabled=(typeof existing.highlight_enabled==='boolean')?existing.highlight_enabled:true;
        body.until_closed=false;
      }
      return Object.assign({},options,{body:JSON.stringify(body)});
    }catch(e){closingPeriodEvent=false;return options;}
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
        badge.className=label==='중지'?'badge bg-danger text-white me-1':'badge bg-warning-subtle text-warning-emphasis border me-1';
        badge.textContent=label;
        container.appendChild(badge);
      });
    });
  }

  function styleSuspensionBadges(){
    document.querySelectorAll('[data-col="workflow"] .badge').forEach(function(badge){
      if(String(badge.textContent||'').trim()!=='중지')return;
      badge.className='badge bg-danger text-white ms-1';
    });
  }
  function eventTimelineTitle(ev){
    return String(ev.title||EVENT_LABELS[ev.event_type]||ev.event_type||'업무 이벤트').trim();
  }
  function eventTimelineDate(ev){
    return String(ev.occurred_at||ev.created_at||'').slice(0,10);
  }
  function decorateSuspensionTimeline(events){
    var rows=(events||[]).filter(function(ev){return ev.event_type==='suspend'&&ev.status!=='void';}).map(function(ev){
      return {title:eventTimelineTitle(ev),date:eventTimelineDate(ev),closed:periodClosed(ev),active:!!ev.highlight_active,used:false};
    });
    if(!rows.length)return;
    document.querySelectorAll('#contractTimelineList > li, #projectTimelineList > li').forEach(function(item){
      var title=item.querySelector('strong');
      if(!title)return;
      var titleText=String(title.textContent||'').trim();
      var text=String(item.textContent||'');
      var match=rows.find(function(row){return !row.used&&row.title===titleText&&(!row.date||text.indexOf(row.date)!==-1);});
      if(!match)return;
      match.used=true;
      item.classList.toggle('border-start',match.active&&!match.closed);
      item.classList.toggle('border-3',match.active&&!match.closed);
      item.classList.toggle('border-danger',match.active&&!match.closed);
      item.classList.toggle('ps-2',match.active&&!match.closed);
      if(match.closed&&!item.querySelector('.gf-period-closed-badge')){
        var badge=document.createElement('span');
        badge.className='badge bg-secondary-subtle text-secondary-emphasis ms-2 gf-period-closed-badge';
        badge.textContent='종료';
        item.insertBefore(badge,title.nextSibling);
      }
    });
  }
  function scheduleSuspensionTimeline(events){
    window.setTimeout(function(){decorateSuspensionTimeline(events);},120);
    window.setTimeout(function(){decorateSuspensionTimeline(events);},420);
  }

  function loadCurrentStageBadges(){
    var mount=byId('eventModalMount');
    styleSuspensionBadges();
    if(!mount)return;
    var url=mount.getAttribute('data-events-list-url')||mount.getAttribute('data-event-list-url');
    var scopeType=mount.getAttribute('data-scope-type'),scopeId=mount.getAttribute('data-scope-id');
    if(!url||!scopeType||!scopeId)return;
    originalFetch(url+'?scope_type='+encodeURIComponent(scopeType)+'&scope_id='+encodeURIComponent(scopeId),{credentials:'same-origin'})
      .then(function(r){if(!r.ok)throw new Error();return r.json();})
      .then(function(data){
        var events=data.events||[];
        renderStageBadges(events.filter(function(ev){return !!ev.highlight_active;}));
        scheduleSuspensionTimeline(events);
      })
      .catch(function(){renderStageBadges([]);});
  }
  function fixSettingsCopy(){
    var card=byId('workflow-standard-settings');if(!card)return;
    var note=card.querySelector('.card-body > .small.text-muted.mt-3');
    if(note)note.textContent='업무단계는 준비 → 계약 → 착수 → 수행 → 준공 → 완료의 Process Stage와 동일합니다. 정산(선급금·기성금·준공금)은 이벤트 전용 분류이며 Process Stage를 변경하지 않습니다.';
  }

  document.addEventListener('DOMContentLoaded',function(){
    markProcessTimeline();
    styleSuspensionBadges();
    loadCurrentStageBadges();
    fixSettingsCopy();
    installModalControls();
    var add=byId('btn-add-event');
    if(add)add.addEventListener('click',function(){scheduleModalControls();window.setTimeout(resetDisplay,90);window.setTimeout(resetDisplay,250);});
    var timeline=byId('timelineList');
    if(timeline)timeline.addEventListener('click',function(){scheduleModalControls();});
  });
  document.addEventListener('hidden.bs.modal',function(event){
    if(event.target&&event.target.id==='eventModal')window.setTimeout(loadCurrentStageBadges,320);
  });

  var attempts=0,timer=window.setInterval(function(){
    attempts+=1;var api=window.ProcessWorkboardUI;
    if(api&&!api.__displayCalendarWrapped){
      var create=api.openCreateModal,edit=api.openEditModal;
      api.openCreateModal=function(){lastEditingEvent=null;closingPeriodEvent=false;var result=create.apply(api,arguments);scheduleModalControls();window.setTimeout(resetDisplay,90);window.setTimeout(resetDisplay,250);return result;};
      api.openEditModal=function(ev){lastEditingEvent=ev||null;closingPeriodEvent=false;var result=edit.apply(api,arguments);scheduleModalControls();window.setTimeout(function(){fillDisplay(lastEditingEvent);},90);window.setTimeout(function(){fillDisplay(lastEditingEvent);},250);return result;};
      api.__displayCalendarWrapped=true;window.clearInterval(timer);
    }else if(attempts>200){window.clearInterval(timer);}
  },25);
})(window,document);
