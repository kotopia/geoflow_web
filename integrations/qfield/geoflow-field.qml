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
    property string serverUrl: iface.readProjectEntry("GeoFlow", "server_url", "")
    property string projectId: iface.readProjectEntry("GeoFlow", "project_id", "")
    property string bearerToken: iface.readProjectEntry("GeoFlow", "qfield_token", "")
    property string roamingPlanUrl: iface.readProjectEntry("GeoFlow", "roaming_plan_url", "")
    property string roamingCellUrl: iface.readProjectEntry("GeoFlow", "roaming_cell_url", "")
    property real movementThresholdM: iface.readProjectDoubleEntry("GeoFlow", "movement_threshold_m", 100.0)
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
        id: roamingTimer
        interval: 8000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: geoflowField.scheduleRoaming(false)
    }

    function absoluteUrl(path) {
        if (path.indexOf("http://") === 0 || path.indexOf("https://") === 0) return path
        return serverUrl.replace(/\/$/, "") + "/" + path.replace(/^\//, "")
    }

    function authGet(path, callback) {
        let xhr = new XMLHttpRequest()
        xhr.open("GET", absoluteUrl(path))
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Authorization", "Bearer " + bearerToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status < 200 || xhr.status >= 300) {
                requestInFlight = false
                mainWindow.displayToast("GeoFlow 수신 실패: HTTP " + xhr.status)
                return
            }
            try {
                callback(JSON.parse(xhr.responseText))
            } catch (e) {
                requestInFlight = false
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
        if (requestInFlight || !serverUrl || !projectId || !bearerToken) return
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
        let iterator = LayerUtils.createFeatureIteratorFromExpression(layer, "\"id\" = '" + escaped + "'")
        return iterator.hasNext()
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
                let geometry = GeometryUtils.createGeometryFromWkt(incoming.geometry_wkt || "")
                let feature = FeatureUtils.createFeature(layer, geometry)
                let attrs = incoming.properties || {}
                for (let name in attrs) {
                    if (!Object.prototype.hasOwnProperty.call(attrs, name)) continue
                    try { feature.setAttribute(name, attrs[name]) } catch (err) {}
                }
                if (LayerUtils.addFeature(layer, feature)) count += 1
            }
        }
        return { count: count, complete: complete }
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(syncButton)
        mainWindow.displayToast("GeoFlow Field 연결됨")
    }
}
