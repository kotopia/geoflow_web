import QtQuick
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
    property var featureFormBridge: null

    property string serverUrl: ""
    property string projectId: ""
    property string bearerToken: ""
    property string roamingPlanUrl: ""
    property string roamingCellUrl: ""
    property string changesetUrl: ""
    property real movementThresholdM: 100.0

    property bool configReady: false
    property bool requestInFlight: false
    property bool syncInFlight: false
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
    property string lastFeatureFormState: ""

    property var managedLayerDescriptors: []
    property var layerFidMaps: ({})
    property var layerVersionMaps: ({})

    Settings {
        id: localState
        category: "GeoFlowField/" + geoflowField.projectId
        property string knownCellsCsv: ""
        property string lastLocation: ""
    }

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
        onClicked: geoflowField.manualSync()
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
        onTriggered: geoflowField.syncNow(false)
    }

    Timer {
        id: editAcceptedSyncTimer
        interval: 650
        repeat: false
        running: false
        onTriggered: geoflowField.syncNow(false)
    }

    Timer {
        id: refreshMapsTimer
        interval: 500
        repeat: false
        running: false
        onTriggered: geoflowField.refreshAllFidMaps()
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
            geoflowField.layerFidMaps = ({})
            geoflowField.layerVersionMaps = ({})
            geoflowField.featureFormBridge = null
            geoflowField.lastFeatureFormState = ""
            bootstrapTimer.restart()
            roamingTimer.restart()
        }
    }

    Connections {
        target: geoflowField.featureFormBridge
        ignoreUnknownSignals: true

        function onStateChanged() {
            let current = String(geoflowField.featureFormBridge ? geoflowField.featureFormBridge.state : "")
            let previous = geoflowField.lastFeatureFormState
            geoflowField.lastFeatureFormState = current
            geoflowField.log("feature form state " + previous + " -> " + current)

            if (previous === "FeatureFormEdit" && current !== "FeatureFormEdit") {
                if (geoflowField.captureFocusedFeature("feature_form_confirmed")) {
                    editAcceptedSyncTimer.restart()
                }
            }
        }
    }

    Repeater {
        id: layerSignalBridges
        model: geoflowField.managedLayerDescriptors

        delegate: Item {
            id: signalBridge
            visible: false
            width: 0
            height: 0
            property var descriptor: modelData || ({})
            property string physicalName: String(descriptor.physical_name || "")
            property string standardName: String(descriptor.standard_name || physicalName).toUpperCase()
            property var layer: geoflowField.layerByPhysicalName(physicalName)

            Connections {
                target: signalBridge.layer
                ignoreUnknownSignals: true

                function onGeometryChanged(fid, geometry) {
                    geoflowField.log(signalBridge.standardName + " geometryChanged fid=" + fid)
                    if (geoflowField.captureGeometry(signalBridge.layer, signalBridge.standardName, fid, geometry)) {
                        editAcceptedSyncTimer.restart()
                    }
                }

                function onAttributeValueChanged(fid, index, value) {
                    geoflowField.log(signalBridge.standardName + " attributeValueChanged fid=" + fid + " index=" + index)
                    if (geoflowField.captureAttribute(signalBridge.layer, signalBridge.standardName, fid, index, value)) {
                        editAcceptedSyncTimer.restart()
                    }
                }

                function onFeatureAdded(fid) {
                    geoflowField.log(signalBridge.standardName + " featureAdded fid=" + fid)
                    Qt.callLater(function() {
                        if (geoflowField.captureCreate(signalBridge.layer, signalBridge.standardName, fid)) {
                            editAcceptedSyncTimer.restart()
                        }
                    })
                }

                function onFeatureDeleted(fid) {
                    geoflowField.log(signalBridge.standardName + " featureDeleted fid=" + fid)
                    if (geoflowField.captureDelete(signalBridge.standardName, fid)) {
                        editAcceptedSyncTimer.restart()
                    }
                }

                function onEditingStopped() {
                    geoflowField.log(signalBridge.standardName + " editingStopped")
                    geoflowField.refreshLayerFidMap(signalBridge.layer, signalBridge.standardName)
                    editAcceptedSyncTimer.restart()
                }

                function onAfterCommitChanges() {
                    geoflowField.log(signalBridge.standardName + " afterCommitChanges")
                    geoflowField.refreshLayerFidMap(signalBridge.layer, signalBridge.standardName)
                    editAcceptedSyncTimer.restart()
                }
            }
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

    function reloadProjectConfig() {
        try { mainWindow = iface.mainWindow() } catch (err) {}
        try { mapCanvas = iface.mapCanvas() } catch (err2) {}
        try { positioning = iface.positioning() } catch (err3) {}
        try { featureFormBridge = iface.findItemByObjectName("featureForm") } catch (err4) { featureFormBridge = null }

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
        if (featureFormBridge) lastFeatureFormState = String(featureFormBridge.state || "")

        if (configReady) {
            log("project config ready for " + projectId + " featureForm=" + Boolean(featureFormBridge))
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
        if (String(path).indexOf("http://") === 0 || String(path).indexOf("https://") === 0) return String(path)
        return serverUrl.replace(/\/$/, "") + "/" + String(path).replace(/^\//, "")
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

    function protectedField(name) {
        return ["id", "project_id", "created_at", "updated_at", "created_by", "updated_by"].indexOf(name) >= 0
    }

    function layerName(layer) {
        if (!layer) return ""
        try { if (typeof layer.name === "string") return layer.name } catch (err) {}
        try { return String(layer.name()) } catch (err2) {}
        return ""
    }

    function layerByPhysicalName(physicalName) {
        if (!physicalName) return null
        try {
            let matches = qgisProject.mapLayersByName(String(physicalName))
            if (matches && matches.length > 0) return matches[0]
        } catch (err) {
            log("mapLayersByName failed for " + physicalName + ": " + err)
        }
        return null
    }

    function standardNameForPhysical(physicalName) {
        let target = String(physicalName || "")
        for (let i = 0; i < managedLayerDescriptors.length; i++) {
            let row = managedLayerDescriptors[i] || {}
            if (String(row.physical_name || "") === target) {
                return String(row.standard_name || target).toUpperCase()
            }
        }
        return target.toUpperCase()
    }

    function fieldName(layer, index) {
        try { return String(layer.fields().at(Number(index)).name()) } catch (err) {}
        return ""
    }

    function collectAttributes(layer, feature) {
        let attrs = {}
        if (!layer || !feature) return attrs
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

    function featureByFid(layer, fid) {
        let iterator = null
        try {
            iterator = LayerUtils.createFeatureIteratorFromExpression(layer, "$id = " + Number(fid))
            if (iterator && iterator.hasNext()) return iterator.next()
        } catch (err) {
            log("feature lookup failed fid=" + fid + ": " + err)
        } finally {
            if (iterator) {
                try { iterator.close() } catch (closeErr) {}
            }
        }
        return null
    }

    function fidMapFor(standardName) {
        let key = String(standardName || "").toUpperCase()
        let maps = layerFidMaps || ({})
        if (!maps[key]) maps[key] = ({})
        layerFidMaps = maps
        return maps[key]
    }

    function versionMapFor(standardName) {
        let key = String(standardName || "").toUpperCase()
        let maps = layerVersionMaps || ({})
        if (!maps[key]) maps[key] = ({})
        layerVersionMaps = maps
        return maps[key]
    }

    function featureVersion(standardName, objectId, feature) {
        let state = projectState()
        let stateKey = String(standardName) + "|" + String(objectId)
        if (state.feature_versions[stateKey]) return String(state.feature_versions[stateKey])
        if (feature) {
            try {
                let value = normalizedValue(feature.attribute("updated_at"))
                if (value) return String(value)
            } catch (err) {}
        }
        return ""
    }

    function refreshLayerFidMap(layer, standardName) {
        if (!layer || !standardName) return 0
        let fidMap = ({})
        let versionMap = ({})
        let iterator = null
        let count = 0
        try {
            iterator = LayerUtils.createFeatureIteratorFromExpression(layer, "\"id\" IS NOT NULL")
            while (iterator && iterator.hasNext()) {
                let feature = iterator.next()
                let objectId = canonicalUuid(feature.attribute("id"))
                if (!objectId) continue
                let fid = String(feature.id())
                fidMap[fid] = objectId
                versionMap[fid] = featureVersion(standardName, objectId, feature)
                count += 1
            }
        } catch (err) {
            log(standardName + " fid map failed: " + err)
        } finally {
            if (iterator) {
                try { iterator.close() } catch (closeErr) {}
            }
        }

        let allFids = layerFidMaps || ({})
        allFids[String(standardName).toUpperCase()] = fidMap
        layerFidMaps = allFids
        let allVersions = layerVersionMaps || ({})
        allVersions[String(standardName).toUpperCase()] = versionMap
        layerVersionMaps = allVersions
        log(standardName + " fid map ready count=" + count)
        return count
    }

    function refreshAllFidMaps() {
        let total = 0
        for (let i = 0; i < managedLayerDescriptors.length; i++) {
            let row = managedLayerDescriptors[i] || {}
            let physical = String(row.physical_name || "")
            let standard = String(row.standard_name || physical).toUpperCase()
            let layer = layerByPhysicalName(physical)
            if (layer) total += refreshLayerFidMap(layer, standard)
        }
        log("all fid maps ready total=" + total)
        return total
    }

    function resolveObjectId(layer, standardName, fid, feature) {
        let map = fidMapFor(standardName)
        let objectId = canonicalUuid(map[String(fid)] || "")
        if (objectId) return objectId

        let sourceFeature = feature || featureByFid(layer, fid)
        if (sourceFeature) {
            objectId = canonicalUuid(sourceFeature.attribute("id"))
            if (objectId) {
                map[String(fid)] = objectId
                let maps = layerFidMaps || ({})
                maps[String(standardName).toUpperCase()] = map
                layerFidMaps = maps
            }
        }
        return objectId
    }

    function baseUpdatedAt(standardName, fid, objectId, feature) {
        let versions = versionMapFor(standardName)
        let value = String(versions[String(fid)] || "")
        if (value) return value
        return featureVersion(standardName, objectId, feature)
    }

    function pendingKey(changeOrLayer, objectId) {
        if (typeof changeOrLayer === "object") {
            return String(changeOrLayer.layer) + "|" + String(changeOrLayer.id)
        }
        return String(changeOrLayer) + "|" + String(objectId)
    }

    function queueChange(change) {
        if (captureSuppressed || !projectId || !change || !change.id || !change.layer) return false
        let state = projectState()
        let pending = state.pending
        let key = pendingKey(change)
        let old = pending[key]

        if (!old) {
            pending[key] = change
        } else if (old.action === "create" && change.action === "delete") {
            delete pending[key]
        } else if (change.action === "delete") {
            let baseValue = old.base_updated_at || change.base_updated_at || ""
            pending[key] = { action: "delete", layer: change.layer, id: change.id }
            if (baseValue) pending[key].base_updated_at = baseValue
        } else if (old.action === "create") {
            old.attributes = Object.assign({}, old.attributes || {}, change.attributes || {})
            if (change.geometry_wkt) old.geometry_wkt = change.geometry_wkt
            pending[key] = old
        } else {
            old.action = "update"
            old.attributes = Object.assign({}, old.attributes || {}, change.attributes || {})
            if (change.geometry_wkt) old.geometry_wkt = change.geometry_wkt
            if (!old.base_updated_at && change.base_updated_at) old.base_updated_at = change.base_updated_at
            pending[key] = old
        }

        state.pending = pending
        saveProjectState(state)
        syncStatus = "pending"
        log("queued " + change.action + " " + change.layer + " " + change.id + " pending=" + Object.keys(pending).length)
        return true
    }

    function captureGeometry(layer, standardName, fid, geometry) {
        if (captureSuppressed || !layer) return false
        let feature = null
        let objectId = resolveObjectId(layer, standardName, fid, null)
        if (!objectId) {
            feature = featureByFid(layer, fid)
            objectId = resolveObjectId(layer, standardName, fid, feature)
        }
        if (!objectId) {
            log(standardName + " geometry skipped: UUID not found fid=" + fid)
            return false
        }

        let wkt = ""
        try {
            if (geometry && !geometry.isNull() && !geometry.isEmpty()) wkt = String(geometry.asWkt(8))
        } catch (err) {}
        if (!wkt) {
            if (!feature) feature = featureByFid(layer, fid)
            wkt = featureGeometryWkt(feature)
        }
        if (!wkt) return false

        let change = { action: "update", layer: standardName, id: objectId, geometry_wkt: wkt }
        let baseValue = baseUpdatedAt(standardName, fid, objectId, feature)
        if (baseValue) change.base_updated_at = baseValue
        return queueChange(change)
    }

    function captureAttribute(layer, standardName, fid, index, value) {
        if (captureSuppressed || !layer) return false
        let name = fieldName(layer, index)
        if (!name || protectedField(name)) return false
        let feature = featureByFid(layer, fid)
        let objectId = resolveObjectId(layer, standardName, fid, feature)
        if (!objectId) return false

        let attrs = ({})
        attrs[name] = normalizedValue(value)
        let change = { action: "update", layer: standardName, id: objectId, attributes: attrs }
        let baseValue = baseUpdatedAt(standardName, fid, objectId, feature)
        if (baseValue) change.base_updated_at = baseValue
        return queueChange(change)
    }

    function captureCreate(layer, standardName, fid) {
        if (captureSuppressed || !layer) return false
        let feature = featureByFid(layer, fid)
        if (!feature) return false

        let objectId = canonicalUuid(feature.attribute("id"))
        let fields = layer.fields()
        captureSuppressed = true
        try {
            if (!objectId) {
                objectId = uuidV4()
                let idIndex = fields.indexOf("id")
                if (idIndex >= 0) layer.changeAttributeValue(fid, idIndex, objectId)
            }
            let projectValue = canonicalUuid(feature.attribute("project_id"))
            if (!projectValue && projectId) {
                let projectIndex = fields.indexOf("project_id")
                if (projectIndex >= 0) layer.changeAttributeValue(fid, projectIndex, projectId)
            }
        } finally {
            captureSuppressed = false
        }

        feature = featureByFid(layer, fid) || feature
        let wkt = featureGeometryWkt(feature)
        if (!wkt || !objectId) return false

        let map = fidMapFor(standardName)
        map[String(fid)] = objectId
        let allFids = layerFidMaps || ({})
        allFids[String(standardName).toUpperCase()] = map
        layerFidMaps = allFids

        return queueChange({
            action: "create",
            layer: standardName,
            id: objectId,
            attributes: collectAttributes(layer, feature),
            geometry_wkt: wkt
        })
    }

    function captureDelete(standardName, fid) {
        if (captureSuppressed) return false
        let map = fidMapFor(standardName)
        let objectId = canonicalUuid(map[String(fid)] || "")
        if (!objectId) {
            log(standardName + " delete skipped: UUID not found fid=" + fid)
            return false
        }
        let versions = versionMapFor(standardName)
        let change = { action: "delete", layer: standardName, id: objectId }
        if (versions[String(fid)]) change.base_updated_at = String(versions[String(fid)])
        delete map[String(fid)]
        delete versions[String(fid)]
        return queueChange(change)
    }

    function captureFocusedFeature(reason) {
        if (!featureFormBridge || captureSuppressed) return false
        let layer = null
        let feature = null
        try { layer = featureFormBridge.selection.focusedLayer } catch (err) {}
        try { feature = featureFormBridge.selection.focusedFeature } catch (err2) {}
        if (!layer || !feature) {
            log("focused feature capture skipped: selection unavailable reason=" + reason)
            return false
        }

        let physical = layerName(layer)
        let standard = standardNameForPhysical(physical)
        let objectId = canonicalUuid(feature.attribute("id"))
        if (!objectId) return false

        let fid = String(feature.id())
        let wkt = featureGeometryWkt(feature)
        let change = {
            action: "update",
            layer: standard,
            id: objectId,
            attributes: collectAttributes(layer, feature)
        }
        if (wkt) change.geometry_wkt = wkt
        let baseValue = baseUpdatedAt(standard, fid, objectId, feature)
        if (baseValue) change.base_updated_at = baseValue
        log("focused feature captured reason=" + reason + " layer=" + standard + " id=" + objectId)
        return queueChange(change)
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

    function applyServerVersions(state, response) {
        let applied = response.applied || []
        for (let i = 0; i < applied.length; i++) {
            let row = applied[i]
            let key = pendingKey(String(row.layer || ""), String(row.id || ""))
            if (row.action === "delete") {
                delete state.feature_versions[key]
            } else if (row.updated_at) {
                state.feature_versions[key] = String(row.updated_at)
            }
        }
    }

    function postOutbox(payload, manual) {
        syncInFlight = true
        syncStatus = "syncing"
        let xhr = new XMLHttpRequest()
        let url = absoluteUrl(changesetUrl)
        log("POST changeset count=" + payload.changes.length + " url=" + url)
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
                    applyServerVersions(state, response)
                    saveProjectState(state)
                }
                wasOffline = false
                authBlocked = false
                syncStatus = "synced"
                clearRetry()
                refreshMapsTimer.restart()
                toast("GeoFlow 서버 반영 완료 · " + Number(response.total || 0) + "건 · revision " + Number(response.current_revision || 0))
                log("changeset applied revision=" + response.current_revision)
                return
            }

            if (xhr.status === 0) {
                wasOffline = true
                syncStatus = "offline"
                scheduleRetry()
                log("offline; Changeset retained for retry")
                if (manual) toast("오프라인입니다 · 변경사항을 보관했습니다")
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
                toast("GeoFlow QField 쓰기 권한이 거부되었습니다 · 프로젝트 권한을 확인하세요")
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

    function syncNow(manual) {
        if (syncInFlight || authBlocked) return
        if (!manual && nextRetryAtMs > 0 && Date.now() < nextRetryAtMs) return
        if (!configReady && !reloadProjectConfig()) {
            if (manual) toast("GeoFlow 프로젝트 연결 정보가 없습니다")
            return
        }

        let state = projectState()
        updateUnsyncedCount(state)
        if (state.conflict) {
            syncStatus = "conflict"
            if (manual) toast("GeoFlow 충돌이 보류 중입니다 · 새 프로젝트 패키지에서 서버 상태를 확인하세요")
            return
        }

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
                if (!quiet && xhr.status === 401) toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다")
                else if (!quiet && xhr.status === 403) toast("GeoFlow QField 읽기 권한이 거부되었습니다" + (serverMessage ? " · " + serverMessage : ""))
                else if (!quiet && xhr.status !== 0) toast("GeoFlow 수신 실패: HTTP " + xhr.status)
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
        catch (err) { return "" }
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
            refreshMapsTimer.restart()

            let state = projectState()
            if (!state.outbox && Object.keys(state.pending || {}).length === 0 && Number(state.base_revision || 0) === 0) {
                state.base_revision = Number(plan.current_revision || 0)
                saveProjectState(state)
            }
            if (force) toast("GeoFlow Field 1.0.1 · 자동 동기화 준비 " + managedLayerDescriptors.length + "개 레이어")
            fetchCells(plan.roaming.cells || [], 0, 0, force)
        }, !force)
    }

    function fetchCells(cells, index, featureTotal, manual) {
        if (index >= cells.length) {
            requestInFlight = false
            mapCanvas.refresh()
            refreshMapsTimer.restart()
            if (manual) toast("GeoFlow 영역 갱신: " + cells.length + "셀 / " + featureTotal + "객체")
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
        let iterator = null
        try {
            let escaped = String(objectId).replace(/'/g, "''")
            iterator = LayerUtils.createFeatureIteratorFromExpression(layer, "\"id\" = '" + escaped + "'")
            return Boolean(iterator && iterator.hasNext())
        } catch (err) {
            return false
        } finally {
            if (iterator) {
                try { iterator.close() } catch (closeErr) {}
            }
        }
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
                let layer = layerByPhysicalName(row.physical_name)
                if (!layer) continue
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
        captureFocusedFeature("manual_sync")
        syncNow(true)
        scheduleRoaming(true)
    }

    function initializeProject() {
        if (!reloadProjectConfig()) {
            toast("GeoFlow Field 연결 정보를 읽지 못했습니다")
            return
        }
        updateUnsyncedCount(projectState())
        toast("GeoFlow Field 1.0.1 연결됨 · 서버 레이어 확인 중")
        scheduleRoaming(true)
        syncNow(false)
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(syncButton)
        log("plugin 1.0.1 component completed")
        bootstrapTimer.restart()
    }

    Component.onDestruction: {
        try { iface.removeItemFromPluginsToolbar(syncButton) } catch (err) {}
    }
}
