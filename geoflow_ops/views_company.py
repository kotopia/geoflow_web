"""Company overview and deliberately separate editing surface."""
from uuid import UUID
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .services.company_overview import company_documents, document_history
from .services.company_references import reference_groups
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from control.gf_authz.permissions import gf_has_perm
from .models import MyOrgUnit, ProcessEvent
from .company_models import CompanyProfile, CompanyRegistration, CompanyRevenue, CompanyHeadcount, CompanyCredit, CompanyEvidence
from .company_forms import ProfileForm, RegistrationForm, RevenueForm, HeadcountForm, CreditForm, CompanyEventForm
from .forms import MyOrgUnitForm
from .services.company_overview import enabled, current_headcount, annual_series, validate_parent, sync_source_event, validate_evidence, replace_evidence, evidence_candidates, record_evidence, EVIDENCE_PURPOSE
from .services.entity_access import require_tenant_context, authorize_scope_read, authorize_scope_write, can_read_event
from .services.finance_access import can_view_finance, can_edit_finance
from .views_events import EVENT_TIMELINE_ORDER

RECORDS = {'registration':(CompanyRegistration,RegistrationForm,'업등록·신고·인증'), 'revenue':(CompanyRevenue,RevenueForm,'연도별 매출'), 'headcount':(CompanyHeadcount,HeadcountForm,'과거 연말 사원수'), 'credit':(CompanyCredit,CreditForm,'신용평가')}


def access(request, pk=None, *, write=False):
    alias = require_tenant_context(request)
    if not enabled(alias):
        raise Http404
    if not gf_has_perm(request, 'directory.edit' if write else 'directory.view'):
        raise PermissionDenied
    obj = get_object_or_404(MyOrgUnit.objects.using(alias), pk=pk) if pk else None
    if obj and not (authorize_scope_write if write else authorize_scope_read)(request, alias, 'orgunit', obj.pk):
        raise PermissionDenied
    return alias, obj


@never_cache
@login_required
@require_http_methods(['GET'])
def home(request):
    alias, _ = access(request)
    companies = MyOrgUnit.objects.using(alias).order_by('name','id')
    key = 'company_overview:' + alias
    last = request.session.get(key)
    try:
        last = UUID(str(last)) if last else None
    except ValueError:
        last = None
    company = companies.filter(pk=last).first() if last else None
    if company is None:
        primary = CompanyProfile.objects.using(alias).filter(is_primary=True).values_list('company_id',flat=True).first()
        company = companies.filter(pk=primary).first() if primary else companies.first()
    if company:
        return redirect('tenant:myinfo_orgunit_detail', pk=company.pk)
    return render(request, 'geoflow_ops/myinfo/orgunit_list.html', {'items':companies})


