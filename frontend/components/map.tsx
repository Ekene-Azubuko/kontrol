"use client";
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Layers, LocateFixed } from "lucide-react";
export type MapItem = {
  id: string;
  latitude: number;
  longitude: number;
  title?: string;
  name?: string;
  category: string;
  severity?: string;
  kind?: "incident" | "hospital" | "vehicle" | "facility";
  markerLabel?: string;
  nearest?: boolean;
};
export type MapRoute = { id: string; points: [number, number][] };
const sanFranciscoBounds: [[number, number], [number, number]] = [
  [-122.525, 37.705],
  [-122.35, 37.825],
];
const basemapStyle = "https://tiles.openfreemap.org/styles/positron";

/** Overlay approved operational records on San Francisco's real streets and geography. */
export function IncidentMap({
  items,
  onSelect,
  onPin,
  pin,
  callerLocation,
  revealLocation,
  compact = false,
  routes,
  selectedId,
  fitToItems = false,
  caption = "LIVE RESPONSES",
  showLegend = true,
}: {
  items: MapItem[];
  onSelect?: (id: string) => void;
  onPin?: (latitude: number, longitude: number) => void;
  pin?: [number, number];
  callerLocation?: {
    latitude: number;
    longitude: number;
    accuracy: number | null;
  };
  revealLocation?: { latitude: number; longitude: number };
  compact?: boolean;
  routes?: MapRoute[];
  selectedId?: string | null;
  fitToItems?: boolean;
  caption?: string;
  showLegend?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const animation = useRef<number | null>(null);
  const [error, setError] = useState(false);
  const [ready, setReady] = useState(false);
  const [revealPhase, setRevealPhase] = useState<
    "locating" | "flying" | "pinned"
  >("locating");
  const select = useRef(onSelect);
  const pinHandler = useRef(onPin);
  useEffect(() => {
    select.current = onSelect;
    pinHandler.current = onPin;
  }, [onSelect, onPin]);
  useEffect(() => {
    if (!container.current) return;
    try {
      maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      const instance = new maplibregl.Map({
        container: container.current,
        // Frame the city without auto-fitting private reports before approval.
        bounds: sanFranciscoBounds,
        fitBoundsOptions: { padding: 35 },
        minZoom: 8,
        maxZoom: 19,
        attributionControl: { compact: true },
        style: basemapStyle,
      });
      instance.addControl(
        new maplibregl.NavigationControl({ showCompass: true }),
        "bottom-right",
      );
      instance.on("click", (event) =>
        pinHandler.current?.(event.lngLat.lat, event.lngLat.lng),
      );
      instance.on("load", () => {
        setReady(true);
        setError(false);
      });
      instance.on("error", () => setError(true));
      const resize = new ResizeObserver(() => instance.resize());
      resize.observe(container.current);
      map.current = instance;
      return () => {
        resize.disconnect();
        instance.remove();
        map.current = null;
      };
    } catch {
      queueMicrotask(() => setError(true));
    }
  }, []);
  useEffect(() => {
    if (!map.current) return;
    const active = new Set(items.map((item) => item.id));
    for (const [id, marker] of markers.current) {
      if (!active.has(id)) {
        marker.remove();
        markers.current.delete(id);
      }
    }
    if (animation.current) cancelAnimationFrame(animation.current);
    const moves: {
      marker: maplibregl.Marker;
      from: [number, number];
      to: [number, number];
    }[] = [];
    for (const item of items) {
      let marker = markers.current.get(item.id);
      if (!marker) {
        const element = document.createElement("button");
        element.onclick = (event) => {
          event.stopPropagation();
          select.current?.(item.id);
        };
        marker = new maplibregl.Marker({ element })
          .setLngLat([item.longitude, item.latitude])
          .addTo(map.current);
        markers.current.set(item.id, marker);
      }
      const element = marker.getElement();
      // MapLibre's positioning classes must survive updates to our visual marker classes.
      const positioningClasses = Array.from(element.classList)
        .filter((name) => name.startsWith("maplibregl-"))
        .join(" ");
      element.className = `${positioningClasses} map-marker ${item.kind || "incident"} ${item.severity || "resource"} ${item.nearest ? "nearest" : ""} ${item.id === selectedId ? "selected" : ""}`;
      if (selectedId !== undefined)
        element.setAttribute("aria-pressed", String(item.id === selectedId));
      element.style.zIndex =
        item.id === selectedId ? "3" : item.nearest ? "2" : "1";
      const label = item.title || item.name || item.category;
      element.setAttribute("aria-label", label);
      element.title = label;
      element.textContent =
        item.markerLabel ??
        (item.kind === "hospital"
          ? "H"
          : item.kind === "vehicle"
            ? "✚"
            : item.category === "wildfire" || item.category === "fire"
              ? "♨"
              : "!");
      if (item.kind === "vehicle") {
        const position = marker.getLngLat();
        moves.push({
          marker,
          from: [position.lng, position.lat],
          to: [item.longitude, item.latitude],
        });
      } else marker.setLngLat([item.longitude, item.latitude]);
    }
    // Retain marker instances so server position updates animate instead of blinking.
    const started = performance.now();
    function animate(timestamp: number) {
      const progress = Math.min(1, (timestamp - started) / 1900);
      for (const move of moves)
        move.marker.setLngLat([
          move.from[0] + (move.to[0] - move.from[0]) * progress,
          move.from[1] + (move.to[1] - move.from[1]) * progress,
        ]);
      if (progress < 1) animation.current = requestAnimationFrame(animate);
    }
    if (moves.length) animation.current = requestAnimationFrame(animate);
    return () => {
      if (animation.current) cancelAnimationFrame(animation.current);
    };
  }, [items, selectedId]);
  const west = Math.min(...items.map((item) => item.longitude));
  const east = Math.max(...items.map((item) => item.longitude));
  const south = Math.min(...items.map((item) => item.latitude));
  const north = Math.max(...items.map((item) => item.latitude));
  useEffect(() => {
    if (
      !ready ||
      !fitToItems ||
      ![west, east, south, north].every(Number.isFinite)
    )
      return;
    // Coordinate-only dependencies prevent SSE refreshes and list sorting from resetting the camera.
    map.current?.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding: 55, maxZoom: 14, duration: 0 },
    );
  }, [ready, fitToItems, west, east, south, north]);
  useEffect(() => {
    if (!map.current || !pin) return;
    const marker = new maplibregl.Marker({
      color: "#3b82f6",
      draggable: !!onPin,
    })
      .setLngLat([pin[1], pin[0]])
      .addTo(map.current);
    marker.on("dragend", () => {
      const point = marker.getLngLat();
      pinHandler.current?.(point.lat, point.lng);
    });
    return () => {
      marker.remove();
    };
  }, [pin, onPin]);
  const revealLatitude = revealLocation?.latitude;
  const revealLongitude = revealLocation?.longitude;
  useEffect(() => {
    const instance = map.current;
    if (
      !ready ||
      !instance ||
      revealLatitude === undefined ||
      revealLongitude === undefined
    )
      return;
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    let marker: maplibregl.Marker | null = null;
    /** Reveal the incident marker after the camera settles, rather than pinning during the flight. */
    function dropPin() {
      if (marker || map.current !== instance || !instance) return;
      const anchor = document.createElement("div");
      anchor.className = "incident-drop-anchor";
      anchor.setAttribute("aria-label", "Automatically detected incident pin");
      const ring = document.createElement("div");
      ring.className = "incident-pin-ring";
      const pin = document.createElement("div");
      pin.className = "incident-drop-pin";
      const core = document.createElement("span");
      core.className = "incident-pin-core";
      pin.appendChild(core);
      anchor.append(ring, pin);
      marker = new maplibregl.Marker({ element: anchor, anchor: "bottom" })
        .setLngLat([revealLongitude!, revealLatitude!])
        .addTo(instance);
      setRevealPhase("pinned");
    }
    const start = window.setTimeout(() => {
      setRevealPhase("flying");
      if (reducedMotion) {
        instance.jumpTo({
          center: [revealLongitude, revealLatitude],
          zoom: 15.7,
          pitch: 0,
          bearing: 0,
        });
        dropPin();
      } else {
        instance.once("moveend", dropPin);
        instance.flyTo({
          center: [revealLongitude, revealLatitude],
          zoom: 15.7,
          pitch: 42,
          bearing: -18,
          duration: 2400,
          curve: 1.3,
        });
      }
    }, 180);
    return () => {
      window.clearTimeout(start);
      instance.off("moveend", dropPin);
      if (map.current === instance) instance.stop();
      marker?.remove();
    };
  }, [ready, revealLatitude, revealLongitude]);
  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance || !callerLocation) return;
    const { latitude, longitude, accuracy } = callerLocation;
    const marker = new maplibregl.Marker({ color: "#f59e0b" })
      .setLngLat([longitude, latitude])
      .addTo(instance);
    // An approximate circle illustrates uncertainty; it does not validate an incident address.
    const coordinates = Array.from({ length: 65 }, (_, index) => {
      const angle = (index * Math.PI) / 32;
      return [
        longitude +
          (Math.cos(angle) * (accuracy || 0)) /
            (111320 * Math.cos((latitude * Math.PI) / 180)),
        latitude + (Math.sin(angle) * (accuracy || 0)) / 111320,
      ];
    });
    instance.addSource("caller-accuracy", {
      type: "geojson",
      data: {
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [coordinates] },
      },
    });
    instance.addLayer({
      id: "caller-accuracy",
      type: "fill",
      source: "caller-accuracy",
      paint: { "fill-color": "#f59e0b", "fill-opacity": 0.18 },
    });
    return () => {
      marker.remove();
      if (map.current !== instance) return;
      if (instance.getLayer("caller-accuracy"))
        instance.removeLayer("caller-accuracy");
      if (instance.getSource("caller-accuracy"))
        instance.removeSource("caller-accuracy");
    };
  }, [ready, callerLocation]);
  useEffect(() => {
    if (!ready || !map.current) return;
    const data = {
      type: "FeatureCollection" as const,
      features: (routes || []).map((route) => ({
        type: "Feature" as const,
        properties: { id: route.id },
        geometry: { type: "LineString" as const, coordinates: route.points },
      })),
    };
    const source = map.current.getSource("response-routes") as
      maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(data);
    else {
      map.current.addSource("response-routes", { type: "geojson", data });
      map.current.addLayer({
        id: "response-routes",
        type: "line",
        source: "response-routes",
        paint: {
          "line-color": "#50cdbd",
          "line-width": 2,
          "line-opacity": 0.7,
          "line-dasharray": [3, 3],
        },
      });
    }
  }, [routes, ready]);
  return (
    <div
      className={`map-wrap ${compact ? "compact" : ""} ${revealLocation ? "call-location-map" : ""}`}
      data-ready={ready}
      data-location-phase={revealLocation ? revealPhase : undefined}
    >
      <div ref={container} className="map-canvas" />
      {error && (
        <div className="map-fallback" role="status">
          Basemap unavailable. Check your connection or use the record list.
        </div>
      )}
      <div className="map-caption">
        <span className="live-dot" /> SAN FRANCISCO{" "}
        <span>{revealLocation ? "INCIDENT LOCATION" : caption}</span>
      </div>
      <div className="map-tools">
        <button
          aria-label="Recenter on San Francisco"
          onClick={() =>
            map.current?.fitBounds(sanFranciscoBounds, { padding: 35 })
          }
        >
          <LocateFixed size={17} />
        </button>
        <span>
          <Layers size={15} /> Street map
        </span>
      </div>
      {revealLocation && !error && (
        <div className={`location-reveal-status ${revealPhase}`} role="status">
          <span className="location-status-dot" />
          {revealPhase === "pinned" ? "Incident located" : "Locating incident…"}
        </div>
      )}
      {!revealLocation && showLegend && (
        <div className="map-legend">
          <span>
            <i className="critical" />
            Critical
          </span>
          <span>
            <i className="high" />
            High
          </span>
          <span>
            <i className="moderate" />
            Moderate
          </span>
          <span>
            <i className="resource" />
            Incident
          </span>
          <span>
            <i className="hospital" />
            Hospital
          </span>
          <span>
            <i className="vehicle" />
            Vehicle
          </span>
        </div>
      )}
      {!items.length && !revealLocation && (
        <small className="map-disclaimer">
          NO APPROVED RESPONSES ON THE MAP
        </small>
      )}
    </div>
  );
}
