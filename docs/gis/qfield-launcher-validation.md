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

## 0.1.2: reconnect after the old development key was lost

The development startup script now stores one Windows DPAPI-protected signing
key per host/port/central/tenant combination under LOCALAPPDATA/GeoFlow/dev-runtime.
It generates a key only once, never prints it, and fails on unreadable stored keys.
The first transition still invalidates old credentials. This is development-only;
production settings are unchanged. Windows DPAPI must be verified on Windows.

After pulling and restarting the dev server, log in on the PC using the SAME LAN
origin as the phone (http://192.168.0.6:8000). Download the browser-authorized file:
`/gis/projects/11111111-1111-4111-8111-111111111401/api/qfield/connection-recovery/`.
Save it as `C:\GeoFlow\logs\geoflow-qfield-connection.json`. Do not upload it to
chat or git: it contains an identity-bound claim credential. It grants no GIS
access by itself and does not stage a handoff. Access still requires the same
user's explicit browser action and normal server-side membership validation.

Save edits and stop QField, then run:

```powershell
adb shell am force-stop ch.opengis.qfield
.\.venv\Scripts\python.exe .\scripts\dev\reconnect_qfield_project.py `
  --connection-file "C:\GeoFlow\logs\geoflow-qfield-connection.json" `
  --project-dir "/storage/emulated/0/Android/data/ch.opengis.qfield/files/Imported Projects/geoflow-qfield-GIS-DEV-001" `
  --backup-dir "C:\GeoFlow\logs\qfield-recovery"
```

The tool backs up the whole selected project, checks exact project/server match,
preserves all QGS bytes except the claim value, rejects concurrent file changes,
and reads back the uploaded QGS. It does not change the runtime, access cache,
GeoPackage or outbox. Open the existing project, then use Open in QField from the
same account's browser to authorize the next session claim. This is a one-time
ADB-assisted development recovery, not the final end-user pairing experience.

Update Launcher using `/gis/qfield/launcher.zip?v=0.1.2`. In QField's plugin
permission dialog, select "Remember my choice" when allowing the trusted
launcher, and ensure it is enabled. Inspected QField source only persists
userEnabled with permanent permission; one-session allowance explains a possible
missing ready message after restart. Never modify QField permission settings
programmatically. Actual installed-version behavior still needs device testing.
0.1.2 dismisses the welcome screen for an already-current registered project,
without reloading it. Other project screens and cold-start action timing remain
subject to device validation.

## Field runtime 0.9.9: stalled changeset recovery

Launcher and per-project Field runtime are separate components. Launcher updates
never replace the Field runtime. 0.9.9 adds a 30-second changeset watchdog,
retaining the original outbox/changeset ID for idempotent retry and ignoring late
callbacks from aborted requests. It logs sync guards for outstanding requests,
uncommitted edits and conflicts. The supplied 17:15 log shows authentication but
no POST or delta request; it does not prove which guard prevented progress.
The watchdog fixes a verified missing timeout, not a proven diagnosis of that
specific phone session. WebGIS also reloads the current extent on WebSocket
connection, because events missed while disconnected are not replayed.

Save QField edits and stop the app, then update the project runtime from the
checked-out repository (no Django server/database connection is used to render):

```powershell
adb shell am force-stop ch.opengis.qfield
.\.venv\Scripts\python.exe .\scripts\dev\update_qfield_runtime.py `
  --project-dir "/storage/emulated/0/Android/data/ch.opengis.qfield/files/Imported Projects/geoflow-qfield-GIS-DEV-001" `
  --backup-dir "C:\GeoFlow\logs\qfield-recovery"
```

This backs up the whole project, verifies that the existing QML is recognizable
and unchanged before writing, updates only the QML and reads it back. No QGS,
GeoPackage, credential or outbox mutation is performed. QField's plugin-file
security boundary is not bypassed; this is an explicit PC/ADB maintenance tool.

Restart the development server after pulling. Start fresh log capture before
opening QField. Open the same existing project and confirm Field 0.9.9 in logs.
Open it from the phone's GeoFlow browser, keeping the PC WebGIS map open. Wait
40 seconds for any existing queue, then save one road vertex edit and verify
POST changesets=200, changeset applied, WebGIS feature batch request, and visible
geometry change without refresh. If a guard/conflict is logged, preserve data
and diagnose that guard; do not delete the queue or reimport the project.
Tests cover Python regressions and extracted JavaScript timeout state behavior;
actual QML/Android behavior and live PostGIS/WebSocket end-to-end remain unverified.

## Field 0.9.10: retained conflict recheck

The 17:26-17:29 device log explicitly reports `conflict requires review`.
No changeset is sent in that state. The server now checks committed changeset
receipts before QField version validation, within the existing transaction and
project lock, so a retry after a lost success response does not conflict with
its own committed edit. New requests still undergo concurrency validation.
This ordering bug is confirmed in code; whether it caused the saved device
conflict requires rechecking that original request.

Update using update_qfield_runtime.py after saving edits and stopping QField.
Field 0.9.10 allows the user to press the plugin toolbar sync button to recheck
the exact retained outbox, keeping its ID, base version, and attributes intact.
It never clears a conflict merely to retry. A committed receipt resolves it;
a genuine conflict remains blocked and logs layer/reason. Pending later edits
are preserved. The sync button now uses the available QField theme icon
ic_cloud_synchronize_24dp instead of the missing ic_sync_white_24dp.
