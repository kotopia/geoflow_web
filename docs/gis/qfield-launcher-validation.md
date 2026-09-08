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

## Field 0.9.12: explicit local-edit conflict recovery

Save edits, authenticate through GeoFlow, then long-press the GeoFlow sync
button. The confirmation dialog lists the update targets and explains that
local geometry/attribute edits will be submitted. Cancel makes no state change.
Confirm creates a new changeset using the server_updated_at from the retained
conflict response. The unchanged server concurrency validator checks that
version under lock; another server edit results in a new 409, never force-write.

Before submission the project state archives the original outbox, pending
changes and conflict together. Pending successors for the same object merge
into the new update (latest geometry/attributes); unrelated pending changes
remain queued. Only update actions and server_object_changed conflicts with
known server timestamps are supported. Delete/missing/versionless/mismatched
conflicts stop without mutation. State changes while the dialog is open cancel
submission. This is explicit local preference, not automatic conflict merging.
The archive remains in QField's durable sync settings; do not clear app data.

Apply code and runtime with the existing update_qfield_runtime.py tool (full
project PC backup and QML byte verification). Confirm Runtime 0.9.12 in output.
Start logs, open the existing project via GeoFlow, save edits, long-press sync,
confirm the listed DORO target and wait 40 seconds. Expect recovery submitted,
POST 200, changeset applied, and WebGIS geometry refresh. If 409 occurs, retain
the archive and compare again. JavaScript state tests cover preservation,
latest pending geometry, unsupported conflicts, and unchanged input state;
actual QField dialog rendering and device persistence require device validation.

## Explicit import and repeated-open validation (2026-09-08)

The dashboard Open button now always invokes the registered launcher URL. Missing
browser storage, a different browser origin, and runtime/schema version changes
must never silently select ZIP import. Only **QField 최초 가져오기** imports a new
copy, after explicit confirmation. This does not automatically upgrade a registered
project's runtime/schema; use the validated in-place runtime procedure for runtime
updates and a separate reviewed migration for schema changes.

Device test order:
1. Finish syncing current edits; resolve any pending/conflict indication before
   deleting anything. Stop QField and back up Imported Projects with adb pull.
   Do not clear QField application data or uninstall the app/launcher.
2. Pull this branch and restart the development server; hard-refresh the phone
   browser at the same LAN origin. Start fresh QField/server log capture.
3. Remove the old GeoFlow project folders in QField (only after step 1).
4. In the phone browser choose **QField 최초 가져오기** once and confirm. Open
   that project, allow its plugin, then use GeoFlow Launcher configuration to
   register this exact current project. Launcher registration remains necessary.
5. Save and close the project. From the browser click **QField에서 열기** three
   times, returning to the browser between attempts. Expect the same registered
   path and only one package-import GET in the entire test.
6. Leave the map still for two minutes. Edit/save one road vertex; expect a
   changesets POST, delta GET, and a PC features GET for DORO. Observe the PC
   geometry update without manual reload. Repeat once. Upload both logs.

Transport audit of the recovery test: 3 changesets POSTs, 3 delta GETs, 3 PC
features GETs, and 57 geojson GETs (layer loads; not 57 edit uploads). The client
loads layers initially and on WebSocket open/reconnect, and after map movement
with a 250 ms debounce. WebSocket changes fetch affected objects. The 2-second
QField polling timer inspects local features, not HTTP; the 3-second send timer
runs only with unsent work. Failed uploads retry with 3/6/12/24/48/60-second
backoff. Persistent runtime disables periodic roaming. Delta is pulled on sync
without an upload and after successful upload, rather than constant idle polling.
Thus an idle QField project does not continuously poll server changes; do not
promise automatic server-to-QField updates while idle. Manual sync retrieves
server deltas. Local full-feature polling and initial per-layer requests remain
scaling considerations, even without periodic network uploads. This audit is not
a load test and does not establish concurrent-user capacity.

### Import redirected to HTML after an existing native session

The 18:35:13 device test returned package-import 302 → /control/ 302 → /login/
200; QField then opened Imported Datasets/_3. rather than geoflow-field.qgs.
A native cookie jar can retain tenant session state without a Django browser
login. Both browser tenant freshness and tenant connection routing must defer
this exact GET package-import route (with token) to its view's signed-token
hydration. Token presence alone never grants access. Invalid tokens receive 401;
project scope, current membership and maps.view remain enforced by the view.
Other browser/package routes retain the browser guards.

ADB no-device/unauthorized messages mean force-stop and backup did not succeed.
Do not delete further projects based on an empty backup directory. Unlock phone,
accept USB debugging authorization, and verify `adb devices` reports `device`
before backup/capture. ADB failure does not explain this HTTP redirect.
After server update, retry explicit import once, then require package-import
200 with a ZIP and a QField geoflow-field.qgs load before repeated-open tests.
