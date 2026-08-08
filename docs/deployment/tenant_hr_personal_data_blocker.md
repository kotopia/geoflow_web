# Tenant HR personal-data public-launch blocker

Status: blocking review item; no tenant database, server, or runtime change has been performed.

## Finding

The current tenant employee implementation contains resident-registration-number (RRN) handling:

- edit/create code accepts `rrn_plain`;
- values can be encrypted with the configured symmetric key and also hashed/masked;
- employee detail UI displays a masked RRN and exposes a new-RRN input in edit mode;
- the template also contains hard-coded demonstration profile/address/social content that should not ship as real employee data.

The current public signup privacy notice intentionally covers signup/account data only. It does not establish a legal basis for tenant HR RRN processing.

## Legal launch position

For the initial GeoFlow public release, treat RRN collection/entry as disabled unless a concrete statutory/regulatory processing basis has been identified for the specific customer/use case. Encryption is a required security control when processing is lawfully permitted; it is not a substitute for the legal basis to process an RRN.

Do not treat ordinary consent as sufficient authority for RRN collection.

## Required product/code actions before broad release

1. Remove or disable the editable `rrn_plain` field from the employee UI by default.
2. Reject/ignore any RRN mutation server-side when the feature is not explicitly lawfully enabled.
3. Do not expose decrypted RRN values to the template. If legacy stored values exist, review their lawful basis and retention before deciding whether masked display should remain.
4. Remove hard-coded demo address/social/license content from the employee detail template.
5. Separate tenant HR/business-data governance from central login/account erasure. Tenant records must not be automatically destroyed merely because a central login account is removed, but their own retention/legal basis must be documented.
6. If RRN processing is later enabled for a specific lawful purpose, document the precise statutory basis, authorized roles, audit controls, retention period, encryption/key management, access logging, and breach-response requirements before enabling it.

## Scope boundary

This blocker does not require changing the Phase 1 central signup schema. It is a tenant HR/data-governance issue and should be resolved before presenting GeoFlow as broadly production-ready.

## Current recommendation

Keep the existing RRN feature OFF for the initial public release and remove the edit field/UI until the lawful-processing basis is established. Continue employee management with ordinary HR fields that have an approved business purpose and privacy notice.

## Cryptographic/data-minimization follow-up if RRN is ever lawfully enabled

The current implementation also computes a deterministic plain SHA-256 digest of the RRN and decrypts the stored ciphertext during normal detail rendering in order to build a mask. Do not carry those behaviors forward unchanged into an enabled production design.

If a lawful RRN use case is later approved:

- avoid an unkeyed deterministic hash as a lookup/deduplication surrogate; use a purpose-specific keyed construction (for example HMAC with a separately managed key) if a stable comparison token is genuinely required;
- do not decrypt the full identifier for ordinary profile rendering merely to display a mask;
- separate encryption keys from comparison/HMAC keys and from application secrets;
- restrict any full-value access to an explicit authorized workflow with audit logging and a documented purpose;
- retain only the minimum masked/non-sensitive derivative required for routine display;
- establish deletion/rotation procedures before enabling the feature.
