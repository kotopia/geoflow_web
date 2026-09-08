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

## Consolidated stability milestone: Field 0.9.13 / Launcher 0.1.3

The 19:04 device trace contains two POST starts one millisecond apart under the
same QField tag; revision 62 succeeds and the other response conflicts. This is
not just QField/default log mirroring. Duplicate runtime/event handling is a
working diagnosis; exact device plugin-loading cause is not yet established.

Generated Field QML now elects one owner under the shared main-window content
item. Duplicate instances cannot capture, claim authentication, fetch deltas,
transmit outboxes, or attach layer listeners. Only the owner gets the toolbar
button. Owner destruction releases the slot; a local-only standby timer can
activate a remaining instance. Pending changes and conflict records are never
cleared as part of ownership election. Project load clears stale bindings before
configuration reload. Launcher independently elects a single owner.

Launcher automatically registers the currently loaded GeoFlow QGS after startup
or project-load completion. Missing/deleted registrations are replaced; a valid
different copy is retained until the user explicitly registers another copy.
Only the local path registry changes; QGS/QML/GeoPackage contents are untouched.
QField's plugin installation/permission prompt still requires the user. This is
not automatic plugin installation or a bypass of project/server permissions.

Implementation checks: 27 isolated Python tests and 5 Node suites pass, including
execution of ownership/registration functions extracted from generated QML,
blocked inactive capture/network entry points, lease release, retained valid
copy, stale-path replacement, and replay/conflict/timeout regressions. Android
QML lifecycle and end-to-end editing require the consolidated device test below.

Update once (no re-import or deletion): stop QField, update the existing selected
project with scripts/dev/update_qfield_runtime.py, start the development server,
and update the app launcher via /gis/qfield/launcher.zip?v=0.1.3. Fully restart
QField after updates so pre-0.9.13 instances cannot remain alive; verify versions.

One device acceptance session:
1. Open the existing GeoFlow project; Launcher auto-registers if missing. Existing
   valid registration remains valid. Do not import a fresh copy solely to test.
2. Start one continuous QField/server capture and note each action time.
3. Open via browser three times; same file, no package-import request.
4. Wait two minutes without movement; no periodic changeset traffic.
5. Edit/save road once, wait for PC update, then edit/save once again. Expect one
   active runtime, no paired POST start for one save and no self-conflict. A retry
   after a real network failure is allowed and must retain its request identity.
6. If an older conflict is already present, preserve it and report it; do not
   repeatedly import or silently reset sync state. This milestone does not resolve
   historical conflicting edits without review.

Subsequent development batches (not claimed complete):
- Offline/reconnect and receive behavior: queue durability across app restart,
  retries and concurrent-edit conflict UX; choose bounded server-to-device change
  notification/polling and verify idle request rate and convergence together.
- Field workflow: create/edit facilities and survey links, GNSS/attributes/photos
  against existing metadata and scoped storage routes.
- Multi-user/scale and delivery: permissions/isolation, measured request/DB cost,
  large layer local polling, and QGIS/exports with realistic test data.
Each batch should finish automated regressions before requesting one documented
user acceptance session. Device-only failures can still require a focused retry;
minor implementation edits alone should not trigger another manual test cycle.

## Field 0.9.14: offline flush and bounded foreground receive

Device evidence for 0.9.13: three edits each produced one POST and successful
revisions 64/65/66, with no paired request/self-conflict in this trace. The
launcher still reported 0.1.2, so auto-registration was NOT device-validated.
No QField requests appear between 19:20:35 and 19:28:04 in the submitted server
excerpt; that observation does not establish behavior under other workloads.

Changes in 0.9.14:
- Save sync state with Settings.sync immediately (pending/outbox/conflict retained).
- Foreground, authorized delta check: 15 seconds after changed data, 30 seconds
  after first empty check, then capped at 60 seconds. Failures wait 60 seconds;
  manual sync can request earlier. Background periodic checks are disabled.
  No polling during pending upload, conflict, in-flight upload, or active edit.
- Re-read state at response time. If project/server, base revision, authorization,
  pending/outbox/conflict, or active editing changed, do not apply the response.
- Delta and claim time out after 30 seconds; clear request reference before abort
  and reject late callbacks. Delta timeout retains local state and cursor.
- Stop automatic checks when history requires a new snapshot. Do not repeatedly
  download full projects; explicit recovery/migration remains a separate action.
- Empty has_more responses cannot trigger a tight recursive paging loop.

This changes prior idle behavior intentionally: an idle *foreground* authorized
QField now makes up to roughly one empty delta request/minute after backoff.
Each request still incurs authentication/DB cost. This is a bounded interim receive
strategy, not zero-cost push and not a demonstrated multi-user capacity figure.
Changed data is returned incrementally; no periodic whole-project ZIP transfer.
The current project dashboard is read-only, so do not instruct users to edit on
that page to manufacture reverse-direction changes. A second authorized editor
is needed for an end-to-end server-to-device acceptance check.

