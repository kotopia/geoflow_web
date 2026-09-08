# GeoFlow Launcher 0.1.1 recovery and device validation

0.1.0 is defective: reading bundled field-runtime.qml is blocked by QField's
project-directory boundary. It can then overwrite the project QML with empty
content. Do not use its configuration action. 0.1.1 registers a path only;
it performs no project file writes and no runtime upgrade. Its ZIP contains
only main.qml and metadata.txt. No security restriction is bypassed.

Save edits, stop QField, and inspect the selected project with:

```powershell
adb shell am force-stop ch.opengis.qfield
.\.venv\Scripts\python.exe .\scripts\dev\recover_qfield_runtime.py `
  --project-dir "/storage/emulated/0/Android/data/ch.opengis.qfield/files/Imported Projects/geoflow-qfield-GIS-DEV-001" `
  --backup-dir "C:\GeoFlow\logs\qfield-recovery"
```

This copies the entire selected project to a new PC backup directory. Add
`--restore-empty` to restore ONLY a zero-byte geoflow-field.qml from its
nonempty, recognizable .before-launcher.bak. Existing nonempty runtimes,
missing backups, failed reads, and running QField stop recovery. It verifies
the restored bytes. QGS, GeoPackage, pictures, outbox, and the original backup
are retained. Recognition is not a QML syntax test. If refused, retain all
copies and inspect before attempting any other recovery. Do not reimport ZIPs
or clear QField data. Choose the exact project copy containing desired edits.

Update the app plugin from `http://192.168.0.6:8000/gis/qfield/launcher.zip?v=0.1.1`
using QField's plugin manager and confirm version 0.1.1 before configuring.
Open the existing project and register it using the plugin configuration button.
Save, close the project, and use the browser's Open in QField action.

Capture logs for both warm and cold app startup. Expected stages are
`GeoFlow Launcher 0.1.1 ready`, `action received`, and `load requested` (or
`registered project already current`). Logs exclude URLs, tokens and paths.
If ready is absent, check app-plugin enablement. If action received is absent,
action delivery/lifecycle still needs device investigation. A load request
alone does not prove project loading succeeded. Another open project is never
replaced automatically. Registration does not select or delete duplicate copies.

Device validation remains required. Python tests cannot establish QML loading,
cold-start action delivery, or actual Android recovery behavior. Authentication
and changeset synchronization must be checked separately. The last supplied
log contains a successful session claim followed by changeset_failed; obtain
the matching server traceback before changing the edit protocol.
