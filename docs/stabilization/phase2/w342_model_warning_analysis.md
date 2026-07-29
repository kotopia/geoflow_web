# W342 Model Warning Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: a7dda13 phase2: fix test-only diagnostic checkpoint encoding
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Analyze the recurring W342 model warning.
- Identify the exact model and field causing the warning.
- Determine whether the warning is runtime-breaking or design-level.
- Determine whether a future fix would require model and migration changes.
- Avoid changing code, models, migrations, tests, templates, static files, or DB state in this analysis step.

## 3. Warning Summary

```text
catalog.CategoryParent.child: (fields.W342) Setting unique=True on a ForeignKey has the same effect as using a OneToOneField.
HINT: ForeignKey(unique=True) is usually better served by a OneToOneField.
```

This is a Django system-check warning, not a startup or runtime error. The project check completes while reporting this design warning.

## 4. Source Finding

The warning originates from:

- File: `control/catalog/models.py`
- Model: `CategoryParent`
- Field: `child`

The field is a `ForeignKey` to `CategoryNode` and is also declared as the model primary key.

The model also has:

- a `parent` foreign key
- a uniqueness declaration covering the parent-child pair
- `managed = False`
- an explicit existing database table mapping

No model or migration file was modified during this analysis.

## 5. Why W342 Is Raised

A primary-key field is inherently unique. Therefore, declaring `child` as a foreign key and also making it the primary key gives the foreign key the same effective uniqueness as `unique=True`.

The resulting relationship means:

- each `CategoryParent` row identifies its child through the primary key
- the same child cannot appear in more than one `CategoryParent` row
- the model behaves like a one-to-one relation from `CategoryParent` to the child node

Django recommends expressing that cardinality explicitly with `OneToOneField` rather than a unique `ForeignKey`.

The parent-child pair uniqueness declaration is weaker than the child primary-key constraint. If the child is already unique by itself, the pair cannot be duplicated.

## 6. Runtime and Design Impact

### Runtime impact

- The warning does not by itself prevent Django startup.
- It does not by itself cause requests, tests, or system checks to fail.
- Existing Phase 2 checks have repeatedly completed with W342 as the only known warning.
- No evidence from static inspection indicates an immediate runtime failure caused solely by W342.

### Design impact

The warning exposes an ambiguity in the intended relationship:

- If each child must have exactly one parent link, the current uniqueness may be intentional, but `OneToOneField` is the clearer model expression.
- If a child may have multiple parent links, the current child primary key is too restrictive and the model/database key design must change.

Static usage commonly queries or deletes links by child and includes code that selects a single parent. This is compatible with a single-parent design, but static code alone is not sufficient to confirm the authoritative database cardinality requirement.

## 7. Migration and Schema Considerations

`CategoryParent` is an unmanaged model. Django does not normally own creation or alteration of its physical table. The initial migration state inspected for this model also does not fully describe the current foreign-key fields.

Consequences:

- A future change must not assume that editing `models.py` is sufficient.
- A future change must not blindly run `makemigrations` or `migrate`.
- Migration state and the physical table definition must be reviewed separately.
- The actual uniqueness and primary-key constraints must be confirmed before choosing a fix.

### If one parent per child is intended

A likely model-level direction is:

- express `child` as `OneToOneField`
- retain the existing primary-key and deletion semantics if they match the physical schema

This may require no physical constraint change if the database already enforces the same uniqueness. However, migration-state handling still needs an explicit design because the model is unmanaged and the existing migration state is not a complete representation of the current fields.

### If multiple parents per child are intended

The future change would be broader:

- remove child-level primary-key uniqueness
- introduce a suitable row identity or key strategy
- retain or redesign parent-child pair uniqueness
- update the physical database schema
- review all ORM code that assumes one parent

This option would require an explicitly approved schema and migration task and is not a minimal warning cleanup.

## 8. Can It Be Fixed Immediately?

No immediate fix is recommended in the current step.

Before implementation, the following decisions are required:

1. Confirm whether one child is allowed to have only one parent.
2. Inspect the physical table constraints through a separately approved read-only metadata task.
3. Decide how unmanaged-model migration state should be represented.
4. Review affected catalog queries and write paths against the chosen cardinality.
5. Scope model, migration-state, and possible schema changes explicitly.

Changing only the field class may silence W342, but doing so without confirming schema and relationship intent could hide a deeper model mismatch.

## 9. Recommended Future Direction

Recommended next step:

- perform a read-only schema and cardinality design review for the existing category-parent table

If the single-parent relationship is confirmed:

- prepare a narrow design for changing the model expression to `OneToOneField`
- document whether the change is model-state-only or requires an explicit migration-state operation
- verify that no physical schema change is needed before implementation

If multiple parents are required:

- defer the warning cleanup
- design a separate schema migration and ORM compatibility plan
- do not treat the work as a simple warning removal

## 10. Future Verification Plan

After a separately approved implementation:

| command | purpose |
|---|---|
| `python -m py_compile control/catalog/models.py` | syntax check |
| targeted catalog model/tests command | catalog behavior regression |
| `python manage.py check` | confirm W342 outcome and system checks |
| `git diff --check` | diff hygiene |
| migration-state review command, if explicitly approved | verify intended model state |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | safety check |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | safety check |

No migration command should be run without separate explicit approval.

## 11. Safety Notes

- No code, model, test, or migration file was modified.
- No `makemigrations` command was run.
- No `migrate` command was run.
- No DB connection, query, write, or schema operation was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 12. Conclusion

- W342 is a design-level warning, not an immediate runtime-breaking error.
- It is caused by `CategoryParent.child` being a foreign key that is also the primary key.
- The current definition enforces one link per child and behaves like a one-to-one relationship.
- A future fix requires confirming intended cardinality and reviewing unmanaged-model migration and physical schema implications.
- The warning should remain until that design is explicitly approved.