Validation: 27 isolated Python tests and 6 Node suites pass. The new suite executes
rendered QML JS to check request coalescing, deadline/backoff, stale response and
edit-race rejection, cursor preservation, empty pagination handling, and immediate
state flush/reconstruction. It cannot prove Android disk/power-loss durability or
actual network reconnection; those remain device acceptance gates.

Consolidated device session (one update and one capture, preserve existing data):
1. Save project; pull branch; stop QField and update the existing project using
   update_qfield_runtime.py. Restart development server. Verify Field 0.9.14.
   Update Launcher separately to 0.1.3; do not reimport project or clear app data.
2. Keep continuous adb/server logs. Edit/save once online; verify PC geometry.
3. Disable phone Wi-Fi/mobile data, keep USB connected. Edit/save again and
   confirm unsent state. Close/reopen QField while still offline; verify geometry
   and pending indicator remain. Do not delete or reinstall anything.
4. Restore Wi-Fi and leave QField open for up to 90 seconds (request timeout plus
   capped retry). Verify pending state clears and PC catches up, without pressing
   manual sync. If authentication expired, return via GeoFlow once; expiry never
   grants a silent token extension.
5. Leave QField foreground idle for 3 minutes. Expect sparse delta requests, no
   repeated changeset POST after acknowledgment. For reverse-direction testing,
   use another authorized editor only when available; no direct DB mutation.
6. Upload logs covering the same times and report online sync, offline retention,
   and reconnect result together. Historical conflict states are preserved; do
   not silently clear them to get a passing test.

## Field 0.9.15: acknowledged cache before the next offline edit

The offline test confirms online revision 67 applied, offline changes were queued,
and reopening the project retried them automatically. The server then returned
409 server_object_changed at 19:40:16 and again on manual retry. The submitted log
does not expose the exact base timestamp. Code inspection identifies a matching
failure path: applyServerVersions updated durable feature_versions but not the
per-binding versionMap, which captureGeometry/captureAttribute prefer. Before a
successful delta/rebind, the next edit could therefore use the pre-ack version.
The new bounded receive interval makes that existing dependency more visible.

Advance only matching layer/UUID entries in the signal capture cache when the
server supplies a version_receipt. Do not rebase existing frozen requests or
silently clear conflicts. Regression tests cover a subsequent offline capture
without an intervening delta, unrelated layer/object isolation, and unverified
receipt protection. Existing offline queued changes survive this code update.

Reconnect sequence: restore Wi-Fi to the development server's LAN, open the same
project containing offline edits, and leave its map visible (not only QField's
home screen). Automatic retry requires no manual sync if auth remains valid.
A conflict halts retries and requires review; waiting or repeatedly pressing sync
cannot resolve it. For this retained test edit, after backup/runtime update,
long-press the GeoFlow sync button to review the DORO recovery dialog. Confirm
only if the phone's retained geometry is the intended result. Original request
and pending edits are archived; the server still rejects a new concurrent change.
Then retest online-save -> offline-save -> app restart -> Wi-Fi reconnect once.

## Field 0.9.16: create and attribute transport increment

The previous device test verified conflict recovery revision 68, online edit 69,
and offline edit retained across a process restart then applied as revision 70.
Subsequent idle delta checks were approximately 62 seconds apart. Launcher still
reported 0.1.2; automatic registration remains a separate unverified device gate.

This increment advances a pending UPDATE from our exact CREATE receipt, keeping
its latest attributes/geometry and frozen outbox intact. Polling can capture a
new committed UUID/project-matching feature absent from a completed baseline,
when it has no server version or existing queue entry; unsaved edits are not
seeded prematurely. Initial project baseline and server-delta rebasing retain
their existing behavior. This is not a full crash-recovery scan of arbitrary
untracked GeoPackage files.

Received attribute updates now use layer.fields().indexOf and callable feature
id where applicable, consistent with the local capture API. Unknown/rejected
fields roll back the attribute edit and stop cursor advance. Tests execute the
rendered JS for missing create signals, no duplicate create on another poll,
create acknowledgement plus follow-up update, remote attribute application and
schema-mismatch rejection. 27 Python tests and 7 Node suites passed. Actual device
create and reverse-direction attribute behavior still need acceptance testing.

Scope boundary: survey points are regular SURVEY features, but gis.survey_link
exists only in schema/seed/preflight in the current code. No QField relationship
form or link changeset path exists yet. Do not equate creating a survey point
with attaching it to a pipe/valve. A subsequent relationship implementation must:
- Use the existing gis.survey_link model; no domain-specific survey tables.
- Resolve feature_type_id from permitted metadata/plan, never a raw table name.
- Verify survey and target both belong to the same authorized project/tenant.
- Preserve UUIDs offline and create parent features before link operations.
- Include link receipt/replay, lineage events, and review of manual confirmation
  identity; never forge confirmed_by from an unrelated central user identifier.
