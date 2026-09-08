# GeoFlow Launcher device validation

Status: device validation required. Server-side tests and ZIP rendering pass;
Android QML loading, cold-start action delivery, and local file writes are not
validated by Python tests.

Install the code-only app plugin from `/gis/qfield/launcher.zip` using QField's
Plugins > Install Plugin from URL menu, then enable GeoFlow Launcher.
Open the existing GeoFlow project that contains the desired edits. Use the
GeoFlow Launcher configuration button to explicitly register this copy. This
backs up its adjacent `geoflow-field.qml` once, then replaces only that runtime.
The QGS, GeoPackage, pictures, and outbox are not deleted or overwritten.
Save edits, close the project, return to GeoFlow, and use Open in QField.

The registered path is keyed by server URL and project UUID. Another open
project is never replaced automatically. If the app opens without selecting a
project on cold start, report the log: action delivery before app plugin load
still requires on-device verification. Do not work around it by importing ZIPs.

Success: requested registered project opens; session-claim and delta succeed;
no new Imported Projects directory appears. Check warm and cold app startup.
Check expiry, multiple existing copies, missing registered file, and another
open project. Configuration is an explicit selection of the current copy;
no duplicate is automatically deleted.

This handles plugin runtime updates only. A future GIS schema/package change
still requires a separate data-preserving migration. The launcher does not
claim to perform such migrations.
