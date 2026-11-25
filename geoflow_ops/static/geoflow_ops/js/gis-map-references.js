/* Shared read-only basemap/reference controls for tenant and project maps. */
(function () {
  "use strict";
  function node(tag, text, parent) {
    var value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (parent) parent.appendChild(value);
    return value;
  }
  function json(id, fallback) {
    var element = document.getElementById(id);
    try { return element ? JSON.parse(element.textContent) : fallback; }
    catch (_) { return fallback; }
  }
  async function post(url, data, signal) {
    var token = document.querySelector('[name="csrfmiddlewaretoken"]');
    var response = await fetch(url, {method: "POST", credentials: "same-origin", cache: "no-store", signal: signal,
      headers: {"Content-Type": "application/json", "X-CSRFToken": token ? token.value : ""}, body: JSON.stringify(data)});
    var result = await response.json().catch(function () { return null; });
    if (!response.ok || !result || !result.ok) throw new Error((result && result.error) || "조회하지 못했습니다. 다시 시도하세요.");
    return result;
  }
  function popup(feature) {
    var box = node("div"), properties = feature.properties || {};
    Object.keys(properties).forEach(function (key) {
      node("strong", key + ": ", box); node("span", String(properties[key] === null ? "" : properties[key]), box); node("br", undefined, box);
    });
    return box;
  }
  function install(map, config) {
    var control = L.control({position: "topright"});
    var activeTiles = [], fileStates = [], refreshTimer;
    var pane = map.createPane("referenceRaster"); pane.style.zIndex = 250; pane.style.pointerEvents = "none";
    var vectorPane = map.createPane("referenceVector"); vectorPane.style.zIndex = 350;
    control.onAdd = function () {
      var box = node("div"); box.className = "gf-reference-control leaflet-bar";
      L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box);
      node("strong", "지도", box);
      var select = node("select", undefined, box); select.setAttribute("aria-label", "배경지도");
      [["Base", "일반지도"], ["Satellite", "항공영상"], ["SatelliteHybrid", "항공영상+지명"]].forEach(function (choice) {
        var option = node("option", choice[1], select); option.value = choice[0];
      });
      var notice = node("div", "", box); notice.setAttribute("role", "status"); notice.className = "gf-reference-message";
      function tile(style) {
        var layer = L.tileLayer(config.tiles[style], {maxNativeZoom: 19, maxZoom: 22, minZoom: 6, pane: style === "Cadastral" ? "referenceRaster" : "tilePane",
          zIndex: style === "Hybrid" ? 2 : 1, attribution: '&copy; <a href="https://www.vworld.kr/">VWorld</a>'});
        layer.on("tileerror", function () { notice.textContent = "지도 연결 실패 · API 키·도메인·호출 상태를 확인하세요."; });
        return layer;
      }
      function base() {
        activeTiles.forEach(function (layer) { map.removeLayer(layer); });
        activeTiles = [tile(select.value === "Base" ? "Base" : "Satellite")];
        if (select.value === "SatelliteHybrid") activeTiles.push(tile("Hybrid"));
        activeTiles.forEach(function (layer) { layer.addTo(map); });
        notice.textContent = "";
      }
      select.addEventListener("change", base); base();
      var cadastral = tile("Cadastral");
      var cadastralLabel = node("label", undefined, box), cadastralCheck = node("input", undefined, cadastralLabel);
      cadastralCheck.type = "checkbox"; cadastralLabel.appendChild(document.createTextNode(" 지적편집도"));
      cadastralCheck.addEventListener("change", function () {
        if (cadastralCheck.checked) cadastral.addTo(map); else map.removeLayer(cadastral);
      });
      var opacityLabel = node("label", "불투명도 ", box), opacity = node("input", undefined, opacityLabel);
      opacity.type = "range"; opacity.min = "10"; opacity.max = "100"; opacity.value = "70";
      opacity.setAttribute("aria-label", "지적편집도 불투명도"); cadastral.setOpacity(0.7);
      opacity.addEventListener("input", function () { cadastral.setOpacity(Number(opacity.value) / 100); });
      var details = node("details", undefined, box); node("summary", "참조자료", details);
      var list = node("div", "목록을 불러오는 중…", details);
      var reload = node("button", "목록 새로고침", details); reload.type = "button";
      async function loadOptions() {
        reload.disabled = true;
        fileStates.forEach(function (state) { state.generation++; if (state.abort) state.abort.abort(); map.removeLayer(state.layer); });
        fileStates = []; list.replaceChildren();
        try {
          var response = await fetch(config.options_url, {credentials: "same-origin", cache: "no-store"});
          var result = await response.json();
          if (!response.ok || !result.ok) throw new Error("참조자료 목록을 읽지 못했습니다.");
          var datasets = result.datasets.filter(function (item) { return item.versions.length; });
          if (!datasets.length) node("p", "등록된 파일 자료가 없습니다.", list);
          datasets.forEach(function (dataset) { addDataset(dataset, list); });
        } catch (error) { node("p", error.message || "참조자료 목록을 읽지 못했습니다.", list); }
        finally { reload.disabled = false; }
      }
      reload.addEventListener("click", loadOptions); loadOptions();
      return box;
    };
    function addDataset(dataset, parent) {
      var row = node("div", undefined, parent); row.className = "gf-reference-dataset";
      var label = node("label", undefined, row), check = node("input", undefined, label); check.type = "checkbox";
      label.appendChild(document.createTextNode(" " + dataset.name));
      var settings = node("div", undefined, row); settings.hidden = true;
      var version = node("select", undefined, settings); version.setAttribute("aria-label", dataset.name + " 버전");
      dataset.versions.forEach(function (item) { var option = node("option", item.label, version); option.value = item.id; });
      var layerSelect = node("select", undefined, settings); layerSelect.setAttribute("aria-label", "원본 레이어");
      var xy = node("div", undefined, settings); xy.hidden = true;
      var x = node("select", undefined, xy), y = node("select", undefined, xy), crs = node("input", undefined, xy);
      x.setAttribute("aria-label", "X 필드"); y.setAttribute("aria-label", "Y 필드"); crs.setAttribute("aria-label", "자료 좌표계"); crs.placeholder = "EPSG:5186";
      var message = node("div", "", settings); message.setAttribute("role", "status");
      var layer = L.geoJSON(null, {pane: "referenceVector", style: {color: "#9359b1", weight: 2, fillOpacity: 0.05},
        pointToLayer: function (_, latlng) { return L.circleMarker(latlng, {pane: "referenceVector", radius: 5, color: "#9359b1"}); },
        onEachFeature: function (feature, item) { item.bindPopup(function () { return popup(feature); }); }});
      var state = {layer: layer, generation: 0, abort: null, enabled: false, refresh: refresh}, layers = [], inspectedVersion = null;
      fileStates.push(state);
      function invalidate() { state.generation++; if (state.abort) state.abort.abort(); layer.clearLayers(); }
      async function inspect() {
        invalidate(); var generation = state.generation; inspectedVersion = null; layerSelect.replaceChildren(); layers = [];
        message.textContent = "원본 레이어 확인 중…";
        try {
          var result = await post(config.overlay_url, {action: "inspect", dataset_id: dataset.id, version_id: version.value});
          if (generation !== state.generation || !state.enabled) return;
          layers = result.layers; inspectedVersion = version.value;
          layers.forEach(function (item) { var option = node("option", item.name, layerSelect); option.value = item.name; });
          layerSettings();
        } catch (error) { if (generation === state.generation) message.textContent = error.message; }
      }
      function layerSettings() {
        invalidate(); var selected = layers.find(function (item) { return item.name === layerSelect.value; });
        xy.hidden = !selected || selected.kind !== "xy";
        x.replaceChildren(); y.replaceChildren();
        [x, y].forEach(function (select, index) {
          var empty = node("option", index ? "Y 필드 선택" : "X 필드 선택", select); empty.value = "";
          if (selected) selected.fields.forEach(function (field) { var option = node("option", field, select); option.value = field; });
        });
        crs.value = selected ? selected.crs : ""; refresh();
      }
      async function refresh() {
        invalidate(); if (!state.enabled || inspectedVersion !== version.value || !layerSelect.value) return;
        var bounds = map.getBounds(), west = bounds.getWest(), east = bounds.getEast(), south = bounds.getSouth(), north = bounds.getNorth();
        if (east - west > 0.02 || north - south > 0.02) { message.textContent = "지도를 확대하면 표시됩니다 · 가로·세로 약 2km 이내"; return; }
        if (!xy.hidden && (!x.value || !y.value || !crs.value)) { message.textContent = "X·Y 필드와 좌표계를 선택하세요."; return; }
        var generation = state.generation; state.abort = new AbortController(); message.textContent = "조회 중…";
        try {
          var result = await post(config.overlay_url, {dataset_id: dataset.id, version_id: version.value, layer: layerSelect.value,
            x_field: x.value, y_field: y.value, reference_crs: crs.value,
            geometry: {type: "Polygon", coordinates: [[[west,south],[east,south],[east,north],[west,north],[west,south]]]}}, state.abort.signal);
          if (generation !== state.generation || !state.enabled) return;
          layer.addData(result); message.textContent = result.features.length + "개 · " + version.options[version.selectedIndex].text;
        } catch (error) { if (error.name !== "AbortError" && generation === state.generation) message.textContent = error.message; }
      }
      check.addEventListener("change", function () {
        state.enabled = check.checked; settings.hidden = !check.checked;
        if (check.checked) { layer.addTo(map); inspect(); } else { invalidate(); map.removeLayer(layer); }
      });
      version.addEventListener("change", inspect); layerSelect.addEventListener("change", layerSettings);
      [x, y, crs].forEach(function (input) { input.addEventListener("change", refresh); });
    }
    control.addTo(map);
    map.on("moveend", function () { clearTimeout(refreshTimer); refreshTimer = setTimeout(function () { fileStates.forEach(function (state) { state.refresh(); }); }, 300); });
    map.on("unload", function () { clearTimeout(refreshTimer); fileStates.forEach(function (state) { if (state.abort) state.abort.abort(); }); });
    return control;
  }
  window.GeoFlowMapReferences = {install: install, json: json, post: post};
})();
