# Tenant data-processing governance blocker

Status: **product/legal/operations design item.** The initial-release RRN application path is disabled, but customer tenant-data governance is not complete.

This document does not create a customer contract, inspect tenant data, or change runtime processing.

## Why this remains separate from public-signup privacy

GeoFlow has two materially different personal-data roles:

1. **Central account/signup data**: GeoFlow determines the signup, authentication, approval, security and account-management purposes described in the public privacy notice.
2. **Tenant business/personnel data**: customer organizations may place employee profiles, contact data, project photos/files and other operational records into their tenant database/storage for the customer's business purposes.

The public signup privacy notice is not a substitute for customer-specific tenant data governance. Before broad customer onboarding, the allocation of customer/GeoFlow responsibilities must be explicit in the customer contract and tenant-facing materials.

## Current technical position

Recent application hardening materially improves the tenant boundary:

- tenant event/attachment APIs derive access from current tenant context and scope permissions;
- tenant route read/write permissions have been aligned for the reviewed project/contract/partner/org-unit surfaces;
- JSON-driven event and project-scope renderers no longer insert user/API values through the reviewed unsafe HTML sinks;
- employee RRN collection, normal decryption/display and crypto write paths are disabled in code;
- direct employee/event upload combinations and declared sizes are bounded and commit performs S3 metadata verification.

These changes reduce application risk but do not decide the legal/contractual data-processing role, historical-data lifecycle or storage lifecycle.

## Contract / DPA checklist

Where the customer controls the purpose of tenant personal data and GeoFlow processes that data on the customer's behalf, the written customer terms/DPA should address at least:

- documented processing purpose and scope;
- processing only within the delegated purpose/instructions;
- technical and administrative safeguards;
- confidentiality and least-privilege duties;
- storage locations and approved infrastructure/subprocessors;
- customer instructions for correction, deletion, export and return;
- incident/breach notification and cooperation procedures;
- retention and deletion at contract termination, including backups and delayed-delete windows;
- audit/inspection and evidence responsibilities;
- subcontracting/re-processing provider changes;
- data portability/export format at termination;
- customer responsibility for the lawful basis and notices applicable to its employee/business data.

Map these items to the law and each customer/use case during the contractual review rather than treating this engineering checklist as legal approval.

## Subprocessor inventory

Maintain a versioned inventory based on actual runtime data flows. Potentially relevant services include:

- AWS compute/database/storage in the configured region;
- email services when tenant data is actually transmitted through email;
- future monitoring, support, analytics, document-processing or backup providers that can access tenant personal data.

Do not classify a software dependency as a subprocessor solely because it exists in source code; base the inventory on actual processing/access.

## Product/operations controls still required

1. **Tenant export**: define who can request/export tenant data, supported formats, authorization and audit evidence.
2. **Tenant deletion/termination**: define live-data, attachment, backup/snapshot and delayed-delete treatment when a customer terminates service.
3. **Support/operator access**: define the purpose, approval, least privilege, time bounds and logging for operator access to customer tenant data.
4. **Attachment lifecycle**: soft-deleting attachment metadata is not the same as physically deleting the S3 object. Define retention and physical deletion behavior.
5. **Upload orphans**: the current presigned PUT workflow verifies actual size/MIME/encryption at commit, but a failed or malicious upload can leave an uncommitted S3 object. Define orphan reconciliation/lifecycle or move to an upload mechanism that enforces stronger conditions before object creation.
6. **Logging**: production logs must not contain passwords, verification tokens, RRN values or unnecessary email/phone/file-content data.
7. **Central-vs-tenant deletion**: central account erasure must not automatically destroy customer business records without an explicit tenant lifecycle rule.

## High-risk identifier status

The initial-release employee code no longer collects/displays/decrypts RRN values in normal operation and rejects a non-empty direct `rrn_plain` POST. This closes the **new application processing path**, not the historical-data question.

No tenant database was inspected or changed during this hardening. Historical RRN-related columns/values may still exist. Their inventory, lawful purpose, retention and deletion require a separately approved database/governance process. See `tenant_hr_personal_data_blocker.md`.

## Launch position

Central public signup can be reviewed independently, but GeoFlow should not be represented as fully ready for unrestricted tenant HR/business personal-data onboarding until at least:

1. the customer/GeoFlow processing-role model is decided;
2. customer contract/DPA terms are approved;
3. the subprocessor inventory matches actual runtime flows;
4. tenant export/delete/termination and support-access procedures are documented;
5. attachment/orphan storage lifecycle is defined; and
6. historical high-risk identifier treatment is resolved where applicable.
