import os
import psycopg2
import bcrypt

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, Http404
from django.conf import settings
from django.db import connections
from pathlib import Path
from django.views.decorators.http import require_http_methods
from django.utils.dateparse import parse_date
from django.contrib import messages
from django.db.models import Q
from django.views.generic import ListView, UpdateView
from django.urls import reverse, reverse_lazy
from datetime import date
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model, login
from django.views.decorators.csrf import csrf_exempt


# sslrootcert_path = os.path.join(settings.BASE_DIR, 'rds-combined-ca-bundle.pem')


# def _ensure_group_connection(request):
#     """
#     세션: group_id(UUID), db_key(db_alias) 사용.
#     db_alias가 settings.DATABASES에 없으면 동적 추가 후 반환.
#     """
#     db_key = request.session.get('db_key')          # = db_alias
#     group_id = request.session.get('group_id')      # = UUID 문자열
#     if not group_id:
#         return None

#     # 이미 세션에 db_key가 있으면 그대로 사용 가능
#     if db_key and db_key in connections.databases:
#         return db_key

#     # 중앙DB에서 조회
#     with connections['default'].cursor() as cur:
#         cur.execute("""
#             SELECT db_alias, db_name, db_host, db_port, db_user, db_password
#             FROM group_db_config
#             WHERE group_id = %s
#             LIMIT 1
#         """, [str(group_id)])
#         row = cur.fetchone()

#     if not row:
#         return None

#     db_alias, db_name, db_host, db_port, db_user, db_password = row
#     cfg = {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': db_name,
#         'USER': db_user,
#         'PASSWORD': db_password,
#         'HOST': db_host,
#         'PORT': db_port,
#         'OPTIONS': {
#             'sslmode': 'verify-full',
#             'sslrootcert': sslrootcert_path,
#         },
#         'ATOMIC_REQUESTS': False,
#         'TIME_ZONE': settings.TIME_ZONE if settings.USE_TZ else None,
#         'CONN_MAX_AGE': 0,
#         'CONN_HEALTH_CHECKS': False,
#         'AUTOCOMMIT': True,
#     }

#     # 이미 settings.DATABASES에 있으면 재사용
#     if db_alias in connections.databases:
#         request.session['db_key'] = db_alias
#         return db_alias

#     settings.DATABASES[db_alias] = cfg
#     connections.databases[db_alias] = cfg
#     request.session['db_key'] = db_alias
#     return db_alias

# # 홈 화면
# # =====================================================================================
def home(request):
    # 중앙이면 테넌트 홈 안 봄
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    if request.session.get("tenant_db_alias") == central_alias:
        return redirect("control:dashboard")

    # 테넌트 세션 없으면 중앙으로 (선호 정책에 맞게)
    if not request.session.get("group_id"):
        return redirect("control:dashboard")  # 또는 redirect("control:no_tenant")

    return render(request, "geoflow_ops/home.html")

# # Constracs
# # =====================================================================================
# from .models import Contract
# from .forms import ContractForm

# def contract_list(request):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return redirect('login')
#     contracts = Contract.objects.using(db_key).all()
#     return render(request, 'geoflow_ops/contract_list.html', {'contracts': contracts})


# # ---- 계약 상세/저장 ----
# def contract_detail_page(request, pk):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return redirect('login')

#     obj = get_object_or_404(Contract.objects.using(db_key), pk=pk)

#     # 새 모델에 맞게: FK는 이미 Partner 인스턴스임
#     client_name = obj.client.name if obj.client else None
#     subclient_name = obj.sub_client.name if obj.sub_client else None

#     if request.method == "POST":
#         form = ContractForm(request.POST, instance=obj)
#         if form.is_valid():
#             inst = form.save(commit=False)
#             inst.save(using=db_key)
#             messages.success(request, "저장했습니다.")
#             return redirect("contract_detail", pk=obj.pk)

#         return render(
#             request,
#             "geoflow_ops/contracts/contract_detail.html",
#             {
#                 "obj": obj,
#                 "client_name": client_name or "-",
#                 "subclient_name": subclient_name or "-",
#                 "edit_mode": True,
#                 "form": form,
#             },
#         )

#     edit_mode = request.GET.get("edit") == "1"
#     return render(
#         request,
#         "geoflow_ops/contracts/contract_detail.html",
#         {
#             "obj": obj,
#             "client_name": client_name or "-",
#             "subclient_name": subclient_name or "-",
#             "edit_mode": edit_mode,
#         },
#     )


# # ---- 계약 JSON ----
# def contract_detail_json(request, pk):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return JsonResponse({'error': '로그인 필요'}, status=401)
#     obj = get_object_or_404(Contract.objects.using(db_key), pk=pk)
#     data = {
#         "id": str(obj.id),
#         "code": obj.code,          # old: contract_code
#         "name": obj.name,          # old: contract_name
#         "start_date": obj.start_date.isoformat() if obj.start_date else None,
#         "end_date": obj.end_date.isoformat() if obj.end_date else None,
#         "amount": obj.amount,
#         "status": obj.status,
#         "kind": obj.kind,
#         "division": obj.division,
#         "client_id": str(obj.client.id) if obj.client else None,
#         "sub_client_id": str(obj.sub_client.id) if obj.sub_client else None,
#     }
#     return JsonResponse(data)

