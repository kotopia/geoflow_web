/* Contract adapter around DataTables SearchBuilder; no business SQL or amount math. */
(function () {
  'use strict';
  const fields = [
    ['code','계약번호','string'], ['name','계약명','string'], ['status','상태','string'],
    ['start','시작일','date'], ['end','종료일','date'], ['kind','계약종류','string'],
    ['amount','계약금액','num'], ['client','거래처','string'], ['orgunit','계약자','string'],
    ['events','표시 중인 이벤트','string']
  ];
  const i18n = {add:'조건 추가',button:'상세필터',clearAll:'조건 초기화',condition:'연산자',data:'항목',
    deleteTitle:'조건 삭제',leftTitle:'그룹 밖으로',rightTitle:'그룹 만들기',logicAnd:'AND',logicOr:'OR',
    title:{0:'상세 조건',_:'상세 조건 (%d)'},value:'값',valueJoiner:'~',
    conditions:{string:{contains:'포함',empty:'값 없음',endsWith:'끝나는 값',equals:'같음',not:'다름',notContains:'포함하지 않음',notEmpty:'값 있음',notEndsWith:'끝나지 않는 값',notStartsWith:'시작하지 않는 값',startsWith:'시작하는 값'},
      number:{between:'범위',empty:'값 없음',equals:'같음',gt:'초과',gte:'이상',lt:'미만',lte:'이하',not:'다름',notBetween:'범위 밖',notEmpty:'값 있음'},
      date:{after:'이후',before:'이전',between:'기간',empty:'값 없음',equals:'같음',not:'다름',notBetween:'기간 밖',notEmpty:'값 있음'}}};
  function el(tag, cls, text) {const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n;}
  function button(text, cls='btn btn-outline-primary') {const b=el('button',cls,text);b.type='button';return b;}
  function money(v) {return v===null?'—':BigInt(v).toLocaleString('ko-KR')+'원';}
  class SavedFilterService {
    constructor(url,token){this.url=url;this.token=token;}
    async request(body) {
      const response=await fetch(this.url,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',
        headers:body?{'Content-Type':'application/json','X-CSRFToken':this.token}:{},body:body?JSON.stringify(body):undefined});
      if(!response.ok){let data;try{data=await response.json();}catch(_){}throw new Error(data?.error||'필터 저장·불러오기에 실패했습니다. 다시 시도하세요.');}
      return response.json();
    }
  }
  document.addEventListener('DOMContentLoaded',function(){
    const base=$('#datatables-contracts').DataTable(), panes=document.getElementById('contract-filter-panes');
    if(!panes)return;
    const error=document.getElementById('contract-filter-error');
    function fail(e){error.textContent=e.message||String(e);error.hidden=false;}
    const filterRow=document.getElementById('contract-column-search'), toggle=document.getElementById('contract-column-toggle');
    const search=base.table().container().querySelector('.dataTables_filter');
    if(search){search.classList.add('contract-search-tools');search.prepend(toggle);}
    base.columns().every(function(index){
      const column=this, input=el('input','form-control form-control-sm');
      const label=fields[index][1];input.type='search';input.placeholder=label;input.setAttribute('aria-label',label+' 검색');
      filterRow.children[index].appendChild(input);
      input.addEventListener('input',()=>column.search(input.value,false,true).draw());
      input.addEventListener('click',e=>e.stopPropagation());
    });
    toggle.addEventListener('click',()=>{filterRow.hidden=!filterRow.hidden;toggle.setAttribute('aria-expanded',String(!filterRow.hidden));base.columns.adjust();});
    // Read all already-authorized DOM rows, including pages and hidden old completions.
    // No additional download of contracts and no mutation of base filters.
    const rows=base.rows().nodes().toArray().map(tr=>{
      const row={id:tr.dataset.id,href:tr.dataset.href};
      fields.slice(0,9).forEach(([key],i)=>row[key]=tr.children[i].textContent.trim());
      row.amount=tr.dataset.amount;
      const stage=tr.children[2].querySelector('.gf-workflow-stage');
      row.statusClass=stage?.className||'badge bg-secondary';
      row.status=stage?.textContent.replace(/^✓\s*/, '').trim()||'';
      row.statusHtml=tr.children[2].innerHTML; // Authorized, escaped server markup; display only.
      row.events=tr.children[2].dataset.eventLabels||'';
      return row;
    });
    const service=new SavedFilterService(panes.dataset.savedUrl,panes.querySelector('[name=csrfmiddlewaretoken]').value);
    const tabs=document.getElementById('contract-filter-tabs'), basePane=document.getElementById('contract-base-pane'), baseTab=document.getElementById('contract-base-tab');
    const controllers=new Map();let sequence=0;
    function activate(id){
      basePane.hidden=id!=='base';baseTab.classList.toggle('active',id==='base');baseTab.setAttribute('aria-selected',String(id==='base'));
      toggle.hidden=id!=='base';
      for(const [key,c] of controllers){c.pane.hidden=key!==id;c.tab.classList.toggle('active',key===id);c.tab.setAttribute('aria-selected',String(key===id));if(key===id){c.table.columns.adjust();$(c.pane).find('.dtsb-group').first().trigger('dtsb-redrawLogic');}}
      if(id==='base')base.columns.adjust().responsive.recalc();
    }
    baseTab.addEventListener('click',()=>activate('base'));
    class AdvancedFilterController {
      constructor(){
        this.id='contract-filter-'+(++sequence);this.excluded=new Set();this.candidates=new Set();this.saved=null;this.ready=false;
        this.item=el('li','nav-item');this.item.setAttribute('role','presentation');
        this.tab=button('상세필터 '+sequence,'nav-link');this.tab.id=this.id+'-tab';this.tab.setAttribute('role','tab');this.tab.setAttribute('aria-controls',this.id);
        const close=button('×','btn btn-link px-2');close.setAttribute('aria-label','상세필터 '+sequence+' 닫기');
        this.item.append(this.tab,close);tabs.append(this.item);tabs.hidden=false;
        this.pane=el('section','card');this.pane.id=this.id;this.pane.setAttribute('role','tabpanel');this.pane.setAttribute('aria-labelledby',this.tab.id);
        const body=el('div','card-body');this.pane.append(body);panes.append(this.pane);
        const toolbar=el('div','d-flex flex-wrap gap-2 mb-3');
        this.name=el('input','form-control w-auto');this.name.maxLength=100;this.name.placeholder='필터 이름';this.name.setAttribute('aria-label','필터 이름');
        const save=button('필터조건 저장','btn btn-primary'),load=button('불러오기'),reset=button('초기화');
        this.savedSelect=el('select','form-select w-auto');this.savedSelect.setAttribute('aria-label','저장 필터');
        this.savedSelect.append(new Option('저장 필터 선택',''));
        toolbar.append(this.name,save,this.savedSelect,load,reset);body.append(toolbar);
        this.message=el('div','small mb-2');this.message.setAttribute('role','status');body.append(this.message);
        body.append(el('p','small text-muted','현재 목록에 조회된 계약 · 과거 완료 포함 · 기본 목록의 검색과 독립적입니다. 중지는 상태가 아닌 ‘표시 중인 이벤트’에서 검색하세요.'));
        const builder=el('div');body.append(builder);
        this.summary=el('div','filter-summary my-3');this.summary.setAttribute('aria-live','polite');body.append(this.summary);
        const wrap=el('div','filter-table-wrap');this.element=el('table','table table-striped table-hover w-100');wrap.append(this.element);body.append(wrap);
        const renderText=$.fn.dataTable.render.text();
        this.table=$(this.element).DataTable({data:rows,dom:'lrtip',deferRender:true,pageLength:10,lengthMenu:[10,25,50],order:[[1,'desc']],
          language:{search:'검색',lengthMenu:'_MENU_개씩 보기',info:'총 _TOTAL_개 중 _START_–_END_',infoEmpty:'결과 없음',infoFiltered:'(조회된 _MAX_건에서 검색)',zeroRecords:'일치하는 계약이 없습니다',emptyTable:'조회된 계약이 없습니다',paginate:{next:'다음',previous:'이전'}},
          columns:[{data:null,title:'선택',orderable:false,searchable:false,defaultContent:'',render:()=>'<input type="checkbox" class="form-check-input filter-include">'},
            ...fields.map(([key,title,type])=>({data:key,title,type,visible:key!=='events',searchBuilderType:type,
              render:(value,mode,row)=>{
                if(mode!=='display')return value;
                if(key==='name'){const a=el('a',null,value);a.href=row.href;return a.outerHTML;}
                if(key==='status')return row.statusHtml;
                if(key==='amount')return value===''?'—':money(value);
                return renderText.display(value);
              }}))],
          searchBuilder:{columns:fields.map((_,i)=>i+1),depthLimit:4,i18n,orthogonal:{display:'filter',search:'filter'}}});
        $(builder).append(this.table.searchBuilder.container());
        this.all=el('input','form-check-input');this.all.type='checkbox';this.all.setAttribute('aria-label','검색 결과 전체 포함 또는 제외');
        this.element.querySelector('thead th').replaceChildren(this.all);
        this.all.addEventListener('change',()=>{for(const id of this.candidates)this.all.checked?this.excluded.delete(id):this.excluded.add(id);this.update();});
        this.element.addEventListener('change',e=>{if(!e.target.matches('.filter-include'))return;const row=this.table.row(e.target.closest('tr')).data();e.target.checked?this.excluded.delete(row.id):this.excluded.add(row.id);this.update();});
        this.table.on('draw.dt',()=>{if(this.ready)this.update();});
        this.tab.addEventListener('click',()=>activate(this.id));
        close.addEventListener('click',()=>{
          if(this.dirty()&&!confirm('저장하지 않은 필터입니다. 닫으시겠습니까?'))return;
          this.table.destroy();this.pane.remove();this.item.remove();controllers.delete(this.id);activate('base');tabs.hidden=controllers.size===0;
        });
        save.addEventListener('click',async()=>{
          save.disabled=true;this.message.textContent='저장 중…';
          try{
            if(!this.name.value.trim())throw new Error('필터 이름을 입력하세요.');
            const definition=this.definition();
            const existing=this.savedFilters?.find(f=>f.name===this.name.value.trim());
            if(existing&&!confirm('같은 이름의 필터를 덮어쓰시겠습니까?')){this.message.textContent='저장을 취소했습니다.';return;}
            const result=await service.request({name:this.name.value.trim(),definition});
            this.tab.textContent=result.name;this.saved=JSON.stringify({name:result.name,definition});this.name.value=result.name;
            this.message.textContent='저장했습니다.';await this.refreshSaved();
          }catch(e){this.message.textContent=e.message;}finally{save.disabled=false;}
        });
        load.addEventListener('click',()=>{
          const selected=this.savedFilters?.find(f=>f.id===this.savedSelect.value);
          if(!selected){this.message.textContent='저장 필터를 선택하세요.';return;}
          if(this.dirty()&&!confirm('현재 조건을 저장된 필터로 바꾸시겠습니까?'))return;
          this.excluded.clear();this.table.searchBuilder.rebuild(selected.definition.conditions);this.table.order(selected.definition.order).draw();
          this.name.value=selected.name;this.tab.textContent=selected.name;this.saved=JSON.stringify({name:selected.name,definition:this.definition()});this.message.textContent='불러왔습니다.';
        });
        reset.addEventListener('click',()=>{if(!confirm('이 탭의 조건과 선택을 초기화하시겠습니까?'))return;this.excluded.clear();this.table.searchBuilder.rebuild({});this.table.order([[1,'desc']]).draw();});
        this.ready=true;this.update();this.refreshSaved();
      }
      definition(){return {version:1,conditions:this.table.searchBuilder.getDetails(),order:this.table.order().map(x=>[x[0],x[1]])};}
      dirty(){const d=this.definition();return this.saved?this.saved!==JSON.stringify({name:this.name.value.trim(),definition:d}):Boolean(this.name.value||d.conditions.criteria?.length||JSON.stringify(d.order)!=='[[1,"desc"]]');}
      async refreshSaved(){try{const data=await service.request();this.savedFilters=data.filters;this.savedSelect.replaceChildren(new Option('저장 필터 선택',''));for(const f of data.filters)this.savedSelect.append(new Option(f.name,f.id));}catch(e){this.message.textContent=e.message;}}
      update(){
        const candidates=this.table.rows({search:'applied'}).data().toArray(), next=new Set(candidates.map(r=>r.id));
        // Rows that leave the result cease to be selected; on re-entry they are new.
        for(const id of this.excluded)if(!next.has(id))this.excluded.delete(id);
        this.candidates=next;
        const included=candidates.filter(r=>!this.excluded.has(r.id)), result=GeoFlowAggregate.calculate(included);
        this.summary.replaceChildren(el('span',null,'선택 '+result.count+'건 / 결과 '+candidates.length+'건'),el('strong',null,'합계 '+money(result.sum)),el('span',null,'평균 '+money(result.average)));
        if(result.missing)this.summary.append(el('span','text-muted','금액 미등록 '+result.missing+'건 · 평균 제외'));
        this.all.checked=next.size>0&&included.length===next.size;this.all.indeterminate=included.length>0&&included.length<next.size;
        const thisController=this;
        this.table.rows({page:'current'}).every(function(){const row=this.data(),box=this.node()?.querySelector('.filter-include');if(box){box.checked=!thisController.excluded.has(row.id);box.setAttribute('aria-label',row.code+' '+row.name+' 계산 포함');}});
      }
    }
    document.getElementById('contract-advanced-add').addEventListener('click',()=>{
      error.hidden=true;
      if(!$.fn.dataTable.SearchBuilder){fail(new Error('상세필터 구성요소를 불러오지 못했습니다. 새로고침하세요.'));return;}
      if(rows.length>5000){fail(new Error('상세필터는 현재 조회된 계약 5,000건까지 지원합니다. 더 큰 데이터는 서버 검색 전환이 필요합니다.'));return;}
      const c=new AdvancedFilterController();controllers.set(c.id,c);activate(c.id);
    });
  });
})();
