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
    property var positioning: iface.positioning()
    // QField can instantiate a project sidecar while the project is still
    // loading. Do not freeze project metadata into one-time property
    // initializers; refresh it when iface.loadProjectEnded fires.
    property string serverUrl: ""
    property string projectId: ""
    property string bearerToken: ""
    property string roamingPlanUrl: ""
    property string roamingCellUrl: ""
    property real movementThresholdM: 100.0
    property bool requestInFlight: false
    property string lastViewport: ""
    property real lastLon: NaN
    property real lastLat: NaN

    Settings {
        id: localState
        category: "GeoFlowField/" + geoflowField.projectId
        property string knownCellsCsv: ""
        property string lastLocation: ""
    }

    QfToolButton {
        id: syncButton
        iconSource: Theme.getThemeVectorIcon("ic_sync_white_24dp")
        iconColor: Theme.toolButtonColor
        bgcolor: Theme.toolButtonBackgroundColor
        round: true
        onClicked: geoflowField.scheduleRoaming(true)
    }

    Timer {
        id: bootstrapTimer
        interval: 1200
        repeat: false
        running: false
        onTriggered: geoflowField.scheduleRoaming(true)
    }

    Timer {
        id: roamingTimer
        interval: 8000
        repeat: true
        running: false
        onTriggered: geoflowField.scheduleRoaming(false)
    }

    Connections {
        target: iface

        function onLoadProjectEnded(path, name) {
            geoflowField.log("project load ended: " + name)
            geoflowField.reloadProjectConfig()
            geoflowField.lastViewport = ""
            geoflowField.lastLon = NaN
            geoflowField.lastLat = NaN
            bootstrapTimer.restart()
            roamingTimer.restart()
        }
    }

    function log(message) {
        try { iface.logMessage("GeoFlow Field: " + message) } catch (err) {}
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

        serverUrl = readProjectText("server_url")
        projectId = readProjectText("project_id")
        bearerToken = readProjectText("qfield_token")
        roamingPlanUrl = readProjectText("roaming_plan_url")
        roamingCellUrl = readProjectText("roaming_cell_url")
        movementThresholdM = readProjectNumber("movement_threshold_m", 100.0)

        if (serverUrl && projectId && bearerToken && roamingPlanUrl && roamingCellUrl) {
            log("project config ready for " + projectId)
            return true
        }
        log(
            "project config incomplete" +
            " server=" + Boolean(serverUrl) +
            " project=" + Boolean(projectId) +
            " token=" + Boolean(bearerToken) +
            " plan=" + Boolean(roamingPlanUrl) +
            " cell=" + Boolean(roamingCellUrl)
        )
        if (mainWindow) mainWindow.displayToast("GeoFlow 프로젝트 연결 정보를 기다리는 중입니다")
        return false
    }

    function absoluteUrl(path) {
        if (path.indexOf("http://") === 0 || path.indexOf("https://") === 0) return path
        return serverUrl.replace(/\/$/, "") + "/" + path.replace(/^\//, "")
    }

    function authGet(path, callback) {
        let xhr = new XMLHttpRequest()
        let url = absoluteUrl(path)
        xhr.open("GET", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Authorization", "Bearer " + bearerToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status < 200 || xhr.status >= 300) {
                requestInFlight = false
                log("HTTP " + xhr.status + " " + url)
                mainWindow.displayToast("GeoFlow 수신 실패: HTTP " + xhr.status)
                return
            }
            try {
                callback(JSON.parse(xhr.responseText))
            } catch (e) {
                requestInFlight = false
                log("JSON parse failed: " + e)
                mainWindow.displayToast("GeoFlow 응답 해석 실패")
            }
        }
        xhr.send()
    }

    function viewportText() {
        if (!mapCanvas || !mapCanvas.mapSettings) return ""
        let e = mapCanvas.mapSettings.visibleExtent
        if (!e) return ""
        try {
            return [e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()].join(",")
        } catch (err) {
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
        if (requestInFlight) return
        if (!serverUrl || !projectId || !bearerToken || !roamingPlanUrl || !roamingCellUrl) {
            if (!reloadProjectConfig()) return
        }

        let viewport = viewportText()
        let pos = currentPosition()
        let moved = false
        if (pos) {
            moved = isNaN(lastLon) || distanceMeters(lastLon, lastLat, pos.lon, pos.lat) >= movementThresholdM
        }
        if (!force && !moved && viewport === lastViewport) return

        let query = []
        if (pos) {
            query.push("lon=" + encodeURIComponent(pos.lon))
            query.push("lat=" + encodeURIComponent(pos.lat))
        }
        if (viewport) query.push("viewport=" + encodeURIComponent(viewport))
        let known = knownCells()
        if (known.length) query.push("known=" + encodeURIComponent(known.join(",")))
        if (!pos && !viewport) {
            log("no GPS or viewport available yet")
            if (force && mainWindow) mainWindow.displayToast("GeoFlow 지도 영역/GPS 준비를 기다리는 중입니다")
            return
        }

        requestInFlight = true
        lastViewport = viewport
        if (pos) {
            lastLon = pos.lon
            lastLat = pos.lat
            localState.lastLocation = pos.lon + "," + pos.lat
        }
        log("request roaming plan")
        authGet(roamingPlanUrl + "?" + query.join("&"), function(plan) {
            if (!plan.ok || !plan.roaming) {
                requestInFlight = false
                mainWindow.displayToast("GeoFlow roaming plan 실패")
                return
            }
            fetchCells(plan.roaming.cells || [], 0, 0)
        })
    }

    function fetchCells(cells, index, featureTotal) {
        if (index >= cells.length) {
            requestInFlight = false
            if (cells.length > 0) {
                mainWindow.displayToast("GeoFlow 영역 갱신: " + cells.length + "셀 / " + featureTotal + "객체")
                mapCanvas.refresh()
            } else {
                mainWindow.displayToast("GeoFlow 영역 최신 상태")
            }
            return
        }
        let cell = cells[index]
        authGet(cell.url, function(payload) {
            let merged = mergeCell(payload)
            if (merged.complete) rememberCell(cell.key)
            fetchCells(cells, index + 1, featureTotal + merged.count)
        })
    }

    function featureExists(layer, objectId) {
        let escaped = String(objectId).replace(/'/g, "''")
        let iterator = QfLayerUtils.createFeatureIteratorFromExpression(layer, "\"id\" = '" + escaped + "'")
        let exists = iterator.hasNext()
        iterator.close()
        return exists
    }

    function mergeCell(payload) {
        let count = 0
        let complete = true
        if (!payload || !payload.ok) return { count: 0, complete: false }
        let layers = payload.layers || []
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
                let geometry = QfGeometryUtils.createGeometryFromWkt(incoming.geometry_wkt || "")
                if (!geometry || geometry.isNull() || geometry.isEmpty()) continue
                let feature = QfFeatureUtils.createFeature(layer, geometry)
                let attrs = incoming.properties || {}
                for (let name in attrs) {
                    if (!Object.prototype.hasOwnProperty.call(attrs, name)) continue
                    try { feature.setAttribute(name, attrs[name]) } catch (err) {}
                }
                if (QfLayerUtils.addFeature(layer, feature)) count += 1
            }
        }
        return { count: count, complete: complete }
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(syncButton)
        reloadProjectConfig()
        log("plugin component completed")
        mainWindow.displayToast("GeoFlow Field 연결됨 · 프로젝트 준비 중")
        bootstrapTimer.restart()
        roamingTimer.restart()
    }
}