# @require_POST
# def contract_create(request):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return redirect("login")

#     form = ContractForm(request.POST)
#     if form.is_valid():
#         obj = form.save(commit=False)  # ← 폼은 commit=False
#         obj.save(using=db_key)         # ← 여기에서만 using 사용!
#         messages.success(request, "계약을 생성했습니다.")
#         return redirect("contract_detail", pk=obj.id)

#     # 유효성 오류 → 편집모드로 다시 렌더
#     return render(
#         request,
#         "geoflow_ops/contracts/contract_detail.html",
#         {"obj": form.instance, "form": form, "edit_mode": True},
#     )


# # Partner
# # =====================================================================================
# from .models import Partner
# from .forms import PartnerForm

# def partner_list(request):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return redirect('login')
#     qs = Partner.objects.using(db_key).all()
#     return render(request, 'geoflow_ops/contracts/partner_list.html', {'partners': qs})

# def partner_detail_page(request, pk):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return redirect('login')
#     obj = get_object_or_404(Partner.objects.using(db_key), pk=pk)

#     if request.method == "POST":
#         form = PartnerForm(request.POST, instance=obj)
#         if form.is_valid():
#             inst = form.save(commit=False)
#             inst.save(using=db_key)
#             messages.success(request, "저장했습니다.")
#             return redirect("partner_detail", pk=obj.pk)
#         return render(
#             request, "geoflow_ops/contracts/partner_detail.html",
#             {"obj": obj, "form": form, "edit_mode": True}
#         )

#     edit_mode = request.GET.get("edit") == "1"
#     return render(
#         request, "geoflow_ops/contracts/partner_detail.html",
#         {"obj": obj, "edit_mode": edit_mode}
#     )


# def partner_detail_json(request, pk):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return JsonResponse({'error': '로그인 필요'}, status=401)
#     obj = get_object_or_404(Partner.objects.using(db_key), pk=pk)
#     data = {
#         "id": str(obj.id),
#         "name": obj.name,              # old: partner_name
#         "type": obj.type,              # old: partner_type
#         "biz_no": obj.biz_no,
#         "rep_name": obj.rep_name,
#         "address": obj.address,
#         "status": obj.status,
#         "description": obj.description,
#         "phone": obj.phone,
#         "email": obj.email,
#     }
#     return JsonResponse(data)


# def partner_options(request):
#     db_key = _ensure_group_connection(request)
#     if not db_key:
#         return JsonResponse({'error': '로그인 필요'}, status=401)

#     q = request.GET.get('q', '').strip()
#     limit = int(request.GET.get('limit', 500))
#     qs = Partner.objects.using(db_key).all().order_by('name')   # old: partner_name

#     if q:
#         qs = qs.filter(
#             Q(name__icontains=q) |       # old: partner_name
#             Q(biz_no__icontains=q) |
#             Q(rep_name__icontains=q)
#         )

#     qs = qs[:limit]
#     data = [
#         {
#             "value": str(p.id),
#             "label": f"{p.name}" if p.type else p.name
#         }
#         for p in qs
#     ]
#     return JsonResponse(data, safe=False)



# # Django에서 로그인된 그룹 DB로 접속해서 데이터 가져오기
# # =====================================================================================
# from .models import Project
# from .forms import ProjectForm

# # views.py

# def tenant_alias(request):
#     db_key = _ensure_group_connection(request)
#     return db_key or "default"


# class ProjectListView(ListView):
#     model = Project
#     template_name = "geoflow_ops/projects/project_list.html"
#     context_object_name = "projects"
#     paginate_by = 20

#     def get_queryset(self):
#         # old: .with_contract().ordered()
#         return (
#             Project.objects
#             .using(tenant_alias(self.request))
#             .select_related("contract")
#             .order_by("created_at")
#         )


# # pk는 UUID이므로 int 힌트 제거
# def project_detail_json(request, pk):
#     alias = tenant_alias(request)
#     obj = get_object_or_404(
#         Project.objects.using(alias).select_related("contract"),
#         pk=pk
#     )
#     return JsonResponse({
#         "id": str(obj.pk),
#         "code": obj.code,                       # old: project_1
#         "name": obj.name,
#         "status": obj.status,
#         "contract_code": obj.contract.code if obj.contract else None,  # old: contract_code
#         "contract_name": obj.contract.name if obj.contract else None,  # old: contract_name
#         "start_date": obj.start_date.strftime("%Y-%m-%d") if obj.start_date else None,
#         "end_date": obj.end_date.strftime("%Y-%m-%d") if obj.end_date else None,
#     })


# def project_detail_page(request, pk):
#     alias = tenant_alias(request)
#     obj = get_object_or_404(
#         Project.objects.using(alias).select_related("contract"),
#         pk=pk
#     )

#     if request.method == "POST":
#         form = ProjectForm(request.POST, instance=obj)
#         if form.is_valid():
#             inst = form.save(commit=False)
#             inst.save(using=alias)
#             messages.success(request, "저장했습니다.")
#             return redirect("project_detail", pk=obj.pk)
#         else:
#             return render(
#                 request,
#                 "geoflow_ops/projects/project_detail.html",
#                 {"obj": obj, "errors": sum(form.errors.values(), []), "edit_mode": True}
#             )

#     return render(request, "geoflow_ops/projects/project_detail.html", {"obj": obj})
