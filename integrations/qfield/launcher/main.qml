import QtQuick
import QtCore
import org.qfield
import org.qfield.core

Item {
    id: launcher
    Settings {
        id: registry
        category: "GeoFlowLauncherV1"
        property string projectsJson: "{}"
    }
    function log(stage) { iface.logMessage("GeoFlow Launcher 0.1.1 " + stage) }
    function toast(text) { iface.mainWindow().displayToast(text) }
    function normalServer(value) { return String(value || "").replace(/\/+$/, "") }
    function entry(key) { return String(iface.readProjectEntry("GeoFlow", key, "") || "") }
    function key(server, project) { return normalServer(server) + "|" + project }
    function projects() {
        try { return JSON.parse(registry.projectsJson) } catch (e) { return {} }
    }
    // QField exposes this action as the plugin's configuration button.
    // Register only the file the user explicitly chose, never a guessed copy.
    function configure() {
        let project = entry("project_id")
        let server = normalServer(entry("server_url"))
        let path = String(qgisProject.fileName || "")
        if (!project || !server || !path.endsWith("/geoflow-field.qgs")) {
            toast("사용할 GeoFlow 프로젝트를 먼저 열고 등록 버튼을 눌러주세요")
            return
        }
        let map = projects()
        map[key(server, project)] = path
        registry.projectsJson = JSON.stringify(map)
        registry.sync()
        log("registered")
        toast("현재 프로젝트 등록 완료 · 편집을 저장하고 닫은 뒤 GeoFlow에서 열어주세요")
    }
    Connections {
        target: iface
        function onExecuteAction(action) {
            let data = QfUrlUtils.getActionDetails(String(action))
            if (data.type !== "geoflow") return
            launcher.log("action received")
            let path = launcher.projects()[launcher.key(data.server, data.project)]
            if (!path || !QfFileUtils.fileExists(path)) {
                launcher.log("registration missing or file unavailable")
                launcher.toast("등록된 프로젝트가 없습니다 · 기존 프로젝트를 열고 GeoFlow Launcher에서 등록해 주세요")
                return
            }
            // Do not switch away from another open project: it may hold edits.
            let current = String(qgisProject.fileName || "")
            if (current && current !== path) {
                launcher.log("another project open; deferred")
                launcher.toast("현재 프로젝트를 저장하고 닫은 뒤 다시 열어주세요")
                return
            }
            if (current !== path) {
                launcher.log("load requested")
                iface.loadFile(path)
            } else {
                launcher.log("registered project already current")
            }
        }
    }
    Component.onCompleted: log("ready")
}
