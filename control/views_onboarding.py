# control/views_onboarding.py (새 파일 또는 views_auth.py 하단)
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required
def no_tenant_view(request):
    """
    활성 멤버십이 없는 사용자가 보게 되는 안내 페이지.
    - 그룹 검색/합류요청 링크
    - 내 요청 현황
    - 로그아웃 유도
    """
    return render(request, "control/no_tenant.html")
