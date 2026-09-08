# GeoFlow GIS Reference Catalog

## Decision

GIS reference data is owned by the `gis` schema. It must not use `ops.settings_nodes` as a live source.

The existing GIS foundation tables are the canonical store:

- `gis.ref_code_group`
- `gis.ref_code_value`

Field-to-reference binding is defined by:

- `gis.meta_field_def.code_group_key` -> `gis.ref_code_group.group_key`

No additional customer-specific reference schema is introduced.

## Runtime contract

WebGIS, QGIS, and QField resolve reference values at runtime from the GIS catalog. The client package contains the binding key or the reference-catalog endpoint, not the option list itself.

For an enabled project layer, the runtime resolver:

1. reads the layer/field definition from `gis.meta_feature_type` and `gis.meta_field_def`;
2. resolves `code_group_key` against an active `gis.ref_code_group`;
3. returns only active `gis.ref_code_value` rows whose validity period includes the current date;
4. returns the same code/label ordering to all GIS clients.

Project-scoped endpoints:

- Browser/WebGIS/QGIS: `/gis/projects/<project_id>/api/reference-catalog/`
- QField bearer session: `/gis/projects/<project_id>/api/qfield/reference-catalog/`

QField access remains project-scoped through the existing signed ticket boundary. Direct PostGIS credentials are not exposed.

## Update boundary

Reference option changes are data changes, not client releases.

Examples of changes that do **not** require a QGIS/QField plugin update or QField project reinstall:

- adding a valve-material option;
- disabling an obsolete code;
- changing display order;
- changing the display label of an existing code;
- setting a validity period for a code.

These changes modify `gis.ref_code_group` / `gis.ref_code_value` and become visible on the next runtime catalog fetch.

Changes that alter field structure or the field-to-group binding are metadata changes. They may require the client to refresh metadata, but they are still separate from plugin-code releases unless client behavior itself changes.

## Isolation from OPS settings

`ops.settings_nodes` remains an OPS/business-settings facility. GIS runtime reference resolution must not import, join, query, proxy, or fallback to it.

If legacy/import tooling later needs to record where a GIS code originated, provenance belongs in GIS-owned metadata. Provenance must never turn into a live runtime dependency on OPS settings.

## Validation

Development preflight validates:

- both GIS reference tables exist;
- active group/value counts can be read;
- every non-empty `gis.meta_field_def.code_group_key` resolves to an active GIS code group.

Zero groups/values/bindings is valid during staged rollout. A dangling field binding is not valid and stops the GIS preflight.

## Seed policy

Do not guess semantic mappings from legacy column names. A concrete binding such as a valve-material field is seeded only after the exact source field and approved code list are confirmed. The reference engine itself is independent of that seed data.
