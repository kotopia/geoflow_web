(function () {
  "use strict";

  function parseJsonScript(id, fallback) {
    var node = document.getElementById(id);
    if (!node) return fallback;
    try {
      return JSON.parse(node.textContent || "null") || fallback;
    } catch (error) {
      return fallback;
    }
  }

  function domainColor(domain) {
    if (domain === "WTL") return "#0d6efd";
    if (domain === "SWL") return "#8b5e3c";
    return "#6c757d";
  }

  function layerStyle(layerInfo) {
    return {
      color: domainColor(layerInfo.domain),
      weight: layerInfo.geometry_kind === "LINE" ? 4 : 2,
      opacity: 0.9
    };
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
      ["측량 코드", properties.survey_code || properties.code],
      ["측량일", properties.survey_date],
      ["명칭", properties.name],
      ["비고", properties.description || properties.etctxt]
    ];

    rows.forEach(function (row) {
      if (row[1] === null || row[1] === undefined || row[1] === "") return;
      var dt = document.createElement("dt");
      dt.textContent = row[0];
      var dd = document.createElement("dd");
      dd.textContent = String(row[1]);
      dl.appendChild(dt);
      dl.appendChild(dd);
    });

    wrapper.appendChild(dl);
    return wrapper;
  }

  function bboxString(map) {
    var bounds = map.getBounds();
    return [
      bounds.getWest(),
      bounds.getSouth(),
      bounds.getEast(),
      bounds.getNorth()
    ].join(",");
  }

  function initProjectMap() {
    var mapNode = document.getElementById("gisProjectMap");
    if (!mapNode || typeof L === "undefined") return;

    var endpoint = mapNode.getAttribute("data-geojson-url");
    var layers = parseJsonScript("gis-map-layers", []);
    var statusNode = document.getElementById("gisMapStatus");
    var countNode = document.getElementById("gisMapVisibleCount");

    var map = L.map(mapNode, {
      preferCanvas: true,
      zoomControl: true
    }).setView([36.5, 127.8], 7);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);

    var overlayMaps = {};
    var layerState = {};
    var loadingGeneration = 0;
    var debounceTimer = null;

    function setStatus(text) {
      if (statusNode) statusNode.textContent = text;
    }

    function updateVisibleCount() {
      if (!countNode) return;
      var total = 0;
      Object.keys(layerState).forEach(function (key) {
        var state = layerState[key];
        if (map.hasLayer(state.group)) total += state.returned || 0;
      });
      countNode.textContent = String(total);
    }

    layers.forEach(function (layerInfo) {
      var group = L.geoJSON(null, {
        style: function () {
          return layerStyle(layerInfo);
        },
        pointToLayer: function (feature, latlng) {
          return pointMarker(feature, latlng, layerInfo);
        },
        onEachFeature: function (feature, leafletLayer) {
          leafletLayer.bindPopup(function () {
            return popupNode(feature, layerInfo);
          });
        }
      });

      group.addTo(map);
      overlayMaps[(layerInfo.domain_label || layerInfo.domain) + " · " + (layerInfo.label || layerInfo.standard_name)] = group;
      layerState[layerInfo.standard_name] = {
        info: layerInfo,
        group: group,
        returned: 0,
        truncated: false
      };
    });

    if (Object.keys(overlayMaps).length) {
      L.control.layers(null, overlayMaps, { collapsed: false }).addTo(map);
    }

    map.on("overlayadd overlayremove", updateVisibleCount);

    async function loadLayer(state, bbox) {
      var params = new URLSearchParams({
        layer: state.info.standard_name,
        limit: "5000"
      });
      if (bbox) params.set("bbox", bbox);

      var response = await fetch(endpoint + "?" + params.toString(), {
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) {
        throw new Error(state.info.standard_name + " HTTP " + response.status);
      }

      var data = await response.json();
      state.group.clearLayers();
      state.group.addData(data);
      state.returned = data.meta ? data.meta.returned : (data.features || []).length;
      state.truncated = Boolean(data.meta && data.meta.truncated);
      return state.group.getBounds();
    }

    async function loadAll(options) {
      options = options || {};
      var generation = ++loadingGeneration;
      var bbox = options.bbox || null;
      var states = Object.keys(layerState).map(function (key) { return layerState[key]; });
      if (!states.length) {
        setStatus("표시할 GIS 객체가 없습니다.");
        return;
      }

      setStatus(bbox ? "현재 지도 영역의 GIS 객체를 불러오는 중…" : "프로젝트 GIS 객체를 불러오는 중…");
      var results = await Promise.allSettled(states.map(function (state) {
        return loadLayer(state, bbox);
      }));
      if (generation !== loadingGeneration) return;

      var failed = results.filter(function (result) { return result.status === "rejected"; });
      var total = states.reduce(function (sum, state) { return sum + state.returned; }, 0);
      var truncated = states.some(function (state) { return state.truncated; });
      updateVisibleCount();

      if (failed.length) {
        setStatus("일부 레이어를 불러오지 못했습니다. (" + failed.length + "개)");
      } else if (truncated) {
        setStatus("객체 " + total + "개 표시 · 일부 레이어는 5,000개 제한 적용");
      } else {
        setStatus("객체 " + total + "개 표시");
      }

      if (options.fit) {
        var combined = null;
        states.forEach(function (state) {
          var bounds = state.group.getBounds();
          if (!bounds.isValid()) return;
          if (!combined) {
            combined = L.latLngBounds(bounds.getSouthWest(), bounds.getNorthEast());
          } else {
            combined.extend(bounds);
          }
        });
        if (combined && combined.isValid()) {
          map.fitBounds(combined.pad(0.15), { maxZoom: 18 });
        }
      }
    }

    loadAll({ fit: true }).then(function () {
      map.on("moveend", function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          loadAll({ bbox: bboxString(map), fit: false }).catch(function () {
            setStatus("현재 지도 영역을 다시 불러오지 못했습니다.");
          });
        }, 250);
      });
    }).catch(function () {
      setStatus("GIS 객체를 불러오지 못했습니다.");
    });
  }

  document.addEventListener("DOMContentLoaded", initProjectMap);
})();