- Export the relationship and receive changes so QGIS/QField share its meaning.
No live schema/data changes were performed in this increment.

Next device batch, after one in-place runtime update to 0.9.16:
1. Create one WTL_VALV_PS point using current form defaults and required fields;
   save and verify PC count/map. Edit one ordinary editable attribute and save.
2. Create one SURVEY point; verify PC count/map. It is not yet linked to a facility.
3. Offline, create one additional valve, change its attribute before transmission,
   save, restart QField, reconnect and verify one object with the latest attribute.
4. Keep both logs throughout. Stop on rejection and preserve objects/queue; do not
   delete/reimport. Existing delete sync is disabled. Reverse-direction attribute
   verification needs another authorized editor; the project dashboard is read-only.

## Field 0.9.17: JSON creation payload and retained-request recovery

The device log confirms three new local UUIDs (two valves, one survey), retained
across restart (baseline 11 vs 8), but the first outbox repeatedly receives HTTP
400 `ext_data: invalid JSON`. Its blocked outbox delays subsequent work. The
log does not contain the raw ext_data value; do not claim a particular malformed
representation is proven from this trace alone.

Server coercion now maps blank/whitespace ext_data to the existing empty-object
default, as it already did for NULL. Other JSON fields keep their null/validation
semantics. Malformed nonempty JSON remains rejected. QML normalization now keeps
JSON-compatible objects/arrays structured instead of String(value), which could
produce the lossy literal [object Object]. Dates retain ISO conversion.

For already-frozen outboxes containing exactly the known lossy ext_data marker,
recover only from a readable actual local object's ext_data. Archive the original
request, issue a new changeset ID, and preserve geometry, other attributes and
pending edits. This malformed original cannot pass server JSON validation.
Unreadable local values are not replaced with guessed empty objects. Blank legacy
requests can retry unchanged against server coercion. No queue clearing, object
recreation, or live DB/schema updates are involved.

Validation: 10 focused Python tests and 4 Node suites pass (JSON recovery,
successor versions, timeout, owner guard). Device repair remains to be verified.
Update server and the existing project's runtime to 0.9.17 once, preserve the
three created features, open from GeoFlow and wait for transmission. Manual sync
may be used once. Expect no invalid JSON rejection and eventual new PC features;
compare UUID/counts and latest attribute values, not just a 200 response. If still
rejected, retain the data and capture the new exact error; do not create more
objects or repeatedly import projects.

## Server typed-scalar validation after JSON recovery

The 20:37 device run uses Field 0.9.17 and retains 11 local features. JSON
validation no longer rejects the first creation, but INSERT fails with PostgreSQL
22007 InvalidDatetimeFormat. The exact input field/value is absent from the log.
Do not claim that an empty date is proven; it is one supported missing-value case.

Server coercion now normalizes blank typed dates/times/numbers/booleans to NULL,
parses valid ISO temporal values, preserves numeric decimal precision, and rejects
invalid nonempty values with field/type details before INSERT. Text emptiness,
JSON semantics, UUID validation, DB constraints, and tenancy remain separate.
QField's ISO datetime representation is accepted for date fields as a date.
No fake dates, zeros, or arbitrary replacements for malformed data are introduced.

14 focused tests cover typed blanks, temporal/numeric/boolean validation, UUID and
JSON behavior, and existing changeset replay ordering. These are isolated tests,
not a successful PostGIS/device insertion claim. Update/restart SERVER ONLY; keep
Field 0.9.17 and existing project/outbox. Retry the same retained three features.
If input is truly malformed nonempty data, expect a field-specific validation
error rather than repeated generic database 503; preserve the queue for review.

## Mixed create batch: survey raw_data default coverage

The 20:47 test confirms first valve creation committed as revision 71. The next
three-item batch is rejected with raw_data: invalid JSON. Atomic rejection keeps
the remaining survey/valve and successor update pending; do not recreate objects.
The foundation SQL declares two feature/survey JSON object defaults: ext_data and
raw_data. Server absence normalization now covers both, while other JSON fields
retain their semantics and malformed nonempty measurement JSON remains rejected.
The exact raw value is not in the device trace; nonempty malformed data still
requires review rather than silent replacement.

15 focused tests pass. A schema-derived coverage test enumerates every jsonb
NOT NULL DEFAULT '{}' field in both GIS foundation SQL files, checks both blank
and NULL input, and verifies actual measurement values are preserved and invalid
content is rejected. No DB/schema mutation or QField runtime change is needed.
Update/restart server only; open the same project and retry the retained batch.
Expect the remaining survey and valve plus pending attribute update to commit;
verify actual UUIDs/counts/attributes as well as HTTP success.
