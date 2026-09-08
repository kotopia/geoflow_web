import QtQuick
import QtCore
import org.qfield
import org.qfield.core

Item {
    id: launcher
    property var ownerSlot: null
    property bool activeOwner: false
    function acquireOwner() {
        let host = iface.mainWindow().contentItem
        for (let i = 0; i < host.children.length; i++) {
            if (host.children[i].objectName === "geoflowLauncherOwnerV1") ownerSlot = host.children[i]
        }
        if (!ownerSlot) ownerSlot = Qt.createQmlObject(
            'import QtQuick; Item { objectName: "geoflowLauncherOwnerV1"; visible: false; property var owner: null }', host)
        if (ownerSlot.owner && ownerSlot.owner !== launcher) return false
        ownerSlot.owner = launcher
        activeOwner = true
        return true
    }
    Timer {
        interval: 2000
        repeat: true
        running: !launcher.activeOwner
        onTriggered: { if (launcher.acquireOwner()) autoRegisterTimer.restart() }
    }
    Timer {
        id: autoRegisterTimer
        interval: 1200
        repeat: false
        onTriggered: launcher.registerCurrent(false)
    }
    Settings {
        id: registry
        category: "GeoFlowLauncherV1"
        property string projectsJson: "{}"
    }
    function log(stage) { iface.logMessage("GeoFlow Launcher 0.1.3 " + stage) }
    function toast(text) { iface.mainWindow().displayToast(text) }
    function normalServer(value) { return String(value || "").replace(/\/+$/, "") }
    function entry(key) { return String(iface.readProjectEntry("GeoFlow", key, "") || "") }
    function key(server, project) { return normalServer(server) + "|" + project }
    function projects() {
        try { return JSON.parse(registry.projectsJson) } catch (e) { return {} }
    }
    // Automatic registration never replaces another existing copy.
    function registerCurrent(explicitChoice) {
        if (!activeOwner) return false
        let project = entry("project_id")
        let server = normalServer(entry("server_url"))
        let path = String(qgisProject.fileName || "")
        if (!project || !server || !path.endsWith("/geoflow-field.qgs") || !QfFileUtils.fileExists(path)) {
            if (explicitChoice) toast("사용할 GeoFlow 프로젝트를 먼저 열어주세요")
            return false
        }
        let map = projects()
        let projectKey = key(server, project)
        let existing = map[projectKey]
        if (!explicitChoice && existing && existing !== path && QfFileUtils.fileExists(existing)) {
            log("automatic registration retained existing copy")
            toast("다른 복사본이 등록되어 있습니다 · 이 복사본을 사용하려면 Launcher에서 직접 등록하세요")
            return false
        }
        if (existing !== path) {
            map[projectKey] = path
            registry.projectsJson = JSON.stringify(map)
            registry.sync()
            log(explicitChoice ? "registered" : "automatically registered")
        }
        if (explicitChoice) toast("현재 프로젝트 등록 완료")
        return true
    }
    function configure() { registerCurrent(true) }
    Connections {
        enabled: launcher.activeOwner
        target: iface
        function onLoadProjectEnded(path, name) { autoRegisterTimer.restart() }
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
                // QField may retain the project while showing its welcome screen.
                // Reveal the existing map without reloading or discarding edits.
                let welcome = iface.findItemByObjectName("welcomeScreen")
                if (welcome && welcome.visible) {
                    welcome.visible = false
                    welcome.focus = false
                    launcher.log("current project welcome screen dismissed")
                }
                launcher.log("registered project already current")
            }
        }
    }
    Component.onCompleted: {
        if (acquireOwner()) { log("ready"); autoRegisterTimer.restart() }
        else log("duplicate launcher suppressed")
    }
    Component.onDestruction: {
        if (ownerSlot && ownerSlot.owner === launcher) ownerSlot.owner = null
    }
}
