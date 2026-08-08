# Central account erasure integration plan

Status: code-prepared integration; no database, migration, server, or destructive runtime action has been performed.

## Purpose

The legacy central administrator delete path predates the Phase 1 signup request/event/token/outbox FK chain. Directly deleting `users` can therefore fail or leave policy-inconsistent records after the signup schema is applied.

The prepared integration delegates central identity cleanup to `erase_central_account_personal_data(user_id)` while keeping the existing administrator-only, POST-only and CSRF-protected boundary.

## Prepared behavior

1. Non-POST requests are rejected/redirected.
2. Missing users and unsafe dependency states fail closed with a generic operator message.
3. The service locks the central user identity before cleanup.
4. Group ownership must be explicitly transferred first; account erasure never silently orphans an owned group.
5. The service detects the Phase 1 signup schema state before querying signup tables:
   - all signup tables absent -> legacy-compatible cleanup path;
   - all signup tables present -> full signup-aware dependency cleanup;
   - partial signup schema -> fail closed.
6. For a fully present signup schema, the user's own outbox rows, verification-token rows, signup events and signup requests are removed in RESTRICT-safe order.
7. Central memberships, join requests and any present legacy password-token artifacts (`password_reset_tokens` and/or `user_tokens`) are removed transactionally.
8. Both modern and legacy join-request email columns are considered when present. Both known audit-decider column variants are checked when present, so mixed-schema references cannot be ignored.
9. If the user is an approval/audit actor for another identity, or an unexpected central FK blocks hard deletion, the central account is irreversibly anonymized instead of breaking referential integrity.
10. Success UI does not echo the deleted email address.
11. Tenant DBs, employee records, project data and business records are not automatically deleted. Their lifecycle can have separate organizational/contractual/statutory bases.

## Administrator membership assignment boundary

The same user-admin hardening prevents a central administrator from using the legacy assignment form to create an active `user_group_map` for an inactive central account. Assignment succeeds only when the target user is active and the selected group is active and role exists. This keeps the manual administrator screen consistent with the normal join-approval precondition.

## Runtime validation still required later

Before relying on hard deletion in production, inspect the real central foreign-key graph in an approved non-production environment and run the relevant Django tests. The service intentionally falls back to anonymization on unexpected central FK conflicts, but that fallback is not a substitute for schema validation.

Do not infer that central-account erasure authorizes deletion of tenant operational or personnel records.

## Django session-bridge identity

GeoFlow login uses the standard Django `auth_user` row only as a session bridge while `public.users` remains authoritative. Because that bridge mirrors the user's email into `username`/`email`, central erasure must not leave it untouched. The prepared service anonymizes matching bridge rows in the same central transaction: it replaces the username with a random `.invalid` value, clears email/name fields, installs an unusable password, and removes active/staff/superuser capability. It preserves the numeric Django row id rather than blindly deleting it so Django audit foreign keys can remain intact without retaining the original email identity. Existing sessions then fail the central active-account guard because the old email no longer resolves to an active central account.

## Administrator self-erasure guard

The central administrator delete endpoint should reject attempts to erase the currently authenticated central administrator from their own active admin session. This is an operational lockout guard, not a denial of the user's privacy rights: another authorized central administrator can process the erasure request through the same service after any required ownership transfer.
