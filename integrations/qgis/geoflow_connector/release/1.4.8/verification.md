# GeoFlow Connector 1.4.8 verification

- QGIS 4.2.2 / Windows: all 21 runtime regression programs passed (regression-results.json).
- Repository/package/publisher tests: all 22 cases passed across the package suite and final publisher contract rerun.
- Immutable archives for existing releases remain reproducible; the new archive matches its allowlisted per-file inventory.
- Package audit: 5,609 runtime files; no detected credentials, user cache, logs, tests or scripts.
- Real qgis-bin processes, isolated profile installed from the release ZIP: 105 modules imported, classFactory/initGui and form host started; temporary GPKG/project saved and reopened in a second process; angle 135.125 and direct ang_dir symbol binding persisted.
- GUI runtime checks used Qt offscreen mode, temporary layers and mocked authorization/server responses. No operational objects or live authenticated server save flows were tested or changed.
- Protected manual plugin publication only; no server code checkout, migrations, service restart or test-channel changes.