@never_cache
@login_required
@require_http_methods(['GET'])
def overview(request, pk):
    alias, obj = access(request, pk)
    request.session['company_overview:' + alias] = str(obj.pk)
    try:
        years = int(request.GET.get('years', 5))
    except (ValueError, TypeError):
        years = 5
    if years not in (3,5,10):
        years = 5
    finance = can_view_finance(request)
    profile = CompanyProfile.objects.using(alias).filter(company_id=pk).select_related('parent').first()
    today = timezone.localdate()
    credit = CompanyCredit.objects.using(alias).filter(company_id=pk, representative=True).first()
    latest_revenue = CompanyRevenue.objects.using(alias).filter(company_id=pk, confirmed=True).order_by('-year').first() if finance else None
    events = ProcessEvent.objects.using(alias).filter(scope_type='orgunit',scope_id=pk).exclude(status='void').order_by(*EVENT_TIMELINE_ORDER)
    # Permission filtering happens before pagination; Finance events remain protected.
    events = [e for e in events if can_read_event(request, alias, e)]
    try:
        page = max(1,int(request.GET.get('page',1)))
    except (TypeError,ValueError):
        page = 1
    page = min(page, max(1,(len(events)+9)//10))
    context = {
        'obj':obj, 'profile':profile, 'companies':MyOrgUnit.objects.using(alias).order_by('name','id'),
        'can_edit':gf_has_perm(request,'directory.edit'), 'finance':finance, 'finance_edit':can_edit_finance(request),
        'headcount':current_headcount(alias,pk), 'revenue':latest_revenue, 'credit':credit,
        'revenue_summary':format(latest_revenue.amount / 100000000, '.2f') if latest_revenue else None,
        'credit_expired':bool(credit and credit.expires_on and credit.expires_on < today),
        'series':annual_series(alias,pk,years,finance=finance), 'years':years,
        'events':events[(page-1)*10:page*10], 'previous_page':page-1 if page>1 else None, 'next_page':page+1 if len(events)>page*10 else None,
        'today':today,
    }
    return workspace(request, alias, obj, context)


def workspace(request, alias, obj, context):
    section = request.GET.get('section','overview')
    if section not in {'overview','basic','documents','performance','organization','references'}:
        raise Http404
    context['section'] = section
    docs = company_documents(alias,obj.pk,finance=context['finance'])
    context.update(documents=docs,current_documents=[d for d in docs if not d['previous']],
                   due_count=sum(d['due'] for d in docs),document_count=sum(d['active'] for d in docs))
    from .services.employee_access import employee_access_policy
    context['can_manage_settings'] = employee_access_policy(request,alias).can_manage_settings
    if section == 'documents':
        group = request.GET.get('group','all')
        if group not in {'all','registration','certification','credit'}:
            group = 'all'
        search = request.GET.get('q','').strip()[:200]
        history = request.GET.get('history') == '1'
        context.update(document_group=group,search=search,show_history=history,
            filtered_documents=[d for d in docs if (history or not d['previous']) and
                (group=='all' or d['group']==group) and
                (not search or search.casefold() in (d['name']+' '+d['issuer']).casefold())])
    record_id = request.GET.get('record')
    if record_id:
        kind = request.GET.get('kind','registration')
        if kind not in RECORDS:
            raise Http404
        if kind in {'credit','revenue'} and not context['finance']:
            raise PermissionDenied
        try:
            record_id = UUID(record_id)
        except ValueError:
            raise Http404
        record = get_object_or_404(RECORDS[kind][0].objects.using(alias),company_id=obj.pk,pk=record_id)
        detail_form = RECORDS[kind][1](instance=record)
        fields = []
        for field in detail_form:
            if field.name == 'items':
                continue
            value = getattr(record, 'get_'+field.name+'_display',lambda: getattr(record,field.name))()
            if isinstance(value,bool): value = '예' if value else '아니오'
            fields.append((field.label, value))
        selected = next((d for d in docs if d['kind']==kind and d['id']==record.pk),None)
        context.update(detail_record=record,detail_kind=kind,detail_fields=fields,
            detail_evidence=record_evidence(alias,obj.pk,kind,record.pk),
            detail_title=selected['name'] if selected else RECORDS[kind][2],
            detail_history=document_history(docs,selected) if selected else [],
            detail_can_renew=bool(selected and not selected['previous']),
            detail_can_edit=context['can_edit'] and (kind not in {'credit','revenue'} or context['finance_edit']))
    if section == 'performance':
        context['revenues'] = CompanyRevenue.objects.using(alias).filter(company_id=obj.pk).order_by('-year') if context['finance'] else []
        context['headcounts'] = CompanyHeadcount.objects.using(alias).filter(company_id=obj.pk).order_by('-year')
    if section == 'organization':
        from .views_myinfo import _load_departments, _load_master
        context.update(departments=_load_departments(alias,obj.pk),job_grades=_load_master(alias,'position_grade'),job_positions=_load_master(alias,'position_title'))
    if section == 'references':
        context['reference_groups'] = reference_groups(alias)
    return render(request,'geoflow_ops/myinfo/company_overview.html',context)


def _forms_context(alias, obj, kind, form, record, request):
    from .views_myinfo import _load_departments, _load_master, _load_company_documents
    context = {'obj':obj,'kind':kind,'form':form,'record':record,'finance_edit':can_edit_finance(request), 'finance':can_view_finance(request)}
    if kind in RECORDS:
        context['heading'] = RECORDS[kind][2]
        context['purpose'] = EVIDENCE_PURPOSE[kind]
        candidates = list(evidence_candidates(alias,obj.pk,kind))
        context['selected_attachments'] = [str(v) for v in CompanyEvidence.objects.using(alias).filter(company_id=obj.pk,record_kind=kind,record_id=record.pk).values_list('attachment_id',flat=True)] if record else []
        if request.method == 'POST':
            context['selected_attachments'] = request.POST.getlist('evidence')
        context['attachments'] = [a for a in candidates if str(a.pk) in context['selected_attachments']]
        context['available_attachments'] = [a for a in candidates if str(a.pk) not in context['selected_attachments']]
    if kind == 'organization':
        context.update(departments=_load_departments(alias,obj.pk), job_grades=_load_master(alias,'position_grade'), job_positions=_load_master(alias,'position_title'))
    if kind == 'documents':
        context.update(business_documents=_load_company_documents(alias,obj.pk,'business_registration'), certification_documents=_load_company_documents(alias,obj.pk,'certification_evaluation'))
    return context


@never_cache
@login_required
@require_http_methods(['GET','POST'])
def edit(request, pk):
    alias, obj = access(request,pk,write=True)
    kind = request.GET.get('section','basic')
    if kind not in {*RECORDS,'basic','organization','documents','event'}:
        raise Http404
    if kind in {'revenue','credit'} and not can_edit_finance(request):
        raise PermissionDenied
    if request.method == 'GET' and kind in RECORDS and not request.GET.get('record') and request.GET.get('new') != '1':
        section = 'performance' if kind in {'revenue','headcount'} else 'documents'
        return redirect(reverse('tenant:myinfo_orgunit_detail',args=[pk])+'?section='+section)
    data = request.POST if request.method == 'POST' else None
    record = None
    original_status = None
    if kind == 'basic':
        profile = CompanyProfile.objects.using(alias).filter(company_id=pk).first() or CompanyProfile(company_id=pk)
        form = MyOrgUnitForm(data,instance=obj)
        from django.forms import HiddenInput
        form.fields['type'].widget = HiddenInput()
        extra = ProfileForm(data,instance=profile,alias=alias)
    elif kind in RECORDS:
        model, form_class, _ = RECORDS[kind]
        record_id = request.GET.get('record')
        if record_id:
            try:
                record_id = UUID(record_id)
            except ValueError:
                raise Http404
            record = get_object_or_404(model.objects.using(alias),company_id=pk,pk=record_id)
        if request.GET.get('renew') == '1' and kind in {'registration','credit'} and record:
            previous = record
            if kind == 'registration':
                record = model(company_id=pk, previous_id=previous.pk, name=previous.name,kind=previous.kind,issuer=previous.issuer,occurred_on=previous.occurred_on,items=previous.items)
            else:
                record = model(company_id=pk, previous_id=previous.pk, agency=previous.agency,rating_type=previous.rating_type,representative=previous.representative)
        original_status = record.status if kind == 'registration' and record and not record._state.adding else None
        form = form_class(data,instance=record or model(company_id=pk),alias=alias)
    elif kind == 'event':
        record_id = request.GET.get('record')
        if record_id:
            try:
                record_id = UUID(record_id)
            except ValueError:
                raise Http404
            record = get_object_or_404(ProcessEvent.objects.using(alias),pk=record_id,scope_type='orgunit',scope_id=pk,event_type='company_manual')
            if record.payload.get('company_source_id'):
                raise PermissionDenied
        form = CompanyEventForm(data, initial={'title':record.title,'occurred_at':record.occurred_at,'memo':record.memo} if record else None)
    else:
        form = None
    if form is not None and hasattr(form, 'instance'):
        form.instance._state.db = alias
    if kind == 'basic':
        extra.instance._state.db = alias
    if data is not None and form is not None:
        valid = form.is_valid()
        if kind == 'basic':
            valid = extra.is_valid() and valid
        if valid:
            try:
                with transaction.atomic(using=alias):
                    # Serialize facts and representative selections per company, including duplicate POSTs.
                    if kind != 'basic':
                        MyOrgUnit.objects.using(alias).select_for_update().get(pk=pk)
                    if kind == 'basic':
                        # Lock all identities for parent-cycle/default-company concurrency checks.
                        list(MyOrgUnit.objects.using(alias).select_for_update().order_by('id').values_list('id',flat=True))
                        parent = request.POST.get('parent')
                        try:
                            parent = UUID(parent) if parent else None
                        except ValueError:
                            raise ValidationError('상위 기업을 확인하세요.')
                        validate_parent(alias,pk,parent,extra.cleaned_data['node_kind'])
                        updated = extra.save(commit=False)
                        updated.parent_id = parent
                        if updated.is_primary:
                            CompanyProfile.objects.using(alias).exclude(company_id=pk).filter(is_primary=True).update(is_primary=False)
                        form.save(commit=False).save(using=alias)
                        updated.save(using=alias)
                    elif kind == 'event':
                        event = record or ProcessEvent(scope_type='orgunit',scope_id=pk,stage='company',event_type='company_manual',created_by=str(request.user.pk),status='done')
                        for key,value in form.cleaned_data.items():
                            setattr(event,key,value)
                        event.save(using=alias)
                    else:
                        fact = form.save(commit=False)
                        if kind in {'revenue','headcount'}:
                            other = RECORDS[kind][0].objects.using(alias).filter(company_id=pk,year=fact.year).exclude(pk=fact.pk)
                            if other.exists():
                                raise ValidationError('해당 연도의 자료가 있습니다. 기존 항목을 수정하세요.')
                        if kind in {'registration','credit'} and fact.previous_id and fact._state.adding:
                            if RECORDS[kind][0].objects.using(alias).filter(previous_id=fact.previous_id).exists():
                                raise ValidationError('이미 갱신된 이력입니다. 가장 최근 이력에서 갱신하세요.')
                            previous = RECORDS[kind][0].objects.using(alias).get(pk=fact.previous_id,company_id=pk)
                            if kind == 'credit' and fact.evaluated_on < previous.evaluated_on:
                                raise ValidationError('갱신 평가일은 이전 평가일 이후여야 합니다.')
                            if kind == 'registration' and (not fact.issued_on or fact.issued_on < (previous.issued_on or previous.occurred_on)):
                                raise ValidationError('갱신 발급일은 이전 발급일 이후로 입력하세요.')
                        if kind == 'registration':
                            if original_status and original_status != fact.status and 'cancelled' in {original_status, fact.status}:
                                raise ValidationError('취소·재등록은 갱신·취소 이력 추가에서 발생일과 함께 새 이력으로 등록하세요.')
                            if fact.previous_id and fact._state.adding:
                                if fact.occurred_on != previous.occurred_on:
                                    raise ValidationError('최초 등록일은 유지하고 갱신 발급일을 별도로 입력하세요.')
                        ids = validate_evidence(alias,pk,kind,request.POST.getlist('evidence'))
                        if kind == 'credit' and fact.representative:
                            CompanyCredit.objects.using(alias).filter(company_id=pk,representative=True).exclude(pk=fact.pk).update(representative=False)
                        fact.save(using=alias)
                        sync_source_event(alias,fact,kind,str(request.user.pk))
                        replace_evidence(alias,fact,kind,ids)
                messages.success(request,'기업정보를 저장했습니다.')
                destination = reverse('tenant:myinfo_orgunit_detail',args=[pk])
                if kind in RECORDS:
                    section = 'performance' if kind in {'revenue','headcount'} else 'documents'
                    destination += f'?section={section}&kind={kind}&record={fact.pk}'
                elif kind == 'basic':
                    destination += '?section=basic'
                return redirect(destination)
            except ValidationError as exc:
                form.add_error(None,exc)
    context = _forms_context(alias,obj,kind,form,record,request)
    context['is_renewal'] = request.GET.get('renew') == '1'
    context['return_section'] = 'performance' if kind in {'revenue','headcount'} else 'documents' if kind in {'registration','credit'} else 'basic'
    if kind == 'basic':
        context.update(profile_form=extra, parent_id=str(profile.parent_id or ''), companies=MyOrgUnit.objects.using(alias).exclude(pk=pk).order_by('name'))
        if data is not None:
            context['parent_id'] = request.POST.get('parent','')
    if kind == 'event':
        context['events'] = ProcessEvent.objects.using(alias).filter(scope_type='orgunit',scope_id=pk,event_type='company_manual').order_by(*EVENT_TIMELINE_ORDER)
    return render(request,'geoflow_ops/myinfo/company_edit.html',context)
