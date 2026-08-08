# Tenant data-processing governance blocker

Status: product/legal operations design item. This document does not itself create a customer contract or change runtime processing.

## Why this is separate from public-signup privacy

GeoFlow has two materially different personal-data roles:

1. **Central account/signup data**: GeoFlow directly determines the signup, authentication, approval, security and account-management purposes described in the public privacy notice.
2. **Tenant business/personnel data**: customer organizations may place employee profiles, contact data, project photos/files and other operational records into their tenant database/storage for the customer's business purposes.

The public signup privacy notice should not be treated as a blanket legal basis for all tenant-held business/personnel data. Before broad customer onboarding, the customer/GeoFlow allocation of controller/processor responsibilities must be made explicit in the customer contract and tenant-facing privacy materials.

## Contract / DPA checklist

Where the customer is the personal-information controller and GeoFlow processes tenant data on the customer's behalf, the written customer terms/DPA should cover at least:

- documented processing purpose and scope;
- prohibition on processing tenant personal data outside the delegated purpose/instructions;
- technical and administrative safeguards;
- confidentiality and access-control duties;
- permitted personnel and least-privilege administration;
- storage locations and approved infrastructure/subprocessors;
- customer instructions for correction, deletion, export and return of data;
- incident/breach notification and cooperation procedures;
- retention and deletion at contract termination, including backups and delayed-delete windows;
- audit/inspection and evidence responsibilities;
- rules for subcontracting/re-subprocessing and processor changes;
- data portability/export format at termination;
- tenant responsibilities for having a lawful basis and giving its own employee/data-subject notices where required.

This checklist should be mapped to the then-current Korean Personal Information Protection Act and customer-specific requirements before contractual use.

## GeoFlow subprocessor inventory to maintain

At minimum maintain a versioned inventory for services that can process tenant personal data, not only signup data. Current architecture may include:

- AWS compute/database/storage in the configured region;
- email services where tenant data is actually sent through mail;
- any future monitoring, support, analytics, document-processing or backup provider that can access tenant personal data.

Do not automatically classify a provider as a subprocessor merely because the software dependency exists; base the inventory on actual runtime data flow.

## Product controls required alongside the contract

- Tenant isolation must be enforced by server-side DB routing and authorization, not only by hidden UI.
- Support/operator access to tenant data needs an explicit operational purpose, least privilege and logging.
- Tenant export/delete workflows need a defined ownership boundary before self-service account deletion is advertised as deleting tenant business records.
- Attachments/photos require their own lifecycle and access controls because they may contain personal information even when no structured personal-data field exists.
- Production logs must not contain passwords, verification tokens, RRN values or unnecessary email/phone/file-content data.

## Separate high-risk identifier blocker

Resident-registration-number processing is not covered merely by a customer DPA or ordinary consent. Keep the dedicated `tenant_hr_personal_data_blocker.md` as a separate launch blocker and do not enable RRN processing without a concrete lawful basis and dedicated safeguards.

## Launch position

Central public signup can be reviewed independently, but GeoFlow should not be represented as fully privacy-ready for unrestricted tenant HR/business personal-data processing until:

1. the customer/GeoFlow processing-role model is decided;
2. customer contract/DPA clauses are approved;
3. subprocessor inventory is accurate for actual runtime flows;
4. tenant deletion/export/support-access procedures are documented; and
5. the RRN blocker is resolved.
