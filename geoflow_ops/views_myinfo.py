# geoflow_ops/views_myinfo.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages

from geoflow_ops.models import MyOrgUnit
from geoflow_ops.forms import MyOrgUnitForm
from geoflow_ops.views_contracts import _alias  # 이미 있는 헬퍼 재사용

@login_required
def orgunit_list(request):
    alias = _alias(request)
    qs = MyOrgUnit.objects.using(alias).all().order_by("name")
    return render(request, "geoflow_ops/myinfo/orgunit_list.html", {"items": qs})


@login_required
def orgunit_detail(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(MyOrgUnit.objects.using(alias), pk=pk)
    return render(request, "geoflow_ops/myinfo/orgunit_detail.html", {"obj": obj})


@login_required
def orgunit_create(request):
    alias = _alias(request)
    if request.method == "POST":
        form = MyOrgUnitForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.save(using=alias)             # 🔹 테넌트 DB에 저장
            messages.success(request, "회사 정보를 추가했습니다.")
            return redirect("tenant:myinfo_orgunit_detail", pk=obj.pk)
    else:
        form = MyOrgUnitForm()

    return render(
        request,
        "geoflow_ops/myinfo/orgunit_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def orgunit_update(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(MyOrgUnit.objects.using(alias), pk=pk)

    if request.method == "POST":
        form = MyOrgUnitForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.save(using=alias)             # 🔹 같은 테넌트 DB에 업데이트
            messages.success(request, "회사 정보를 수정했습니다.")
            return redirect("tenant:myinfo_orgunit_detail", pk=obj.pk)
    else:
        form = MyOrgUnitForm(instance=obj)

    return render(
        request,
        "geoflow_ops/myinfo/orgunit_form.html",
        {"form": form, "mode": "edit", "obj": obj},
    )
