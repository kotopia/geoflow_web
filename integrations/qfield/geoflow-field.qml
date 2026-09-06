import QtQuick
import QtCore
import org.qfield.org
import org.qfield.core
import org.qfield.gui

Item {
    id: geoflowField
    objectName: "geoflowField"

    property var mainWindow: iface.mainWindow()
    property var mapCanvas: iface.mapCanvas()
    property string serverUrl: ""
    property string projectId: ""
    property string bearerToken: ""
    property string changesetUrl: ""
    property bool configReady: false
    property bool syncInFlight: false
    property bool captureSuppressed: false
    property var layerBindings: []

    Settings {
        id: durableState
        category: "GeoFlowFieldSync"
        property string projectStatesJson: "{}"
    }

    QfToolButton {
        id: syncButton
        iconSource: Theme.getThemeVectorIcon("ic_sync_white_24dp")
        iconColor: Theme.toolButtonColor
        bgcolor: Theme.toolButtonBackgroundColor
        round: true
        onClicked: geoflowField.syncNow(true)
    }

    Timer {
        id: bootstrapTimer
        interval: 1000
        repeat: false
        running: true
        onTriggered: geoflowField.initializeProject()
    }

    Timer {
        id: syncTimer
        interval: 3000
        repeat: true
        running: true
        onTriggered: geoflowField.syncNow(false)
    }

    Connections {
        target: iface

        function onLoadProjectEnded(path, name) {
            geoflowField.log("project load ended: " + name)
            bootstrapTimer.restart()
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

    function reloadProjectConfig() {
        serverUrl = readProjectText("server_url")
        projectId = readProjectText("project_id")
        bearerToken = readProjectText("qfield_token")
        let roamingPlanUrl = readProjectText("roaming_plan_url")
        changesetUrl = roamingPlanUrl.replace(/roaming-plan\/?$/, "changesets/")
        configReady = Boolean(serverUrl && projectId && bearerToken && changesetUrl)
        if (!configReady) {
            log(
                "project config incomplete" +
                " server=" + Boolean(serverUrl) +
                " project=" + Boolean(projectId) +
                " token=" + Boolean(bearerToken) +
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
        text = text.replace(/^\{/, "").replace(/\}$/, "").toLowerCase()
        return text
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
        if (state.outbox === undefined) state.outbox = null
        if (state.base_revision === undefined || Number(state.base_revision) < 0) state.base_revision = 0
        return state
    }

    function saveProjectState(state) {
        if (!projectId) return
        let states = parseStates()
        states[projectId] = state
        durableState.projectStatesJson = JSON.stringify(states)
    }

    function normalizedValue(value) {
        if (value === undefined || value === null) return null
        let type = typeof value
        if (type === "string" || type === "number" || type === "boolean") return value
        try {
            if (value.toISOString) return value.toISOString()
        } catch (err) {}
        return String(value)
    }

    function layerName(layer) {
        try {
            if (typeof layer.name === "string") return layer.name
        } catch (err) {}
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
        try {
            let byId = qgisProject.mapLayers()
            for (let key in byId) {
                if (!Object.prototype.hasOwnProperty.call(byId, key)) continue
                let layer = byId[key]
                if (!isManagedLayer(layer)) continue
                let name = layerName(layer)
                if (!name || seen[name]) continue
                seen[name] = true
                result.push(layer)
            }
        } catch (err) {
            log("qgisProject.mapLayers unavailable: " + err)
        }
        if (result.length > 0) return result

        try {
            let rows = mapCanvas.mapSettings.layers
            for (let i = 0; i < rows.length; i++) {
                let layer = rows[i]
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
            iterator = QfLayerUtils.createFeatureIteratorFromExpression(layer, "$id = " + Number(fid))
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

    function refreshFidMap(binding) {
        binding.fidMap = {}
        let iterator = null
        try {
            iterator = QfLayerUtils.createFeatureIterator(binding.layer)
            while (iterator.hasNext()) {
                let feature = iterator.next()
                let objectId = canonicalUuid(feature.attribute("id"))
                if (objectId) binding.fidMap[String(feature.id())] = objectId
            }
        } catch (err) {
            log(binding.standard + " fid map failed: " + err)
        } finally {
            if (iterator) {
                try { iterator.close() } catch (closeErr) {}
            }
        }
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
        binding.fidMap[String(fid)] = objectId
        return { id: objectId, feature: featureByFid(binding.layer, fid) || feature }
    }

    function pendingKey(change) {
        return String(change.layer) + "|" + String(change.id)
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
            pending[key] = { action: "delete", layer: change.layer, id: change.id }
        } else if (old.action === "create") {
            old.attributes = Object.assign({}, old.attributes || {}, change.attributes || {})
            if (change.geometry_wkt) old.geometry_wkt = change.geometry_wkt
            pending[key] = old
        } else if (old.action === "update" && change.action === "update") {
            old.attributes = Object.assign({}, old.attributes || {}, change.attributes || {})
            if (change.geometry_wkt) old.geometry_wkt = change.geometry_wkt
            pending[key] = old
        } else {
            pending[key] = change
        }
        state.pending = pending
        saveProjectState(state)
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
        queueChange({ action: "update", layer: binding.standard, id: identity.id, attributes: attrs })
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
        queueChange({ action: "update", layer: binding.standard, id: identity.id, geometry_wkt: wkt })
    }

    function captureDelete(binding, fid) {
        if (captureSuppressed) return
        let objectId = canonicalUuid(binding.fidMap[String(fid)] || "")
        if (!objectId) {
            log(binding.standard + " delete skipped: UUID not found for fid " + fid)
            return
        }
        queueChange({ action: "delete", layer: binding.standard, id: objectId })
        delete binding.fidMap[String(fid)]
    }

    function unbindLayers() {
        for (let i = 0; i < layerBindings.length; i++) {
            let b = layerBindings[i]
            try { b.layer.featureAdded.disconnect(b.added) } catch (err) {}
            try { b.layer.attributeValueChanged.disconnect(b.attribute) } catch (err2) {}
            try { b.layer.geometryChanged.disconnect(b.geometry) } catch (err3) {}
            try { b.layer.featureDeleted.disconnect(b.deleted) } catch (err4) {}
            try { b.layer.editingStopped.disconnect(b.stopped) } catch (err5) {}
        }
        layerBindings = []
    }

    function bindLayers() {
        unbindLayers()
        let layers = managedLayers()
        let bindings = []
        for (let i = 0; i < layers.length; i++) {
            let layer = layers[i]
            let binding = {
                layer: layer,
                standard: layerName(layer).toUpperCase(),
                fidMap: {}
            }
            refreshFidMap(binding)
            binding.added = function(fid) { geoflowField.captureCreate(binding, fid) }
            binding.attribute = function(fid, index, value) { geoflowField.captureAttribute(binding, fid, index, value) }
            binding.geometry = function(fid, geometry) { geoflowField.captureGeometry(binding, fid, geometry) }
            binding.deleted = function(fid) { geoflowField.captureDelete(binding, fid) }
            binding.stopped = function() {
                geoflowField.refreshFidMap(binding)
                geoflowField.syncNow(false)
            }
            try {
                layer.featureAdded.connect(binding.added)
                layer.attributeValueChanged.connect(binding.attribute)
                layer.geometryChanged.connect(binding.geometry)
                layer.featureDeleted.connect(binding.deleted)
                layer.editingStopped.connect(binding.stopped)
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
            try {
                if (layerBindings[i].layer.isModified()) return true
            } catch (err) {}
        }
        return false
    }

    function pendingCount(state) {
        return Object.keys((state || projectState()).pending || {}).length
    }

    function makeOutbox(state) {
        let keys = Object.keys(state.pending || {})
        if (keys.length === 0) return null
        let changes = []
        for (let i = 0; i < keys.length; i++) changes.push(state.pending[keys[i]])
        let payload = {
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

    function postOutbox(payload, manual) {
        syncInFlight = true
        let xhr = new XMLHttpRequest()
        let url = absoluteUrl(changesetUrl)
        xhr.open("POST", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Content-Type", "application/json; charset=utf-8")
        xhr.setRequestHeader("Authorization", "Bearer " + bearerToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            syncInFlight = false

            if (xhr.status >= 200 && xhr.status < 300) {
                let response = null
                try { response = JSON.parse(xhr.responseText) } catch (parseErr) {}
                if (!response || !response.ok) {
                    log("invalid changeset response")
                    if (manual) toast("GeoFlow 동기화 응답을 해석하지 못했습니다")
                    return
                }
                let state = projectState()
                if (state.outbox && state.outbox.changeset_id === payload.changeset_id) {
                    state.outbox = null
                    state.base_revision = Number(response.current_revision || state.base_revision || 0)
                    saveProjectState(state)
                }
                toast(
                    "GeoFlow 서버 반영 완료 · " +
                    Number(response.total || 0) + "건" +
                    " (revision " + Number(response.current_revision || 0) + ")"
                )
                log("changeset applied revision=" + response.current_revision)
                return
            }

            if (xhr.status === 0) {
                log("offline; Changeset retained for retry")
                if (manual) toast("오프라인입니다 · 변경사항을 보관했습니다")
                return
            }

            let message = "HTTP " + xhr.status
            try {
                let errorPayload = JSON.parse(xhr.responseText)
                message = errorPayload.message || errorPayload.error || message
            } catch (err) {}
            log("changeset failed: " + message)
            if (xhr.status === 401 || xhr.status === 403) {
                toast("GeoFlow QField 인증이 만료되었습니다 · 프로젝트를 다시 연결하세요")
            } else if (xhr.status === 409) {
                toast("GeoFlow 동기화 충돌 · 서버 상태 확인이 필요합니다")
            } else if (manual) {
                toast("GeoFlow 서버 반영 실패: " + message)
            }
        }
        xhr.send(JSON.stringify(payload))
    }

    function syncNow(manual) {
        if (syncInFlight) return
        if (!configReady && !reloadProjectConfig()) {
            if (manual) toast("GeoFlow 프로젝트 연결 정보가 없습니다")
            return
        }
        if (layerBindings.length === 0) bindLayers()
        if (hasUncommittedEdits()) {
            if (manual) toast("현재 편집을 저장한 뒤 동기화하세요")
            return
        }

        let state = projectState()
        let payload = state.outbox
        if (!payload) payload = makeOutbox(state)
        if (!payload) {
            if (manual) toast("GeoFlow: 동기화할 로컬 변경이 없습니다")
            return
        }
        postOutbox(payload, manual)
    }

    function initializeProject() {
        mainWindow = iface.mainWindow()
        mapCanvas = iface.mapCanvas()
        if (!reloadProjectConfig()) {
            toast("GeoFlow Field 연결 정보를 읽지 못했습니다")
            return
        }
        let count = bindLayers()
        toast("GeoFlow Field 0.5 연결됨 · 편집 동기화 준비 " + count + "개 레이어")
        syncNow(false)
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(syncButton)
        log("plugin component completed")
        bootstrapTimer.restart()
    }

    Component.onDestruction: {
        unbindLayers()
        try { iface.removeItemFromPluginsToolbar(syncButton) } catch (err) {}
    }
}
