(function () {
  "use strict";

  function parseJsonScript(id, fallback) {
    var node = document.getElementById(id);
    if (!node) return fallback;
    try { return JSON.parse(node.textContent || "null") || fallback; }
    catch (error) { return fallback; }
  }

  function domainColor(domain) {
    if (domain === "WTL") return "#0d6efd";
    if (domain === "SWL") return "#8b5e3c";
    return "#6c757d";
  }

  function layerStyle(layerInfo) {
    return { color: domainColor(layerInfo.domain), weight: layerInfo.geometry_kind === "LINE" ? 4 : 2, opacity: 0.9 };
  }

  function pointMarker(feature, latlng, layerInfo) {
    return L.circleMarker(latlng, {
      radius: layerInfo.standard_name === "SURVEY" ? 5 : 6,
      color: domainColor(layerInfo.domain),
      weight: 2,
      fillColor: domainColor(layerInfo.domain),
      fillOpacity: 0.75
    });
  }

  function popupNode(feature, layerInfo) {
    var wrapper = document.createElement("div");
    wrapper.className = "gf-gis-popup";
    var title = document.createElement("strong");
    title.textContent = layerInfo.label || layerInfo.standard_name;
    wrapper.appendChild(title);

    var dl = document.createElement("dl");
    var properties = feature.properties || {};
    var rows = [
      ["UUID", feature.id || properties.id],
      ["시설물 코드", properties.ftr_cde],
      ["외부 시설물 ID", properties.ftr_idn],
      ["소스 키", properties.source_key],
      ["소스 유형", properties.source_type],
      ["측량 코드", properties.survey_code || properties.code],
      ["측량일", properties.survey_date],
      ["명칭", properties.name],
      ["비고", properties.description || properties.etctxt]
    ];
    rows.forEach(function (row) {
      if (row[1] === null || row[1] === undefined || row[1] === "") return;
      var dt = document.createElement("dt");
      var dd = document.createElement("dd");
      dt.textContent = row[0];
      dd.textContent = String(row[1]);
      dl.appendChild(dt);
      dl.appendChild(dd);
    });
    wrapper.appendChild(dl);
    return wrapper;
  }

  function bboxString(map) {
    var bounds = map.getBounds();
    return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(",");
  }

  function initProjectMap() {
    var mapNode = document.getElementById("gisProjectMap");
    if (!mapNode || typeof L === "undefined") return;

    var endpoint = mapNode.getAttribute("data-geojson-url");
    var featureEndpoint = mapNode.getAttribute("data-feature-url");
    var websocketPath = mapNode.getAttribute("data-websocket-path");
    var layers = parseJsonScript("gis-map-layers", []).filter(function (row) {
      return !row.physical_status || row.physical_status === "READY";
    });
    var statusNode = document.getElementById("gisMapStatus");
    var countNode = document.getElementById("gisMapVisibleCount");

    var map = L.map(mapNode, { preferCanvas: true, zoomControl: true }).setView([36.5, 127.8], 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);

    var overlayMaps = {};
    var layerState = {};
    var loadingGeneration = 0;
    var debounceTimer = null;
    var socket = null;
    var reconnectTimer = null;
    var reconnectDelay = 1000;
    var websocketStarted = false;

    function setStatus(text) { if (statusNode) statusNode.textContent = text; }

    function featureId(feature) {
      if (!feature) return "";
      return String(feature.id || (feature.properties || {}).id || "");
    }

    function updateVisibleCount() {
      if (!countNode) return;
      var total = 0;
      Object.keys(layerState).forEach(function (key) {
        var state = layerState[key];
        if (map.hasLayer(state.group)) total += state.group.getLayers().length;
      });
      countNode.textContent = String(total);
    }

    function createState(layerInfo) {
      var state = {
        info: layerInfo,
        group: null,
        featureLayers: {},
        returned: 0,
        truncated: false
      };
      state.group = L.geoJSON(null, {
        style: function () { return layerStyle(layerInfo); },
        pointToLayer: function (feature, latlng) { return pointMarker(feature, latlng, layerInfo); },
        onEachFeature: function (feature, leafletLayer) {
          var id = featureId(feature);
          if (id) state.featureLayers[id] = leafletLayer;
          leafletLayer.bindPopup(function () { return popupNode(feature, layerInfo); });
        }
      });
      state.group.addTo(map);
      overlayMaps[(layerInfo.domain_label || layerInfo.domain) + " · " + (layerInfo.label || layerInfo.standard_name)] = state.group;
      layerState[layerInfo.standard_name] = state;
      return state;
    }

    layers.forEach(createState);
    if (Object.keys(overlayMaps).length) L.control.layers(null, overlayMaps, { collapsed: false }).addTo(map);
    map.on("overlayadd overlayremove", updateVisibleCount);

    function clearState(state) {
      state.group.clearLayers();
      state.featureLayers = {};
      state.returned = 0;
    }

    function removeFeature(state, objectId) {
      var layer = state.featureLayers[objectId];
      if (layer) state.group.removeLayer(layer);
      delete state.featureLayers[objectId];
      state.returned = state.group.getLayers().length;
    }

    async function loadLayer(state, bbox) {
      var params = new URLSearchParams({ layer: state.info.standard_name, limit: "5000" });
      if (bbox) params.set("bbox", bbox);
      var response = await fetch(endpoint + "?" + params.toString(), {
        credentials: "same-origin", headers: { "Accept": "application/json" }
      });
      if (!response.ok) throw new Error(state.info.standard_name + " HTTP " + response.status);
      var data = await response.json();
      clearState(state);
      state.group.addData(data);
      state.returned = state.group.getLayers().length;
      state.truncated = Boolean(data.meta && data.meta.truncated);
      return state.group.getBounds();
    }

    async function loadAll(options) {
      options = options || {};
      var generation = ++loadingGeneration;
      var bbox = options.bbox || null;
      var states = Object.keys(layerState).map(function (key) { return layerState[key]; });
      if (!states.length) { setStatus("표시할 GIS 객체가 없습니다."); return; }
      setStatus(bbox ? "현재 지도 영역의 GIS 객체를 불러오는 중…" : "프로젝트 GIS 객체를 불러오는 중…");
      var results = await Promise.allSettled(states.map(function (state) { return loadLayer(state, bbox); }));
      if (generation !== loadingGeneration) return;
      var failed = results.filter(function (result) { return result.status === "rejected"; });
      var total = states.reduce(function (sum, state) { return sum + state.group.getLayers().length; }, 0);
      var truncated = states.some(function (state) { return state.truncated; });
      updateVisibleCount();
      if (failed.length) setStatus("일부 레이어를 불러오지 못했습니다. (" + failed.length + "개)");
      else if (truncated) setStatus("객체 " + total + "개 표시 · 일부 레이어는 5,000개 제한 적용");
      else setStatus("객체 " + total + "개 표시");

      if (options.fit) {
        var combined = null;
        states.forEach(function (state) {
          var bounds = state.group.getBounds();
          if (!bounds.isValid()) return;
          if (!combined) combined = L.latLngBounds(bounds.getSouthWest(), bounds.getNorthEast());
          else combined.extend(bounds);
        });
        if (combined && combined.isValid()) map.fitBounds(combined.pad(0.15), { maxZoom: 18 });
      }
    }

    async function refreshChangedLayer(state, objectIds, currentRevision) {
      objectIds.forEach(function (id) { removeFeature(state, id); });
      if (!objectIds.length) return;
      var params = new URLSearchParams({
        layer: state.info.standard_name,
        ids: objectIds.join(","),
        bbox: bboxString(map)
      });
      var response = await fetch(featureEndpoint + "?" + params.toString(), {
        credentials: "same-origin", headers: { "Accept": "application/json" }
      });
      if (!response.ok) throw new Error(state.info.standard_name + " refresh HTTP " + response.status);
      var data = await response.json();
      state.group.addData(data);
      state.returned = state.group.getLayers().length;
      updateVisibleCount();
      setStatus("실시간 변경 반영 · revision " + currentRevision);
    }

    async function applyRealtimeEvent(payload) {
      if (!payload || payload.type !== "gis.project.change") return;
      var grouped = {};
      (payload.changes || []).forEach(function (change) {
        var state = layerState[String(change.layer || "")];
        if (!state) return;
        var id = String(change.id || "");
        if (!id) return;
        if (change.action === "delete") {
          removeFeature(state, id);
          return;
        }
        if (!grouped[change.layer]) grouped[change.layer] = [];
        grouped[change.layer].push(id);
      });
      updateVisibleCount();
      var tasks = Object.keys(grouped).map(function (layerName) {
        var unique = Array.from(new Set(grouped[layerName]));
        return refreshChangedLayer(layerState[layerName], unique, payload.current_revision || 0);
      });
      try { await Promise.all(tasks); }
      catch (error) {
        setStatus("실시간 부분 갱신 실패 · 현재 영역 다시 불러오는 중…");
        await loadAll({ bbox: bboxString(map), fit: false });
      }
    }

    function websocketUrl() {
      if (!websocketPath) return "";
      var scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      return scheme + "//" + window.location.host + websocketPath;
    }

    function connectWebSocket() {
      var url = websocketUrl();
      if (!url || typeof WebSocket === "undefined") return;
      websocketStarted = true;
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      socket = new WebSocket(url);
      socket.onopen = function () {
        reconnectDelay = 1000;
        setStatus("실시간 연결됨");
      };
      socket.onmessage = function (event) {
        try { applyRealtimeEvent(JSON.parse(event.data)); } catch (error) { /* ignore malformed event */ }
      };
      socket.onclose = function () {
        socket = null;
        setStatus("실시간 연결 재시도 중…");
        reconnectTimer = setTimeout(connectWebSocket, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 15000);
      };
      socket.onerror = function () { if (socket) socket.close(); };
    }

    loadAll({ fit: true }).then(function () {
      connectWebSocket();
      map.on("moveend", function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          loadAll({ bbox: bboxString(map), fit: false }).catch(function () {
            setStatus("현재 지도 영역을 다시 불러오지 못했습니다.");
          });
        }, 250);
      });
    }).catch(function () { setStatus("GIS 객체를 불러오지 못했습니다."); });

    window.addEventListener("beforeunload", function () {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) socket.close();
      websocketStarted = false;
    });
  }

  document.addEventListener("DOMContentLoaded", initProjectMap);
})();
