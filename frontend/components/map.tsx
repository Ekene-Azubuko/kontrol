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
  kind?: "incident" | "hospital" | "vehicle";
};
export type MapRoute = { id: string; points: [number, number][] };
const sanFranciscoBounds: [[number, number], [number, number]] = [
  [-122.525, 37.705],
  [-122.35, 37.825],
];
const basemapStyle = "https://tiles.openfreemap.org/styles/dark";

/** Overlay approved operational records on San Francisco's real streets and geography. */
export function IncidentMap({
  items,
  onSelect,
  onPin,
  pin,
  compact = false,
  routes,
}: {
  items: MapItem[];
  onSelect?: (id: string) => void;
  onPin?: (latitude: number, longitude: number) => void;
  pin?: [number, number];
  compact?: boolean;
  routes?: MapRoute[];
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const animation = useRef<number | null>(null);
  const [error, setError] = useState(false);
  const [ready, setReady] = useState(false);
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
      element.className = `${positioningClasses} map-marker ${item.kind || "incident"} ${item.severity || "resource"}`;
      const label = item.title || item.name || item.category;
      element.setAttribute("aria-label", label);
      element.title = label;
      element.textContent =
        item.kind === "hospital"
          ? "H"
          : item.kind === "vehicle"
            ? "✚"
            : item.category === "wildfire" || item.category === "fire"
              ? "♨"
              : "!";
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
  }, [items]);
  useEffect(() => {
    if (!map.current || !pin) return;
    const marker = new maplibregl.Marker({ color: "#3b82f6" })
      .setLngLat([pin[1], pin[0]])
      .addTo(map.current);
    return () => {
      marker.remove();
    };
  }, [pin]);
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
    <div className={`map-wrap ${compact ? "compact" : ""}`} data-ready={ready}>
      <div ref={container} className="map-canvas" />
      {error && (
        <div className="map-fallback" role="status">
          Basemap unavailable. Check your connection or use the record list.
        </div>
      )}
      <div className="map-caption">
        <span className="live-dot" /> SAN FRANCISCO{" "}
        <span>LIVE RESPONSES</span>
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
      {!items.length && <small className="map-disclaimer">NO APPROVED RESPONSES ON THE MAP</small>}
    </div>
  );
}
