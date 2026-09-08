import QtQuick
import QtQuick.Controls as Controls
import QtCore
import org.qfield
import org.qgis
import Theme

Item {
    id: geoflowField
    objectName: "geoflowField"

    property var mainWindow: iface.mainWindow()
    property var mapCanvas: iface.mapCanvas()
    property var positioning: iface.positioning()
    property string serverUrl: ""
    property string projectId: ""
    property string bearerToken: ""
    property string roamingPlanUrl: ""
    property string roamingCellUrl: ""
    property string changesetUrl: ""
    property real movementThresholdM: 100.0
    property bool configReady: false
    property bool requestInFlight: false
    property var changesetRequest: null
    property double changesetStartedAtMs: 0
    property string lastSyncBlock: ""
    property bool syncInFlight: false
    Timer {
        interval: 1000
        repeat: true
        running: geoflowField.syncInFlight
        onTriggered: geoflowField.expireStalledChangeset()
    }
    function expireStalledChangeset() {
        if (!syncInFlight || !changesetRequest || Date.now() - changesetStartedAtMs < 30000) return
        let stalled = changesetRequest
        changesetRequest = null
        syncInFlight = false
        stalled.abort()
        syncStatus = "offline"
        scheduleRetry()
        log("changeset timeout; existing outbox retained for retry")
    }
    function reportSyncBlock(reason) {
        if (lastSyncBlock !== reason) log("sync waiting: " + reason)
        lastSyncBlock = reason
    }
    property bool captureSuppressed: false
    property bool wasOffline: false
    property bool authBlocked: false
    property string syncStatus: "idle"
    property int unsyncedCount: 0
    property int retryAttempt: 0
    property double nextRetryAtMs: 0
    property string lastViewport: ""
    property real lastLon: NaN
    property real lastLat: NaN
    property var layerBindings: []
    property var managedLayerDescriptors: []
    property var pollingBaseline: ({})
    property bool pollingBaselineReady: false

    Settings {
        id: localState
        category: "GeoFlowField/" + geoflowField.projectId
        property string knownCellsCsv: ""
        property string lastLocation: ""
        property string packageTokenFingerprint: ""
    }

    Settings {
        id: durableState
        category: "GeoFlowFieldSync"
        property string projectStatesJson: "{}"
    }

    property string recoverySnapshot: ""
    property var recoveryCandidate: null
    Controls.Dialog {
        id: conflictDialog
        parent: geoflowField.mainWindow.contentItem
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 480)
        modal: true
        title: "QField 편집으로 충돌 복구"
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        contentItem: Controls.Label {
            text: "대상: " + (geoflowField.recoveryCandidate ? geoflowField.recoveryCandidate.summary : "") +
                  "\nQField에 보관한 도형·속성 편집을 서버에 반영합니다. 기존 요청은 복구 이력에 보관합니다. 서버가 다시 변경되면 전송을 중단합니다.\n확인을 누르면 전송합니다."
            wrapMode: Text.WordWrap
        }
        onAccepted: geoflowField.acceptConflictRecovery()
    }

    function buildConflictRecovery(original, newId) {
        let state = JSON.parse(JSON.stringify(original))
        if (!state.outbox || !state.conflict || state.conflict.changeset_id !== state.outbox.changeset_id)
            throw new Error("충돌 요청을 먼저 동기화 버튼으로 재확인하세요")
        let conflicts = state.conflict.conflicts || []
        if (!conflicts.length) throw new Error("충돌 상세가 없습니다 · 동기화 버튼으로 재확인하세요")
        let versions = {}
        for (let row of conflicts) {
            if (row.reason !== "server_object_changed" || !row.server_updated_at)
                throw new Error("자동 복구할 수 없는 충돌입니다 · 기존 변경을 보존했습니다")
            versions[pendingKey(String(row.layer), String(row.id))] = String(row.server_updated_at)
        }
        let changes = []
        for (let sent of state.outbox.changes || []) {
            let key = pendingKey(String(sent.layer), String(sent.id))
            let later = (state.pending || {})[key]
            if (sent.action !== "update" || (later && later.action !== "update"))
                throw new Error("이 복구는 기존 객체 수정만 지원합니다")
            let change = JSON.parse(JSON.stringify(sent))
            if (later) {
                change.attributes = Object.assign({}, change.attributes || {}, later.attributes || {})
                if (later.geometry_wkt) { change.geometry_wkt = later.geometry_wkt; delete change.geometry_wkb }
                if (later.geometry_wkb) { change.geometry_wkb = later.geometry_wkb; delete change.geometry_wkt }
                delete state.pending[key]
            }
            if (versions[key]) { change.base_updated_at = versions[key]; delete versions[key] }
            changes.push(change)
        }
        if (Object.keys(versions).length) throw new Error("충돌 대상과 전송 대상이 일치하지 않습니다")
        if (!changes.length) throw new Error("복구할 편집이 없습니다")
        state.recovery_archive = state.recovery_archive || []
        state.recovery_archive.push({outbox: original.outbox, pending: original.pending, conflict: original.conflict})
        state.outbox = Object.assign({}, state.outbox, {changeset_id: newId, changes: changes})
        state.conflict = null
        return {state: state, summary: changes.map(function(c) { return c.layer + " " + c.id }).join("\n")}
    }

    // QField exposes configure through the project's plugin settings button.
    function configure() {
        if (syncInFlight || hasUncommittedEdits()) { toast("편집을 저장하고 전송이 끝난 뒤 복구하세요"); return }
        if (!sessionAuthorized()) { toast("GeoFlow에서 QField 열기로 먼저 연결하세요"); return }
        try {
            let original = projectState()
            recoveryCandidate = buildConflictRecovery(original, uuidV4())
            recoverySnapshot = JSON.stringify(original)
            conflictDialog.open()
        } catch (err) { toast(String(err.message || err)) }
    }

    function acceptConflictRecovery() {
        if (!recoveryCandidate || syncInFlight || hasUncommittedEdits() || !sessionAuthorized() ||
            JSON.stringify(projectState()) !== recoverySnapshot) {
            toast("확인 중 상태가 변경됐습니다 · 복구를 다시 열어주세요")
            return
        }
        saveProjectState(recoveryCandidate.state)
        durableState.sync()
        if (JSON.stringify(projectState()) !== JSON.stringify(recoveryCandidate.state)) {
            toast("복구 이력 저장을 확인할 수 없어 전송을 중단했습니다")
            return
        }
        clearRetry()
        lastSyncBlock = ""
        log("explicit conflict recovery submitted; original request archived")
        postOutbox(recoveryCandidate.state.outbox, true)
        recoveryCandidate = null
    }

    QfToolButton {
        id: syncButton
        iconSource: Theme.getThemeVectorIcon("ic_cloud_synchronize_24dp")
        iconColor: Theme.toolButtonColor
        bgcolor: Theme.toolButtonBackgroundColor
        round: true
        onClicked: geoflowField.manualSync()
        onPressAndHold: geoflowField.configure()
    }

    Timer {
        id: bootstrapTimer
        interval: 1200
        repeat: false
        running: true
        onTriggered: geoflowField.initializeProject()
    }

    Timer {
        id: roamingTimer
        interval: 8000
        repeat: true
        running: true
        onTriggered: geoflowField.scheduleRoaming(false)
    }

    Timer {
        id: syncTimer
        interval: 3000
        repeat: true
        running: true
        onTriggered: geoflowField.syncNow(false, false)
    }

    Timer {
        id: pollingTimer
        interval: 2000
        repeat: true
        running: true
        onTriggered: geoflowField.pollForLocalChanges(false)
    }

    Timer {
        id: editAcceptedSyncTimer
        interval: 450
        repeat: false
        running: false
        onTriggered: geoflowField.syncNow(false, true)
    }

    Timer {
        id: bindRetryTimer
        interval: 1500
        repeat: true
        running: false
        onTriggered: {
            if (!managedLayerDescriptors || managedLayerDescriptors.length === 0) return
            let count = geoflowField.bindLayers()
            if (count > 0) {
                stop()
                geoflowField.rebuildPollingBaseline()
                geoflowField.toast("GeoFlow Field 0.9.4 · 자동 동기화 준비 " + count + "개 레이어")
            }
        }
    }

    Connections {
        target: iface

        function onLoadProjectEnded(path, name) {
            geoflowField.log("project load ended: " + name)
            geoflowField.lastViewport = ""
            geoflowField.lastLon = NaN
            geoflowField.lastLat = NaN
            geoflowField.authBlocked = false
            geoflowField.managedLayerDescriptors = []
            geoflowField.pollingBaseline = ({})
            geoflowField.pollingBaselineReady = false
            bootstrapTimer.restart()
            roamingTimer.restart()
        }
    }

    function log(message) {
        try { iface.logMessage("GeoFlow Field: " + message) } catch (err) {}
    }

    function toast(message) {
        try { iface.mainWindow().displayToast(message) } catch (err) {}
    }

    function readProjectText(key) {
        let value = ""
        try { value = String(iface.readProjectEntry("GeoFlow", key, "") || "") } catch (err) {}
        if (!value) {
            try { value = String(iface.readProjectEntry("GeoFlow", "/" + key, "") || "") } catch (err2) {}
        }
        return value
    }

    function readProjectNumber(key, fallback) {
        let value = fallback
        try { value = Number(iface.readProjectDoubleEntry("GeoFlow", key, fallback)) } catch (err) {}
        if (!isFinite(value) || value <= 0) {
            try { value = Number(iface.readProjectDoubleEntry("GeoFlow", "/" + key, fallback)) } catch (err2) {}
        }
        if (!isFinite(value) || value <= 0) value = fallback
        return value
    }

    function resetRoamingStateForFreshTicket() {
        let fingerprint = bearerToken ? bearerToken.slice(-24) : ""
        if (!fingerprint) return
        if (localState.packageTokenFingerprint && localState.packageTokenFingerprint === fingerprint) return
        localState.packageTokenFingerprint = fingerprint
        localState.knownCellsCsv = ""
        localState.lastLocation = ""
        lastViewport = ""
        lastLon = NaN
        lastLat = NaN
        log("fresh package ticket detected; roaming cache state reset")
    }

    function reloadProjectConfig() {
        try { mainWindow = iface.mainWindow() } catch (err) {}
        try { mapCanvas = iface.mapCanvas() } catch (err2) {}
        try { positioning = iface.positioning() } catch (err3) {}

        serverUrl = readProjectText("server_url")
        projectId = readProjectText("project_id")
        bearerToken = readProjectText("qfield_token")
        roamingPlanUrl = readProjectText("roaming_plan_url")
        roamingCellUrl = readProjectText("roaming_cell_url")
        movementThresholdM = readProjectNumber("movement_threshold_m", 100.0)
        changesetUrl = roamingPlanUrl.replace(/roaming-plan\/?$/, "changesets/")
        configReady = Boolean(
            serverUrl && projectId && bearerToken && roamingPlanUrl && roamingCellUrl && changesetUrl
        )
        if (configReady) {
            resetRoamingStateForFreshTicket()
            log("project config ready for " + projectId)
        } else {
            log(
                "project config incomplete" +
                " server=" + Boolean(serverUrl) +
                " project=" + Boolean(projectId) +
                " token=" + Boolean(bearerToken) +
                " plan=" + Boolean(roamingPlanUrl) +
                " cell=" + Boolean(roamingCellUrl) +
                " changeset=" + Boolean(changesetUrl)
            )
        }
        return configReady
    }

    function absoluteUrl(path) {
        if (path.indexOf("http://") === 0 || path.indexOf("https://") === 0) return path
        return serverUrl.replace(/\/$/, "") + "/" + path.replace(/^\//, "")
    }

    function uuidV4() {
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {
            let r = Math.floor(Math.random() * 16)
            let v = c === "x" ? r : ((r & 0x3) | 0x8)
            return v.toString(16)
        })
    }

    function canonicalUuid(value) {
        let text = String(value === undefined || value === null ? "" : value).trim()
        return text.replace(/^\{/, "").replace(/\}$/, "").toLowerCase()
    }

    function parseStates() {
        try {
            let value = JSON.parse(durableState.projectStatesJson || "{}")
            return value && typeof value === "object" ? value : {}
        } catch (err) {
            return {}
        }
    }

    function projectState() {
        let states = parseStates()
        let state = states[projectId]
        if (!state || typeof state !== "object") state = {}
        if (!state.client_id) state.client_id = uuidV4()
        if (!state.pending || typeof state.pending !== "object") state.pending = {}
        if (!state.feature_versions || typeof state.feature_versions !== "object") state.feature_versions = {}
        if (state.outbox === undefined) state.outbox = null
        if (state.conflict === undefined) state.conflict = null
        if (state.base_revision === undefined || Number(state.base_revision) < 0) state.base_revision = 0
        return state
    }

    function saveProjectState(state) {
        if (!projectId) return
        let states = parseStates()
        states[projectId] = state
        durableState.projectStatesJson = JSON.stringify(states)
        durableState.sync()
        updateUnsyncedCount(state)
    }

    function updateUnsyncedCount(state) {
        let current = state || projectState()
        let count = Object.keys(current.pending || {}).length
        if (current.outbox && current.outbox.changes) count += current.outbox.changes.length
        unsyncedCount = count
        if (current.conflict) syncStatus = "conflict"
        else if (count > 0 && syncStatus === "idle") syncStatus = "pending"
        else if (count === 0 && syncStatus === "pending") syncStatus = "synced"
    }

    function normalizedValue(value) {
        if (value === undefined || value === null) return null
        let type = typeof value
        if (type === "string" || type === "number" || type === "boolean") return value
        try { if (value.toISOString) return value.toISOString() } catch (err) {}
        return String(value)
    }

    function layerName(layer) {
        try { if (typeof layer.name === "string") return layer.name } catch (err) {}
        try { return String(layer.name()) } catch (err2) {}
        return ""
    }

    function isManagedLayer(layer) {
        if (!layer) return false
        try {
            let fields = layer.fields()
            return fields.indexOf("id") >= 0 && fields.indexOf("project_id") >= 0
        } catch (err) {
            return false
        }
    }

    function managedLayers() {
        let result = []
        let seen = {}

        if (managedLayerDescriptors && managedLayerDescriptors.length > 0) {
            for (let i = 0; i < managedLayerDescriptors.length; i++) {
                let descriptor = managedLayerDescriptors[i] || {}
                let physical = String(descriptor.physical_name || "")
                if (!physical || seen[physical]) continue
                try {
                    let matches = qgisProject.mapLayersByName(physical)
                    if (matches && matches.length > 0) {
                        seen[physical] = true
                        result.push(matches[0])
                    }
                } catch (err) {
                    log("mapLayersByName failed for " + physical + ": " + err)
                }
            }
            if (result.length > 0) return result
        }

        try {
            let rows = mapCanvas.mapSettings.layers
            for (let j = 0; j < rows.length; j++) {
                let layer = rows[j]
                if (!isManagedLayer(layer)) continue
                let name = layerName(layer)
                if (!name || seen[name]) continue
                seen[name] = true
                result.push(layer)
            }
        } catch (err2) {
            log("map canvas layer list unavailable: " + err2)
        }
        return result
    }

    function featureByFid(layer, fid) {
        let iterator = null
        try {
            iterator = LayerUtils.createFeatureIteratorFromExpression(layer, "$id = " + Number(fid))
            if (iterator.hasNext()) return iterator.next()
        } catch (err) {
            log("feature lookup failed: " + err)
        } finally {
            if (iterator) {
                try { iterator.close() } catch (closeErr) {}
            }
        }
        return null
    }

    function fieldName(layer, index) {
        try { return String(layer.fields().at(Number(index)).name()) } catch (err) {}
        return ""
    }

    function featureGeometryWkt(feature) {
        if (!feature) return ""
        try {
            let geometry = feature.geometry()
            if (!geometry || geometry.isNull() || geometry.isEmpty()) return ""
            return String(geometry.asWkt(8))
        } catch (err) {
            log("geometry WKT unavailable: " + err)
            return ""
        }
    }

    function protectedField(name) {
        return ["id", "project_id", "created_at", "updated_at", "created_by", "updated_by"].indexOf(name) >= 0
    }

    function collectAttributes(layer, feature) {
        let attrs = {}
        if (!feature) return attrs
        try {
            let fields = layer.fields()
            for (let i = 0; i < fields.count(); i++) {
                let name = String(fields.at(i).name())
                if (!name || protectedField(name)) continue
                let value = feature.attribute(name)
                if (value === undefined || value === null) continue
                attrs[name] = normalizedValue(value)
            }
        } catch (err) {
            log("attribute collection failed: " + err)
        }
        return attrs
    }

    function featureSignature(layer, feature) {
        return JSON.stringify({
            geometry_wkt: featureGeometryWkt(feature),
            attributes: collectAttributes(layer, feature)
        })
    }

    function pendingKey(changeOrLayer, objectId) {
        if (typeof changeOrLayer === "object") {
            return String(changeOrLayer.layer) + "|" + String(changeOrLayer.id)
        }
        return String(changeOrLayer) + "|" + String(objectId)
    }

    function featureBaseUpdatedAt(binding, feature, objectId) {
        let state = projectState()
        let key = pendingKey(binding.standard, objectId)
        if (state.feature_versions[key]) return String(state.feature_versions[key])
        if (feature) {
            try {
                let idx = binding.layer.fields().indexOf("updated_at")
                if (idx >= 0) {
                    let value = normalizedValue(feature.attribute("updated_at"))
                    if (value) return String(value)
                }
            } catch (err) {}
        }
        return ""
    }

    function refreshFidMap(binding) {
        binding.fidMap = {}
        binding.versionMap = {}
        let iterator = null
        try {
            iterator = LayerUtils.createFeatureIterator(binding.layer)
            while (iterator.hasNext()) {
                let feature = iterator.next()
                let objectId = canonicalUuid(feature.attribute("id"))
                if (!objectId) continue
                binding.fidMap[String(feature.id())] = objectId
                binding.versionMap[String(feature.id())] = featureBaseUpdatedAt(binding, feature, objectId)
            }
        } catch (err) {
            log(binding.standard + " fid map failed: " + err)
        } finally {
            if (iterator) {
                try { iterator.close() } catch (closeErr) {}
            }
        }
    }

    function rebuildPollingBaseline() {
        if (layerBindings.length === 0) return 0
        let baseline = ({})
        let total = 0
        for (let i = 0; i < layerBindings.length; i++) {
            let binding = layerBindings[i]
            let iterator = null
            try {
                iterator = LayerUtils.createFeatureIterator(binding.layer)
                while (iterator.hasNext()) {
                    let feature = iterator.next()
                    let objectId = canonicalUuid(feature.attribute("id"))
                    if (!objectId) continue
                    let key = pendingKey(binding.standard, objectId)
                    baseline[key] = {
                        signature: featureSignature(binding.layer, feature),
                        base_updated_at: featureBaseUpdatedAt(binding, feature, objectId)
                    }
                    total += 1
                }
            } catch (err) {
                log(binding.standard + " polling baseline failed: " + err)
            } finally {
                if (iterator) {
                    try { iterator.close() } catch (closeErr) {}
                }
            }
        }
        pollingBaseline = baseline
        pollingBaselineReady = true
        log("polling baseline ready count=" + total)
        return total
    }

    function seedPollingBaselineForMissing() {
        if (!pollingBaselineReady) return rebuildPollingBaseline()
        let seeded = 0
        for (let i = 0; i < layerBindings.length; i++) {
            let binding = layerBindings[i]
            let iterator = null
            try {
                iterator = LayerUtils.createFeatureIterator(binding.layer)
                while (iterator.hasNext()) {
                    let feature = iterator.next()
                    let objectId = canonicalUuid(feature.attribute("id"))
                    if (!objectId) continue
                    let key = pendingKey(binding.standard, objectId)
                    if (pollingBaseline[key]) continue
                    pollingBaseline[key] = {
                        signature: featureSignature(binding.layer, feature),
                        base_updated_at: featureBaseUpdatedAt(binding, feature, objectId)
                    }
                    seeded += 1
                }
            } catch (err) {
                log(binding.standard + " polling seed failed: " + err)
            } finally {
                if (iterator) {
                    try { iterator.close() } catch (closeErr) {}
                }
            }
        }
        if (seeded > 0) log("polling baseline seeded new server objects=" + seeded)
        return seeded
    }

    function pollForLocalChanges(force) {
        if (!configReady || captureSuppressed || syncInFlight || authBlocked) return
        if (requestInFlight && !force) return
        if (layerBindings.length === 0) {
            if (managedLayerDescriptors.length > 0) bindLayers()
            return
        }
        if (!pollingBaselineReady) {
            rebuildPollingBaseline()
            return
        }

        let changed = false
        for (let i = 0; i < layerBindings.length; i++) {
            let binding = layerBindings[i]
            let iterator = null
            try {
                iterator = LayerUtils.createFeatureIterator(binding.layer)
                while (iterator.hasNext()) {
                    let feature = iterator.next()
                    let objectId = canonicalUuid(feature.attribute("id"))
                    if (!objectId) continue
                    let key = pendingKey(binding.standard, objectId)
                    let signature = featureSignature(binding.layer, feature)
                    let old = pollingBaseline[key]
                    if (!old) {
                        pollingBaseline[key] = {
                            signature: signature,
                            base_updated_at: featureBaseUpdatedAt(binding, feature, objectId)
                        }
                        continue
                    }
                    if (old.signature !== signature) {
                        let geometryWkt = featureGeometryWkt(feature)
                        let update = {
                            action: "update",
                            layer: binding.standard,
                            id: objectId,
                            attributes: collectAttributes(binding.layer, feature)
                        }
                        if (geometryWkt) update.geometry_wkt = geometryWkt
                        if (old.base_updated_at) update.base_updated_at = old.base_updated_at
                        queueChange(update)
                        changed = true
                        log("poll detected update " + binding.standard + " " + objectId)
                    }
                    pollingBaseline[key] = {
                        signature: signature,
                        base_updated_at: old.base_updated_at || featureBaseUpdatedAt(binding, feature, objectId)
                    }
                }
            } catch (err) {
                log(binding.standard + " polling failed: " + err)
            } finally {
                if (iterator) {
                    try { iterator.close() } catch (closeErr) {}
                }
            }
        }

        // Never infer deletes from iterator absence. QField may temporarily hide
        // cached/provider features while editing or refreshing. Deletes are sent
        // only from the explicit featureDeleted signal path.
        if (changed) syncNow(false, true)
    }

    function ensureFeatureIdentity(binding, fid) {
        let feature = featureByFid(binding.layer, fid)
        if (!feature) return null
        let objectId = canonicalUuid(feature.attribute("id"))
        let projectValue = canonicalUuid(feature.attribute("project_id"))
        let fields = binding.layer.fields()

        captureSuppressed = true
        try {
            if (!objectId) {
                objectId = uuidV4()
                let idIndex = fields.indexOf("id")
                if (idIndex >= 0) binding.layer.changeAttributeValue(fid, idIndex, objectId)
            } else if (String(feature.attribute("id")) !== objectId) {
                let canonicalIndex = fields.indexOf("id")
                if (canonicalIndex >= 0) binding.layer.changeAttributeValue(fid, canonicalIndex, objectId)
            }
            if (!projectValue && projectId) {
                let projectIndex = fields.indexOf("project_id")
                if (projectIndex >= 0) binding.layer.changeAttributeValue(fid, projectIndex, projectId)
            }
        } finally {
            captureSuppressed = false
        }
        let refreshed = featureByFid(binding.layer, fid) || feature
        binding.fidMap[String(fid)] = objectId
        if (binding.versionMap[String(fid)] === undefined) {
            binding.versionMap[String(fid)] = featureBaseUpdatedAt(binding, refreshed, objectId)
        }
        return { id: objectId, feature: refreshed }
    }

    function queueChange(change) {
        if (!projectId || !change || !change.id || !change.layer) return
        let state = projectState()
        let pending = state.pending
        let key = pendingKey(change)
        let old = pending[key]

        if (!old) {
            pending[key] = change
        } else if (old.action === "create" && change.action === "delete") {
            delete pending[key]
        } else if (change.action === "delete") {
            let baseUpdatedAt = old.base_updated_at || change.base_updated_at || ""
            pending[key] = { action: "delete", layer: change.layer, id: change.id }
            if (baseUpdatedAt) pending[key].base_updated_at = baseUpdatedAt
        } else if (old.action === "create") {
            old.attributes = Object.assign({}, old.attributes || {}, change.attributes || {})
            if (change.geometry_wkt) old.geometry_wkt = change.geometry_wkt
            pending[key] = old
        } else if (old.action === "update" && change.action === "update") {
            old.attributes = Object.assign({}, old.attributes || {}, change.attributes || {})
            if (change.geometry_wkt) old.geometry_wkt = change.geometry_wkt
            if (!old.base_updated_at && change.base_updated_at) old.base_updated_at = change.base_updated_at
            pending[key] = old
        } else {
            pending[key] = change
        }
        state.pending = pending
        saveProjectState(state)
        syncStatus = "pending"
        log("queued " + change.action + " " + change.layer + " " + change.id)
    }

    function captureCreate(binding, fid) {
        if (captureSuppressed) return
        let identity = ensureFeatureIdentity(binding, fid)
        if (!identity || !identity.id) return
        let geometryWkt = featureGeometryWkt(identity.feature)
        if (!geometryWkt) return
        queueChange({
            action: "create",
            layer: binding.standard,
            id: identity.id,
            attributes: collectAttributes(binding.layer, identity.feature),
            geometry_wkt: geometryWkt
        })
    }

    function captureAttribute(binding, fid, index, value) {
        if (captureSuppressed) return
        let name = fieldName(binding.layer, index)
        if (!name || protectedField(name)) return
        let identity = ensureFeatureIdentity(binding, fid)
        if (!identity || !identity.id) return
        let attrs = {}
        attrs[name] = normalizedValue(value)
        let change = { action: "update", layer: binding.standard, id: identity.id, attributes: attrs }
        let baseUpdatedAt = binding.versionMap[String(fid)] || featureBaseUpdatedAt(binding, identity.feature, identity.id)
        if (baseUpdatedAt) change.base_updated_at = baseUpdatedAt
        queueChange(change)
    }

    function captureGeometry(binding, fid, geometry) {
        if (captureSuppressed) return
        let identity = ensureFeatureIdentity(binding, fid)
        if (!identity || !identity.id) return
        let wkt = ""
        try {
            if (geometry && !geometry.isNull() && !geometry.isEmpty()) wkt = String(geometry.asWkt(8))
        } catch (err) {
            wkt = featureGeometryWkt(identity.feature)
        }
        if (!wkt) return
        let change = { action: "update", layer: binding.standard, id: identity.id, geometry_wkt: wkt }
        let baseUpdatedAt = binding.versionMap[String(fid)] || featureBaseUpdatedAt(binding, identity.feature, identity.id)
        if (baseUpdatedAt) change.base_updated_at = baseUpdatedAt
        queueChange(change)
    }

    function captureDelete(binding, fid) {
        if (captureSuppressed) return
        let objectId = canonicalUuid(binding.fidMap[String(fid)] || "")
        if (!objectId) {
            log(binding.standard + " delete skipped: UUID not found for fid " + fid)
            return
        }
        let change = { action: "delete", layer: binding.standard, id: objectId }
        let baseUpdatedAt = binding.versionMap[String(fid)] || ""
        if (baseUpdatedAt) change.base_updated_at = baseUpdatedAt
        queueChange(change)
        delete binding.fidMap[String(fid)]
        delete binding.versionMap[String(fid)]
    }

    function unbindLayers() {
        for (let i = 0; i < layerBindings.length; i++) {
            let b = layerBindings[i]
            try { b.layer.featureAdded.disconnect(b.added) } catch (err) {}
            try { b.layer.attributeValueChanged.disconnect(b.attribute) } catch (err2) {}
            try { b.layer.geometryChanged.disconnect(b.geometry) } catch (err3) {}
            try { b.layer.featureDeleted.disconnect(b.deleted) } catch (err4) {}
            try { b.layer.editingStopped.disconnect(b.stopped) } catch (err5) {}
            try { b.layer.editCommandEnded.disconnect(b.commandEnded) } catch (err6) {}
            try { b.layer.afterCommitChanges.disconnect(b.committed) } catch (err7) {}
        }
        layerBindings = []
    }

    function standardNameForPhysical(physical) {
        let target = String(physical || "")
        for (let i = 0; i < managedLayerDescriptors.length; i++) {
            let row = managedLayerDescriptors[i] || {}
            if (String(row.physical_name || "") === target) {
                return String(row.standard_name || target).toUpperCase()
            }
        }
        return target.toUpperCase()
    }

    function bindLayers() {
        unbindLayers()
        let layers = managedLayers()
        let bindings = []
        for (let i = 0; i < layers.length; i++) {
            let layer = layers[i]
            let physicalName = layerName(layer)
            let binding = {
                layer: layer,
                standard: standardNameForPhysical(physicalName),
                fidMap: {},
                versionMap: {}
            }
            refreshFidMap(binding)
            binding.added = function(fid) { geoflowField.captureCreate(binding, fid) }
            binding.attribute = function(fid, index, value) { geoflowField.captureAttribute(binding, fid, index, value) }
            binding.geometry = function(fid, geometry) { geoflowField.captureGeometry(binding, fid, geometry) }
            binding.deleted = function(fid) { geoflowField.captureDelete(binding, fid) }
            binding.stopped = function() {
                geoflowField.refreshFidMap(binding)
                geoflowField.syncNow(false, true)
            }
            binding.commandEnded = function() {
                geoflowField.log(binding.standard + " edit command accepted")
                editAcceptedSyncTimer.restart()
            }
            binding.committed = function() {
                geoflowField.refreshFidMap(binding)
                geoflowField.syncNow(false, true)
            }
            try {
                layer.featureAdded.connect(binding.added)
                layer.attributeValueChanged.connect(binding.attribute)
                layer.geometryChanged.connect(binding.geometry)
                layer.featureDeleted.connect(binding.deleted)
                layer.editingStopped.connect(binding.stopped)
                try { layer.editCommandEnded.connect(binding.commandEnded) } catch (commandErr) {
                    log(binding.standard + " editCommandEnded unavailable: " + commandErr)
                }
                try { layer.afterCommitChanges.connect(binding.committed) } catch (commitErr) {
                    log(binding.standard + " afterCommitChanges unavailable: " + commitErr)
                }
                bindings.push(binding)
            } catch (err) {
                log(binding.standard + " listener bind failed: " + err)
            }
        }
        layerBindings = bindings
        log("edit listeners ready: " + layerBindings.length)
        return layerBindings.length
    }

    function hasUncommittedEdits() {
        for (let i = 0; i < layerBindings.length; i++) {
            try { if (layerBindings[i].layer.isModified()) return true } catch (err) {}
        }
        return false
    }

    function makeOutbox(state) {
        let keys = Object.keys(state.pending || {})
        if (keys.length === 0) return null
        let changes = []
        for (let i = 0; i < keys.length; i++) changes.push(state.pending[keys[i]])
        let payload = {
            protocol: "geoflow_qfield_changeset_v2",
            client_id: state.client_id || uuidV4(),
            changeset_id: uuidV4(),
            base_revision: Number(state.base_revision || 0),
            changes: changes
        }
        state.client_id = payload.client_id
        state.outbox = payload
        state.pending = {}
        saveProjectState(state)
        return payload
    }

    function scheduleRetry() {
        retryAttempt += 1
        let delay = Math.min(3000 * Math.pow(2, Math.min(retryAttempt - 1, 5)), 60000)
        nextRetryAtMs = Date.now() + delay
    }

    function clearRetry() {
        retryAttempt = 0
        nextRetryAtMs = 0
    }

    function applyServerVersions(state, response, sentPayload) {
        let applied = response.applied || []
        for (let i = 0; i < applied.length; i++) {
            let row = applied[i]
            let key = pendingKey(String(row.layer || ""), String(row.id || ""))
            if (row.action === "delete") {
                delete state.feature_versions[key]
            } else if (row.updated_at) {
                state.feature_versions[key] = String(row.updated_at)
                // Advance only a successor based on this exact acknowledged edit.
                // Never change a frozen outbox or adopt a later server version.
                let pending = (state.pending || {})[key]
                if (response.version_receipt === true && pending && sentPayload) {
                    for (let sent of sentPayload.changes || []) {
                        if (pendingKey(String(sent.layer || ""), String(sent.id || "")) === key &&
                            String(pending.base_updated_at || "") === String(sent.base_updated_at || "") &&
                            String(sent.base_updated_at || "") !== "") {
                            pending.base_updated_at = String(row.updated_at)
                        }
                    }
                }
            }
        }
    }

    function postOutbox(payload, manual) {
        syncInFlight = true
        syncStatus = "syncing"
        let xhr = new XMLHttpRequest()
        changesetRequest = xhr
        changesetStartedAtMs = Date.now()
        let url = absoluteUrl(changesetUrl)
        log("POST changeset count=" + payload.changes.length + " url=" + url)
        xhr.open("POST", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Content-Type", "application/json; charset=utf-8")
        xhr.setRequestHeader("Authorization", "Bearer " + bearerToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (changesetRequest !== xhr) return
            changesetRequest = null
            syncInFlight = false

            if (xhr.status >= 200 && xhr.status < 300) {
                let response = null
                try { response = JSON.parse(xhr.responseText) } catch (parseErr) {}
                if (!response || !response.ok) {
                    syncStatus = "error"
                    scheduleRetry()
                    log("invalid changeset response")
                    if (manual) toast("GeoFlow 동기화 응답을 해석하지 못했습니다")
                    return
                }
                let state = projectState()
                if (state.outbox && state.outbox.changeset_id === payload.changeset_id) {
                    state.outbox = null
                    state.conflict = null
                    state.base_revision = Number(response.current_revision || state.base_revision || 0)
                    applyServerVersions(state, response, payload)
                    saveProjectState(state)
                }
                let recovered = wasOffline
                wasOffline = false
                authBlocked = false
                syncStatus = "synced"
                clearRetry()
                rebuildPollingBaseline()
                if (recovered) {
                    toast("GeoFlow 재연결 · 보관된 변경사항 자동 동기화 완료")
                } else if (manual || Number(response.total || 0) > 0) {
                    toast(
                        "GeoFlow 서버 반영 완료 · " +
                        Number(response.total || 0) + "건" +
                        " (revision " + Number(response.current_revision || 0) + ")"
                    )
                }
                log("changeset applied revision=" + response.current_revision)
                return
            }

            if (xhr.status === 0) {
                wasOffline = true
                syncStatus = "offline"
                scheduleRetry()
                log("offline; Changeset retained for retry")
                if (manual) toast("오프라인입니다 · 변경사항 " + unsyncedCount + "건을 보관했습니다")
                return
            }

            let message = "HTTP " + xhr.status
            let errorPayload = null
            try {
                errorPayload = JSON.parse(xhr.responseText)
                message = errorPayload.message || errorPayload.error || message
            } catch (err) {}
            log("changeset failed: " + message)

            if (xhr.status === 401) {
                authBlocked = true
                syncStatus = "auth_required"
                toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다 · 프로젝트를 다시 연결하세요")
                return
            }
            if (xhr.status === 403) {
                authBlocked = true
                syncStatus = "permission_denied"
                toast("GeoFlow QField 쓰기 권한을 확인할 수 없습니다 · GeoFlow 프로젝트 권한을 확인하세요")
                return
            }
            if (xhr.status === 409) {
                let state = projectState()
                state.conflict = {
                    changeset_id: payload.changeset_id,
                    message: message,
                    conflicts: errorPayload && errorPayload.conflicts ? errorPayload.conflicts : []
                }
                saveProjectState(state)
                for (let detail of state.conflict.conflicts) {
                    log("conflict detail layer=" + String(detail.layer || "") + " reason=" + String(detail.reason || "unknown"))
                }
                syncStatus = "conflict"
                toast("GeoFlow 동기화 충돌 · 서버 변경과 겹쳐 자동 전송을 중단했습니다")
                return
            }

            syncStatus = "error"
            scheduleRetry()
            if (manual) toast("GeoFlow 서버 반영 실패: " + message)
        }
        xhr.send(JSON.stringify(payload))
    }

    function syncNow(manual, acceptedEdit) {
        if (syncInFlight || authBlocked) { reportSyncBlock(syncInFlight ? "request in flight" : "authentication"); return }
        if (!manual && nextRetryAtMs > 0 && Date.now() < nextRetryAtMs) return
        if (!configReady && !reloadProjectConfig()) {
            if (manual) toast("GeoFlow 프로젝트 연결 정보가 없습니다")
            return
        }
        if (layerBindings.length === 0 && managedLayerDescriptors.length > 0) bindLayers()
        if (hasUncommittedEdits() && !acceptedEdit) {
            reportSyncBlock("uncommitted edits")
            if (manual) toast("현재 편집을 저장한 뒤 동기화하세요")
            return
        }

        let state = projectState()
        updateUnsyncedCount(state)
        if (state.conflict) {
            // Recheck the identical frozen request only on explicit user action.
            // The server returns its receipt or preserves a genuine conflict.
            if (manual && state.outbox) {
                log("rechecking retained conflict changeset")
                postOutbox(state.outbox, true)
                return
            }
            reportSyncBlock("conflict requires review")
            syncStatus = "conflict"
            if (manual) toast("GeoFlow 충돌이 보류 중입니다 · 기존 변경을 보존했습니다")
            return
        }
        lastSyncBlock = ""
        let payload = state.outbox
        if (!payload) payload = makeOutbox(state)
        if (!payload) {
            syncStatus = "synced"
            if (manual) toast("GeoFlow: 동기화할 로컬 변경이 없습니다")
            return
        }
        postOutbox(payload, manual)
    }

    function authGet(path, callback, quiet) {
        let xhr = new XMLHttpRequest()
        let url = absoluteUrl(path)
        xhr.open("GET", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Authorization", "Bearer " + bearerToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status < 200 || xhr.status >= 300) {
                requestInFlight = false
                let serverMessage = ""
                try {
                    let body = JSON.parse(xhr.responseText)
                    serverMessage = String(body.message || body.error || body.detail || "")
                } catch (parseErr) {}
                log("HTTP " + xhr.status + " " + url + (serverMessage ? " " + serverMessage : ""))
                if (!quiet && xhr.status === 401) {
                    toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다")
                } else if (!quiet && xhr.status === 403) {
                    toast("GeoFlow QField 읽기 권한이 거부되었습니다" + (serverMessage ? " · " + serverMessage : ""))
                } else if (!quiet && xhr.status !== 0) {
                    toast("GeoFlow 수신 실패: HTTP " + xhr.status)
                }
                return
            }
            try { callback(JSON.parse(xhr.responseText)) }
            catch (e) {
                requestInFlight = false
                log("JSON parse failed: " + e)
                if (!quiet) toast("GeoFlow 응답 해석 실패")
            }
        }
        xhr.send()
    }

    function viewportText() {
        if (!mapCanvas || !mapCanvas.mapSettings) return ""
        let e = mapCanvas.mapSettings.visibleExtent
        if (!e) return ""
        try { return [e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()].join(",") }
        catch (err) {
            log("viewport unavailable: " + err)
            return ""
        }
    }

    function currentPosition() {
        if (!positioning || !positioning.active) return null
        let info = positioning.positionInformation
        if (!info || !info.longitudeValid || !info.latitudeValid) return null
        return { lon: Number(info.longitude), lat: Number(info.latitude) }
    }

    function distanceMeters(lon1, lat1, lon2, lat2) {
        let rad = Math.PI / 180.0
        let x = (lon2 - lon1) * rad * Math.cos((lat1 + lat2) * 0.5 * rad)
        let y = (lat2 - lat1) * rad
        return Math.sqrt(x * x + y * y) * 6378137.0
    }

    function knownCells() {
        if (!localState.knownCellsCsv) return []
        return localState.knownCellsCsv.split(",").filter(function(v) { return v.length > 0 })
    }

    function rememberCell(key) {
        let rows = knownCells()
        if (rows.indexOf(key) < 0) rows.push(key)
        if (rows.length > 2000) rows = rows.slice(rows.length - 2000)
        localState.knownCellsCsv = rows.join(",")
    }

    function scheduleRoaming(force) {
        if (requestInFlight || !configReady) return
        let viewport = viewportText()
        let pos = currentPosition()
        let moved = false
        if (pos) moved = isNaN(lastLon) || distanceMeters(lastLon, lastLat, pos.lon, pos.lat) >= movementThresholdM
        if (!force && !moved && viewport === lastViewport) return

        let query = []
        if (pos) {
            query.push("lon=" + encodeURIComponent(pos.lon))
            query.push("lat=" + encodeURIComponent(pos.lat))
        }
        if (viewport) query.push("viewport=" + encodeURIComponent(viewport))
        let known = knownCells()
        if (known.length) query.push("known=" + encodeURIComponent(known.join(",")))
        if (!pos && !viewport) return

        requestInFlight = true
        lastViewport = viewport
        if (pos) {
            lastLon = pos.lon
            lastLat = pos.lat
            localState.lastLocation = pos.lon + "," + pos.lat
        }
        authGet(roamingPlanUrl + "?" + query.join("&"), function(plan) {
            if (!plan.ok || !plan.roaming) {
                requestInFlight = false
                return
            }

            managedLayerDescriptors = plan.layers || []
            let bound = bindLayers()
            if (bound === 0 && managedLayerDescriptors.length > 0) {
                bindRetryTimer.restart()
            } else if (force) {
                toast("GeoFlow Field 0.9.4 · 자동 동기화 준비 " + bound + "개 레이어")
            }

            let state = projectState()
            if (!state.outbox && Object.keys(state.pending || {}).length === 0 && Number(state.base_revision || 0) === 0) {
                state.base_revision = Number(plan.current_revision || 0)
                saveProjectState(state)
            }
            fetchCells(plan.roaming.cells || [], 0, 0, force)
        }, !force)
    }

    function fetchCells(cells, index, featureTotal, manual) {
        if (index >= cells.length) {
            requestInFlight = false
            if (cells.length > 0) {
                if (manual) toast("GeoFlow 영역 갱신: " + cells.length + "셀 / " + featureTotal + "객체")
                mapCanvas.refresh()
                let count = bindLayers()
                if (count === 0 && managedLayerDescriptors.length > 0) bindRetryTimer.restart()
                else seedPollingBaselineForMissing()
            } else {
                seedPollingBaselineForMissing()
                if (manual) toast("GeoFlow 영역 최신 상태")
            }
            return
        }
        let cell = cells[index]
        authGet(cell.url, function(payload) {
            let merged = mergeCell(payload)
            if (merged.complete) rememberCell(cell.key)
            fetchCells(cells, index + 1, featureTotal + merged.count, manual)
        }, !manual)
    }

    function featureExists(layer, objectId) {
        let escaped = String(objectId).replace(/'/g, "''")
        let iterator = LayerUtils.createFeatureIteratorFromExpression(layer, "\"id\" = '" + escaped + "'")
        let exists = iterator.hasNext()
        iterator.close()
        return exists
    }

    function mergeCell(payload) {
        let count = 0
        let complete = true
        if (!payload || !payload.ok) return { count: 0, complete: false }
        let layers = payload.layers || []
        captureSuppressed = true
        try {
            for (let i = 0; i < layers.length; i++) {
                let row = layers[i]
                if (row.truncated) complete = false
                let matches = qgisProject.mapLayersByName(row.physical_name)
                if (!matches || matches.length === 0) continue
                let layer = matches[0]
                let features = row.features || []
                for (let j = 0; j < features.length; j++) {
                    let incoming = features[j]
                    if (!incoming.id || featureExists(layer, incoming.id)) continue
                    let geometry = GeometryUtils.createGeometryFromWkt(incoming.geometry_wkt || "")
                    if (!geometry || geometry.isNull() || geometry.isEmpty()) continue
                    let feature = FeatureUtils.createFeature(layer, geometry)
                    let attrs = incoming.properties || {}
                    for (let name in attrs) {
                        if (!Object.prototype.hasOwnProperty.call(attrs, name)) continue
                        try { feature.setAttribute(name, attrs[name]) } catch (err) {}
                    }
                    try {
                        if (LayerUtils.addFeature(layer, feature)) count += 1
                    } catch (addErr) {
                        log("roaming addFeature unavailable: " + addErr)
                    }
                }
            }
        } finally {
            captureSuppressed = false
        }
        return { count: count, complete: complete }
    }

    function manualSync() {
        authBlocked = false
        log("manual sync requested")
        pollForLocalChanges(true)
        syncNow(true, true)
        scheduleRoaming(true)
    }

    function initializeProject() {
        if (!reloadProjectConfig()) {
            toast("GeoFlow Field 연결 정보를 읽지 못했습니다")
            return
        }
        updateUnsyncedCount(projectState())
        toast("GeoFlow Field 0.9.4 연결됨 · 서버 레이어 확인 중")
        scheduleRoaming(true)
        syncNow(false, false)
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(syncButton)
        log("plugin 0.9.4 component completed")
        bootstrapTimer.restart()
    }

    Component.onDestruction: {
        pollingTimer.stop()
        editAcceptedSyncTimer.stop()
        bindRetryTimer.stop()
        unbindLayers()
        try { iface.removeItemFromPluginsToolbar(syncButton) } catch (err) {}
    }
}
