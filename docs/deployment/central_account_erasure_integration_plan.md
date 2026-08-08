# Central account erasure integration plan

Status: prepared design only. No repository, database, or server action has been performed.

## Why the existing delete view must change

The existing administrator delete path removes membership, join requests and legacy password-reset tokens before deleting `users`, but it predates the signup request/event/token/outbox FK chain. Once the signup schema is present, direct hard deletion can be blocked by RESTRICT references.

## Prepared integration

Replace only the destructive SQL body of `users_delete_admin` with a call to `erase_central_account_personal_data(user_id)`. Keep the existing POST-only + CSRF + staff authorization boundary.

Expected public/operator behavior:

1. GET/non-POST remains rejected.
2. Missing user produces a generic operator-facing error.
3. The service removes the user's own signup dependencies, membership, join requests and reset-token artifacts transactionally.
4. If the account still owns a group, erasure stops and requires explicit ownership transfer first.
5. If no other applicant's audit history references the user, the service attempts a central hard delete.
6. If the user is an approver/audit actor for another applicant, or an unexpected central FK blocks hard deletion, the central identity row is irreversibly anonymized instead so referential integrity remains valid.
7. Success UI must not echo the deleted email address.
8. The operation does not touch tenant DBs. Tenant operational/personnel data requires a separate tenant-scoped retention decision.

## Proposed view-level replacement logic

```python
from .services.central_account_erasure_service import (
    AccountErasureError,
    erase_central_account_personal_data,
)

@require_staff
@csrf_protect
def users_delete_admin(request, user_id):
    if request.method != "POST":
        messages.error(request, "잘못된 접근입니다.")
        return redirect("control:users_detail_admin", user_id=user_id)

    try:
        result = erase_central_account_personal_data(str(user_id))
    except AccountErasureError:
        messages.error(request, "사용자 개인정보 삭제를 완료할 수 없습니다. 연관 데이터 상태를 확인하세요.")
        return redirect("control:users_detail_admin", user_id=user_id)

    if result.mode == "anonymized":
        messages.success(request, "사용자 계정 개인정보가 삭제되고 감사 이력용 식별자는 익명화되었습니다.")
    else:
        messages.success(request, "사용자 계정 개인정보가 삭제되었습니다.")
    return redirect("users_list_admin")
```

Before applying this integration, verify actual central DB foreign-key dependencies in a non-production environment. Do not infer that central-account erasure also authorizes deletion of tenant business records.
