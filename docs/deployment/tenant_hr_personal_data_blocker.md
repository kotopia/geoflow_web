# Tenant HR personal-data public-launch blocker

Status: **new RRN collection/processing path disabled in application code; historical-data/governance follow-up remains.**

No tenant database, server, storage, migration, or runtime change was performed as part of the code hardening.

## Current code state

The initial-release application no longer exposes the resident-registration-number (RRN) feature in normal employee management:

- employee create/edit UI has no RRN field or masked RRN display;
- a non-empty direct `rrn_plain` POST is rejected with HTTP 400;
- normal employee detail queries do not select RRN fields;
- the employee view contains no RRN encryption, deterministic hash, decryption, or mask-building path;
- the hard-coded demonstration address, license and social-profile content was removed from the employee detail template.

These controls intentionally leave the tenant schema unchanged. The existing `hr.employee_profile` RRN-related columns, and any historical values already stored in them, were **not** inspected, migrated, rewritten, or deleted.

## Initial-release position

Keep RRN processing disabled for the initial GeoFlow release. Re-enabling it is a separate product/legal/security change and must not be accomplished by merely restoring a form field or encryption key.

The disabled application path does not establish that historical RRN data is lawful, necessary, or ready for indefinite retention. That question requires an approved data inventory and customer-specific governance review.

## Remaining release/governance work

1. In an explicitly approved non-production or controlled database window, determine whether historical RRN values exist and which tenants/records are affected. Do not inspect production-like data merely to complete a code review.
2. Decide the lawful purpose, retention, deletion or migration treatment for any historical values before broad tenant HR onboarding.
3. Include backups, snapshots and delayed-delete storage when defining deletion; deleting only the live row is not a complete lifecycle policy.
4. Review uploaded employee documents/photos separately. Attachments can contain high-risk identifiers even when structured RRN fields are disabled.
5. Keep central-account deletion separate from tenant business-record lifecycle. Removing a login identity must not silently destroy tenant HR records that belong to a customer-controlled retention process.
6. Define customer/operator responsibilities, support access, export and termination procedures in the tenant data-processing governance workstream.

## If RRN is ever re-enabled

Before implementation, approve a concrete lawful use case and a dedicated security design covering at least:

- precise purpose and authority to process the identifier;
- authorized roles and least-privilege access;
- explicit full-value access workflow rather than routine profile decryption;
- audit logging and incident handling;
- retention and deletion periods;
- encryption and key management;
- a separate keyed comparison mechanism only if stable comparison is genuinely required;
- key rotation and recovery procedures;
- customer/data-subject notice obligations applicable to the use case.

Do not restore the previous unkeyed deterministic SHA-256 comparison token or normal-detail full-value decryption pattern.

## Release interpretation

The **code-level RRN collection/display blocker is closed for the initial release**. The following remain open and must not be conflated with that code fix:

- historical RRN inventory and lifecycle;
- tenant HR/business-data controller/processor governance;
- attachment/storage lifecycle;
- any future lawful RRN feature design.
