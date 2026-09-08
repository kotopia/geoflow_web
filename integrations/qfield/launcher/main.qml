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
        let runtimePath = path.replace(/\.qgs$/, ".qml")
        let backupPath = runtimePath + ".before-launcher.bak"
        if (!QfFileUtils.fileExists(runtimePath)) {
            toast("기존 GeoFlow 플러그인 파일을 찾을 수 없습니다")
            return
        }
        if (!QfFileUtils.fileExists(backupPath) &&
            !QfFileUtils.writeFileContent(backupPath, QfFileUtils.readFileContent(runtimePath))) {
            toast("플러그인 백업 실패 · 등록을 중단했습니다")
            return
        }
        let source = QfUrlUtils.toLocalFile(Qt.resolvedUrl("field-runtime.qml").toString())
        if (!QfFileUtils.fileExists(source) ||
            !QfFileUtils.writeFileContent(runtimePath, QfFileUtils.readFileContent(source))) {
            toast("플러그인 갱신 실패 · 백업 파일을 보존했습니다")
            return
        }
        let map = projects()
        map[key(server, project)] = path
        registry.projectsJson = JSON.stringify(map)
        registry.sync()
        toast("현재 프로젝트 등록 완료 · 편집을 저장하고 닫은 뒤 GeoFlow에서 열어주세요")
    }
    Connections {
        target: iface
        function onExecuteAction(action) {
            let data = QfUrlUtils.getActionDetails(String(action))
            if (data.type !== "geoflow") return
            let path = launcher.projects()[launcher.key(data.server, data.project)]
            if (!path || !QfFileUtils.fileExists(path)) {
                launcher.toast("등록된 프로젝트가 없습니다 · 기존 프로젝트를 열고 GeoFlow Launcher에서 등록해 주세요")
                return
            }
            // Do not switch away from another open project: it may hold edits.
            let current = String(qgisProject.fileName || "")
            if (current && current !== path) {
                launcher.toast("현재 프로젝트를 저장하고 닫은 뒤 다시 열어주세요")
                return
            }
            if (String(qgisProject.fileName || "") !== path) iface.loadFile(path)
        }
    }
    Component.onCompleted: iface.logMessage("GeoFlow Launcher 0.1.0 ready")
}
