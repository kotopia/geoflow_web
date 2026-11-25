(function () {
  "use strict";
  function init() {
    var element = document.getElementById("gisDashboardMap"); if (!element) return;
    if (!window.L || !window.GeoFlowMapReferences) { element.textContent = "지도 라이브러리를 불러오지 못했습니다. 새로고침해 주세요."; return; }
    var map = L.map(element).setView([36.5, 127.8], 7);
    var shared = window.GeoFlowMapReferences;
    shared.install(map, shared.json("gis-vworld-config", {}));
    var projects = shared.json("gis-project-locations", []);
    var groups = typeof L.markerClusterGroup === "function" ? L.markerClusterGroup({disableClusteringAtZoom: 14, showCoverageOnHover: false}) : L.layerGroup();
    var areas = L.geoJSON(null, {style: {color: "#0d6efd", weight: 2, fillOpacity: 0.05}});
    var extent = L.latLngBounds([]), labels = [];
    projects.forEach(function (feature) {
      var properties = feature.properties;
      var region = L.geoJSON(feature, {style: {color: "#0d6efd", weight: 2, fillOpacity: 0.05}});
      var bounds = region.getBounds(); if (!bounds.isValid()) return;
      extent.extend(bounds);
      var tooltip = document.createElement("span"); tooltip.textContent = properties.code;
      var marker = L.marker(bounds.getCenter(), {title: properties.code + " · " + properties.name});
      marker.bindTooltip(tooltip, {permanent: false, direction: "top", className: "gf-project-label"});
      function openProject() { window.location.assign(properties.url); }
      marker.on("click", openProject); groups.addLayer(marker); labels.push(marker);
      if (feature.geometry.type !== "Point") { region.on("click", openProject); areas.addLayer(region); }
    });
    groups.addTo(map);
    function zoom() {
      var expanded = map.getZoom() >= 13;
      labels.forEach(function (marker) { if (expanded) marker.openTooltip(); else marker.closeTooltip(); });
      if (expanded) areas.addTo(map); else map.removeLayer(areas);
    }
    map.on("zoomend", zoom); map.on("layeradd", function (event) { if (labels.indexOf(event.layer) !== -1 && map.getZoom() >= 13) event.layer.openTooltip(); });
    if (extent.isValid()) map.fitBounds(extent, {maxZoom: 15, padding: [30,30]});
    zoom();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
