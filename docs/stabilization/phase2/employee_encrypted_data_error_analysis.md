# Employee Encrypted Data Error Analysis

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: 032e80b phase2: document presign entity resolution smoke test
- Working tree expected state: clean

## 2. Error Summary

Some employee detail pages returned HTTP 500.

Observed error:

- django.db.utils.OperationalError: Wrong key or corrupt data

Observed location:

- geoflow_ops/views_employees.py
- employees_detail()
- around line 314
- during PostgreSQL pgcrypto decryption

This error is separate from the upload hardening work.

The upload hardening flow remained normal.

## 3. Code Location

The failing logic decrypts:

- hr.employee_profile.rrn_cipher

The displayed fallback field is:

- rrn_last4

Related consistency fields:

- rrn_cipher
- rrn_hash
- rrn_last4

The SQL structure uses parameter binding:

- SELECT pgp_sym_decrypt(rrn_cipher, %s)
- WHERE id = %s

The actual key, encrypted value, and decrypted personal data must not be printed.

## 4. Decryption Flow

Current flow:

1. employee profile is loaded
2. rrn_last4 may be used to build a masked display value
3. settings.RRN_SYM_KEY is used for pgcrypto decryption
4. pgp_sym_decrypt(rrn_cipher, key) is executed
5. decrypted digits are converted into masked display text
6. profile["rrn_masked"] is updated

Current issue:

- the decryption SQL has no narrow try/except guard
- if pgp_sym_decrypt raises Wrong key or corrupt data, the fallback display is not reached
- the whole employee detail page returns HTTP 500

## 5. Why Only Some Employees Fail

Likely causes:

### 5.1 Damaged copied ciphertext

A manually copied encrypted value may have been corrupted during copy/paste.

Possible causes:

- bytea hex/escape representation changed
- copied value was truncated
- GUI-displayed value was copied instead of raw bytea
- text conversion changed the binary payload
- extra quotes, escapes, whitespace, or line breaks were introduced

### 5.2 Different encryption key

Some rows may have been encrypted with an older or different key.

If all encrypted rows failed, the current key itself would be suspect.

Because some employees work and some fail, the issue is more likely row-specific.

### 5.3 Malformed or mixed data

Some rows may contain:

- empty binary payload
- plaintext stored in the encrypted column
- malformed bytea
- old-format encrypted data
- rrn_cipher, rrn_hash, and rrn_last4 from different source rows

### 5.4 Null data

NULL data may not fail in the same way and may fall back to rrn_last4.

Therefore normal employee pages do not necessarily prove that every encrypted value is valid.

## 6. Manual Copy Hypothesis

The user's manual copy operation could be the cause.

Important distinction:

### 6.1 Technically safer copy

A direct database-to-database bytea assignment may preserve the encrypted value.

Example concept:

- destination.rrn_cipher = source.rrn_cipher

This may decrypt successfully if:

- the source ciphertext is valid
- the same RRN_SYM_KEY is used
- the value is copied byte-for-byte
- no text representation conversion occurs

However, copying only rrn_cipher may still break consistency with rrn_hash and rrn_last4.

### 6.2 Risky copy

Risky methods include:

- copying displayed bytea text from a GUI
- converting bytea to text and back
- copying only part of the value
- copying from another environment/key
- storing plaintext or masked values into rrn_cipher
- copying rrn_cipher without rrn_hash and rrn_last4 consistency

## 7. Recommended Decision

Decision:

- code guard first
- data repair later

Reason:

- immediate DB UPDATE is risky
- the damaged rows are not fully identified yet
- the application should not return HTTP 500 just because one encrypted field cannot be decrypted
- code guard can prevent page failure without exposing secrets or changing DB data
- data repair can be handled later as a controlled DB maintenance task

## 8. Recommended Code Guard Scope

Future code-change scope:

- geoflow_ops/views_employees.py only

Goal:

- catch pgcrypto decryption failure narrowly
- keep employee detail page available
- fall back to rrn_last4-based masking when available
- do not print key, ciphertext, or decrypted personal data
- log only safe metadata such as employee ID and error category
- do not change save/encryption behavior
- do not run migration
- do not change RRN_SYM_KEY

## 9. Recommended Data Repair Scope

Future DB maintenance scope:

- only after explicit approval
- only after backup confirmation
- problem rows only
- no secret output
- no encrypted value output
- no decrypted personal data output

Preferred repair route:

- re-enter the correct value through the normal application save flow
- allow the app to regenerate rrn_cipher, rrn_hash, and rrn_last4 consistently

If original value is unknown:

- do not invent personal data
- decide separately whether to clear the damaged encrypted fields

## 10. Must Not Do

Do not:

- rotate RRN_SYM_KEY
- print .env
- print RRN_SYM_KEY
- print encrypted values
- print decrypted personal data
- run UPDATE now
- run migrations
- copy ciphertext through uncontrolled text representation
- treat code guard as data repair

## 11. Final Recommendation

Recommended path:

1. document this analysis
2. implement code guard first
3. smoke test failing and normal employee detail pages
4. plan controlled data repair later if needed

Result:

- both code guard and data repair are needed
- code guard should come first
- data repair should be a separate approved maintenance scope
