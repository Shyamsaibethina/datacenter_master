'use client';

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import Map, { Marker, Source, Layer, Popup } from 'react-map-gl/mapbox';
import type { MapRef } from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';
import type { MapMouseEvent } from 'mapbox-gl';
import ChatSidebar, { type ChatMapContext } from './ChatSidebar';
import { apiClient, type SiteCandidate } from '../../lib/api-client';
import { formatCandidatesContext } from '../../lib/site-analysis';

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? '';

interface LngLat {
  lng: number;
  lat: number;
}

interface ChatSidebarState {
  isOpen: boolean;
  location: LngLat;
  initialPrompt?: string;
}

interface GridSpacing {
  dlat: number;
  dlon: number;
}

const TOP_N_MARKERS = 8;

function scoreColor(score: number): string {
  if (score >= 0.7) return '#16a34a';
  if (score >= 0.5) return '#d97706';
  return '#dc2626';
}

function boxPolygon(a: LngLat, b: LngLat): GeoJSON.Feature {
  const minLng = Math.min(a.lng, b.lng);
  const maxLng = Math.max(a.lng, b.lng);
  const minLat = Math.min(a.lat, b.lat);
  const maxLat = Math.max(a.lat, b.lat);
  return {
    type: 'Feature',
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [minLng, minLat],
        [maxLng, minLat],
        [maxLng, maxLat],
        [minLng, maxLat],
        [minLng, minLat],
      ]],
    },
    properties: {},
  };
}

function buildSitePrompt(c: SiteCandidate): string {
  const pct = Math.round(c.overall_score * 100);
  const reasons = c.reasons.map((r) => `- ${r}`).join('\n');
  return (
    `This candidate datacenter site at ${c.coordinates.lat.toFixed(4)}, ${c.coordinates.lon.toFixed(4)} ` +
    `scored ${pct}/100 overall.\n\nKey factors:\n${reasons}\n\n` +
    `Explain whether this is a strong location for a datacenter and what the main risks are.`
  );
}

export default function MapViewer() {
  const mapRef = useRef<MapRef>(null);
  const [viewState, setViewState] = useState({
    longitude: -95.7129,
    latitude: 37.0902,
    zoom: 4,
  });

  const [drawMode, setDrawMode] = useState(false);
  const [dragStart, setDragStart] = useState<LngLat | null>(null);
  const [previewBox, setPreviewBox] = useState<GeoJSON.Feature | null>(null);
  const [searchBox, setSearchBox] = useState<GeoJSON.Feature | null>(null);

  const [cells, setCells] = useState<SiteCandidate[]>([]);
  const [grid, setGrid] = useState<GridSpacing | null>(null);
  const [selected, setSelected] = useState<SiteCandidate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [overlayOn, setOverlayOn] = useState<{ transmission: boolean; water: boolean }>({
    transmission: false,
    water: false,
  });
  const [overlayData, setOverlayData] = useState<{
    transmission: GeoJSON.FeatureCollection | null;
    water: GeoJSON.FeatureCollection | null;
  }>({ transmission: null, water: null });
  const [overlayLoading, setOverlayLoading] = useState<{ transmission: boolean; water: boolean }>({
    transmission: false,
    water: false,
  });
  const [overlayInfo, setOverlayInfo] = useState<
    { lng: number; lat: number; title: string; lines: string[] } | null
  >(null);

  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [explLoading, setExplLoading] = useState(false);

  const [pinnedSites, setPinnedSites] = useState<SiteCandidate[]>([]);
  const [searchSummary, setSearchSummary] = useState<string | undefined>();
  const [chatSidebar, setChatSidebar] = useState<ChatSidebarState>({
    isOpen: false,
    location: { lng: 0, lat: 0 },
  });

  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;
    if (drawMode) map.dragPan.disable();
    else map.dragPan.enable();
  }, [drawMode]);

  const markerCells = useMemo(
    () => [...cells].sort((a, b) => b.overall_score - a.overall_score).slice(0, TOP_N_MARKERS),
    [cells]
  );

  const heatmapData = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!grid || grid.dlat <= 0 || grid.dlon <= 0 || cells.length === 0) return null;
    const halfLat = grid.dlat / 2;
    const halfLon = grid.dlon / 2;
    return {
      type: 'FeatureCollection',
      features: cells.map((c) => {
        const { lat, lon } = c.coordinates;
        return {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [[
              [lon - halfLon, lat - halfLat],
              [lon + halfLon, lat - halfLat],
              [lon + halfLon, lat + halfLat],
              [lon - halfLon, lat + halfLat],
              [lon - halfLon, lat - halfLat],
            ]],
          },
          properties: {
            score: c.overall_score,
            key: `${lat},${lon}`,
          },
        };
      }),
    };
  }, [grid, cells]);

  const runSearch = useCallback(async (corner1: LngLat, corner2: LngLat) => {
    const bbox = {
      min_lat: Math.min(corner1.lat, corner2.lat),
      min_lon: Math.min(corner1.lng, corner2.lng),
      max_lat: Math.max(corner1.lat, corner2.lat),
      max_lon: Math.max(corner1.lng, corner2.lng),
    };
    setLoading(true);
    setError(null);
    setCells([]);
    setGrid(null);
    setSelected(null);
    try {
      // fast=true: local DuckDB only (power + fiber), skips slow external APIs
      const res = await apiClient.findSiteCandidates({
        ...bbox,
        grid_size: 5,
        top_k: TOP_N_MARKERS,
        fast: true,
      });
      const scored = res.cells ?? res.candidates ?? [];
      setCells(scored);
      setGrid({ dlat: res.cell_dlat, dlon: res.cell_dlon });
      const top = [...scored].sort((a, b) => b.overall_score - a.overall_score).slice(0, TOP_N_MARKERS);
      setSearchSummary(formatCandidatesContext(top, 'Rectangle search — top sites'));
      if (scored.length === 0) {
        setError('No candidate sites could be scored in that area.');
      }
    } catch (e) {
      console.error(e);
      setError('Failed to score this area. Is the API running on localhost:8000?');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleMouseDown = useCallback(
    (event: MapMouseEvent) => {
      if (!drawMode) return;
      setDragStart({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      setPreviewBox(null);
    },
    [drawMode]
  );

  const handleMouseMove = useCallback(
    (event: MapMouseEvent) => {
      if (!drawMode || !dragStart) return;
      setPreviewBox(boxPolygon(dragStart, { lng: event.lngLat.lng, lat: event.lngLat.lat }));
    },
    [drawMode, dragStart]
  );

  const handleMouseUp = useCallback(
    (event: MapMouseEvent) => {
      if (!drawMode || !dragStart) return;
      const end = { lng: event.lngLat.lng, lat: event.lngLat.lat };
      if (Math.abs(end.lng - dragStart.lng) < 1e-4 && Math.abs(end.lat - dragStart.lat) < 1e-4) {
        setDragStart(null);
        return;
      }
      setSearchBox(boxPolygon(dragStart, end));
      setPreviewBox(null);
      setDrawMode(false);
      runSearch(dragStart, end);
      setDragStart(null);
    },
    [drawMode, dragStart, runSearch]
  );

  const handleMapClick = useCallback(
    (event: MapMouseEvent) => {
      if (drawMode) return;
      const feats = event.features ?? [];

      const tx = feats.find((f) => f.layer?.id === 'overlay-transmission');
      if (tx) {
        const p = tx.properties ?? {};
        const voltage = p.VOLTAGE ?? p.voltage ?? p.voltage_kv ?? p.VOLT_CLASS;
        setOverlayInfo({
          lng: event.lngLat.lng,
          lat: event.lngLat.lat,
          title: 'Transmission line',
          lines: [
            voltage != null ? `Voltage: ${voltage} kV` : 'Voltage: n/a',
            p.OWNER || p.owner ? `Owner: ${p.OWNER ?? p.owner}` : '',
            p.distance_km != null ? `${Number(p.distance_km).toFixed(1)} km from query point` : '',
          ].filter(Boolean),
        });
        return;
      }

      const wt = feats.find((f) => f.layer?.id === 'overlay-water');
      if (wt) {
        const p = wt.properties ?? {};
        setOverlayInfo({
          lng: event.lngLat.lng,
          lat: event.lngLat.lat,
          title: 'Water monitoring site',
          lines: [
            p.name ? `${p.name}` : '',
            `Type: ${p.kind === 'groundwater' ? 'Groundwater' : 'Surface water'}`,
            p.identifier ? `USGS ID: ${p.identifier}` : '',
          ].filter(Boolean),
        });
        return;
      }

      const cell = feats.find((f) => f.layer?.id === 'suitability-fill');
      if (cell?.properties?.key) {
        const hit = cells.find(
          (c) => `${c.coordinates.lat},${c.coordinates.lon}` === cell.properties!.key
        );
        if (hit) {
          setSelected(hit);
          setOverlayInfo(null);
          return;
        }
      }

      setSelected(null);
      setOverlayInfo(null);
    },
    [drawMode, cells]
  );

  const openChat = useCallback((prompt?: string) => {
    setChatSidebar({
      isOpen: true,
      location: { lng: viewState.longitude, lat: viewState.latitude },
      initialPrompt: prompt,
    });
  }, [viewState]);

  const togglePin = useCallback((site: SiteCandidate) => {
    const key = `${site.coordinates.lat},${site.coordinates.lon}`;
    setPinnedSites((prev) => {
      const exists = prev.some((p) => `${p.coordinates.lat},${p.coordinates.lon}` === key);
      if (exists) return prev.filter((p) => `${p.coordinates.lat},${p.coordinates.lon}` !== key);
      if (prev.length >= 4) return prev;
      return [...prev, site];
    });
  }, []);

  const isPinned = useCallback(
    (site: SiteCandidate) =>
      pinnedSites.some(
        (p) =>
          p.coordinates.lat === site.coordinates.lat && p.coordinates.lon === site.coordinates.lon
      ),
    [pinnedSites]
  );

  const mapContext: ChatMapContext = useMemo(
    () => ({
      mapCandidates: markerCells.length ? markerCells : cells.slice(0, TOP_N_MARKERS),
      pinnedSites,
      selectedSite: selected,
      searchSummary,
    }),
    [markerCells, cells, pinnedSites, selected, searchSummary]
  );

  const handleSitesFromChat = useCallback((sites: SiteCandidate[]) => {
    setCells(sites);
    setGrid(null);
    setSelected(null);
  }, []);

  const handleMapMoveFromChat = useCallback((center: { lat: number; lon: number }) => {
    setViewState((prev) => ({
      ...prev,
      latitude: center.lat,
      longitude: center.lon,
      zoom: Math.max(prev.zoom, 9),
    }));
  }, []);

  const fetchOverlay = useCallback(async (kind: 'transmission' | 'water') => {
    setOverlayLoading((prev) => ({ ...prev, [kind]: true }));
    try {
      const fc =
        kind === 'transmission'
          ? await apiClient.getTransmissionOverlayAll()
          : await apiClient.getWaterOverlayAll();
      setOverlayData((prev) => ({ ...prev, [kind]: fc }));
    } catch (e) {
      console.error(`Failed to load ${kind} overlay`, e);
    } finally {
      setOverlayLoading((prev) => ({ ...prev, [kind]: false }));
    }
  }, []);

  const toggleOverlay = useCallback(
    (kind: 'transmission' | 'water') => {
      setOverlayOn((prev) => {
        const turningOn = !prev[kind];
        const next = { ...prev, [kind]: turningOn };
        // One-time load per session — skip if already fetched.
        if (turningOn && !overlayData[kind]) fetchOverlay(kind);
        return next;
      });
    },
    [overlayData, fetchOverlay]
  );

  const siteKey = (c: SiteCandidate) => `${c.coordinates.lat},${c.coordinates.lon}`;

  useEffect(() => {
    if (!selected) return;
    const key = siteKey(selected);
    if (explanations[key]) return;
    let cancelled = false;
    setExplLoading(true);
    fetch('/api/explain-site', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(selected),
    })
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled && d.explanation) {
          setExplanations((prev) => ({ ...prev, [key]: d.explanation }));
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setExplLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  return (
    <div className="relative w-full h-screen">
      <div className="absolute top-4 left-4 z-10 bg-white rounded-lg shadow-lg p-4 max-w-xs space-y-3">
        <h3 className="font-semibold text-gray-900">Datacenter Site Finder</h3>
        <p className="text-sm text-gray-600">
          Draw a box to rank sites by power + connectivity, or use chat for full
          scoring near a city.
        </p>
        <button
          onClick={() => {
            setDrawMode((d) => !d);
            setError(null);
          }}
          className={`w-full px-3 py-2 rounded-md text-sm font-medium transition-colors ${
            drawMode
              ? 'bg-red-500 text-white hover:bg-red-600'
              : 'bg-blue-500 text-white hover:bg-blue-600'
          }`}
        >
          {drawMode ? 'Cancel drawing' : '▭ Draw search area'}
        </button>

        <div className="space-y-2 pt-1 border-t border-gray-100">
          <span className="text-xs font-semibold text-gray-700">Data layers (US-wide)</span>
          <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={overlayOn.transmission}
              onChange={() => toggleOverlay('transmission')}
              disabled={overlayLoading.transmission}
              className="accent-orange-500"
            />
            <span className="inline-block w-3 h-0.5 bg-orange-500" />
            {overlayLoading.transmission ? 'Loading transmission…' : 'Transmission lines'}
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={overlayOn.water}
              onChange={() => toggleOverlay('water')}
              disabled={overlayLoading.water}
              className="accent-sky-500"
            />
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-sky-500" />
            {overlayLoading.water ? 'Loading water sites…' : 'Water sites'}
          </label>
          <p className="text-xs text-gray-400">
            Loads entire US dataset once (cached after first toggle).
          </p>
        </div>

        {cells.length > 0 && (
          <>
            <p className="text-xs text-gray-500">
              {cells.length} sites · click a cell or marker for details
            </p>
            <button
              onClick={() =>
                openChat(
                  `I just searched this area. ${searchSummary ?? ''}\n\nWhy is the highest-scoring site ranked best? Which corners score lower and why?`
                )
              }
              className="w-full px-3 py-1.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200"
            >
              Discuss this search in chat
            </button>
          </>
        )}
        {pinnedSites.length > 0 && (
          <p className="text-xs text-indigo-600">{pinnedSites.length} site(s) pinned for compare/memo</p>
        )}
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>

      {grid && cells.length > 0 && (
        <div className="absolute top-4 right-4 z-10 bg-white rounded-lg shadow-lg p-3 space-y-1.5">
          <span className="text-xs font-semibold text-gray-700">Power + connectivity</span>
          <div
            className="h-2 w-40 rounded"
            style={{
              background: 'linear-gradient(to right, #dc2626 0%, #f59e0b 50%, #16a34a 100%)',
            }}
          />
          <div className="flex justify-between text-[10px] text-gray-500">
            <span>Poor</span>
            <span>Strong</span>
          </div>
        </div>
      )}

      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/20">
          <div className="bg-white rounded-lg shadow-xl px-6 py-4 flex items-center space-x-3">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-gray-700">Scoring area (power + fiber)…</span>
          </div>
        </div>
      )}

      <Map
        ref={mapRef}
        {...viewState}
        onMove={(evt) => setViewState(evt.viewState)}
        onClick={handleMapClick}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        mapboxAccessToken={MAPBOX_TOKEN}
        style={{ width: '100%', height: '100%' }}
        mapStyle="mapbox://styles/mapbox/streets-v12"
        cursor={drawMode ? 'crosshair' : 'pointer'}
        interactiveLayerIds={[
          ...(heatmapData ? ['suitability-fill'] : []),
          ...(overlayOn.transmission && overlayData.transmission ? ['overlay-transmission'] : []),
          ...(overlayOn.water && overlayData.water ? ['overlay-water'] : []),
        ]}
      >
        {heatmapData && (
          <Source id="suitability" type="geojson" data={heatmapData}>
            <Layer
              id="suitability-fill"
              type="fill"
              paint={{
                'fill-color': [
                  'interpolate',
                  ['linear'],
                  ['get', 'score'],
                  0, '#dc2626',
                  0.5, '#f59e0b',
                  0.75, '#16a34a',
                ],
                'fill-opacity': 0.5,
              }}
            />
          </Source>
        )}

        {overlayOn.transmission && overlayData.transmission && (
          <Source id="overlay-transmission-src" type="geojson" data={overlayData.transmission}>
            <Layer
              id="overlay-transmission"
              type="line"
              paint={{ 'line-color': '#f97316', 'line-width': 2, 'line-opacity': 0.85 }}
            />
          </Source>
        )}

        {overlayOn.water && overlayData.water && (
          <Source id="overlay-water-src" type="geojson" data={overlayData.water}>
            <Layer
              id="overlay-water"
              type="circle"
              paint={{
                'circle-radius': 5,
                'circle-color': ['match', ['get', 'kind'], 'groundwater', '#7c3aed', '#0ea5e9'],
                'circle-stroke-color': '#ffffff',
                'circle-stroke-width': 1,
                'circle-opacity': 0.9,
              }}
            />
          </Source>
        )}

        {searchBox && (
          <Source id="search-box" type="geojson" data={searchBox}>
            <Layer id="search-box-line" type="line" paint={{ 'line-color': '#3b82f6', 'line-width': 2 }} />
          </Source>
        )}

        {previewBox && (
          <Source id="preview-box" type="geojson" data={previewBox}>
            <Layer id="preview-box-fill" type="fill" paint={{ 'fill-color': '#3b82f6', 'fill-opacity': 0.12 }} />
            <Layer
              id="preview-box-line"
              type="line"
              paint={{ 'line-color': '#3b82f6', 'line-width': 2, 'line-dasharray': [2, 1] }}
            />
          </Source>
        )}

        {markerCells.map((c) => (
          <Marker
            key={siteKey(c)}
            longitude={c.coordinates.lon}
            latitude={c.coordinates.lat}
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              setSelected(c);
              setOverlayInfo(null);
            }}
          >
            <div
              className="flex items-center justify-center rounded-full text-white text-xs font-bold shadow-md cursor-pointer border-2 border-white"
              style={{ width: 30, height: 30, backgroundColor: scoreColor(c.overall_score) }}
              title={`Score ${Math.round(c.overall_score * 100)}/100`}
            >
              {Math.round(c.overall_score * 100)}
            </div>
          </Marker>
        ))}

        {selected && (
          <Popup
            longitude={selected.coordinates.lon}
            latitude={selected.coordinates.lat}
            anchor="bottom"
            offset={20}
            onClose={() => setSelected(null)}
            closeOnClick={false}
            maxWidth="320px"
          >
            <div className="space-y-2">
              <div className="flex items-baseline justify-between">
                <span className="font-semibold text-gray-900">Suitability</span>
                <span
                  className="text-lg font-bold"
                  style={{ color: scoreColor(selected.overall_score) }}
                >
                  {Math.round(selected.overall_score * 100)}/100
                </span>
              </div>
              <p className="text-xs text-gray-500">
                {selected.coordinates.lat.toFixed(4)}, {selected.coordinates.lon.toFixed(4)}
              </p>
              <div className="text-xs text-gray-700 bg-blue-50 rounded p-2 leading-snug">
                {explanations[siteKey(selected)] ? (
                  explanations[siteKey(selected)]
                ) : explLoading ? (
                  <span className="text-gray-400 italic">Generating AI summary…</span>
                ) : (
                  <span className="text-gray-400 italic">No AI summary available.</span>
                )}
              </div>
              <div className="space-y-1">
                {Object.entries(selected.subscores).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <span className="w-20 text-xs capitalize text-gray-600">{k}</span>
                    <div className="flex-1 h-2 bg-gray-200 rounded">
                      <div
                        className="h-2 rounded"
                        style={{ width: `${Math.round(v * 100)}%`, backgroundColor: scoreColor(v) }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <ul className="text-xs text-gray-700 list-disc pl-4 space-y-0.5">
                {selected.reasons.map((r, idx) => (
                  <li key={idx}>{r}</li>
                ))}
              </ul>
              <div className="flex gap-2 mt-1">
                <button
                  onClick={() => openChat(buildSitePrompt(selected))}
                  className="flex-1 px-3 py-1.5 bg-blue-500 text-white rounded-md text-xs font-medium hover:bg-blue-600"
                >
                  Ask AI
                </button>
                <button
                  onClick={() => togglePin(selected)}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium border ${
                    isPinned(selected)
                      ? 'bg-indigo-100 text-indigo-800 border-indigo-300'
                      : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  {isPinned(selected) ? 'Unpin' : 'Pin'}
                </button>
              </div>
            </div>
          </Popup>
        )}

        {overlayInfo && (
          <Popup
            longitude={overlayInfo.lng}
            latitude={overlayInfo.lat}
            anchor="bottom"
            offset={12}
            onClose={() => setOverlayInfo(null)}
            closeOnClick={false}
            maxWidth="240px"
          >
            <div className="space-y-1">
              <span className="font-semibold text-gray-900 text-sm">{overlayInfo.title}</span>
              <ul className="text-xs text-gray-700 space-y-0.5">
                {overlayInfo.lines.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </div>
          </Popup>
        )}
      </Map>

      <ChatSidebar
        isOpen={chatSidebar.isOpen}
        mapContext={mapContext}
        initialPrompt={chatSidebar.initialPrompt}
        pinnedSites={pinnedSites}
        onClose={() => setChatSidebar((p) => ({ ...p, isOpen: false }))}
        onSitesFound={handleSitesFromChat}
        onMapMove={handleMapMoveFromChat}
      />

      {!chatSidebar.isOpen && (
        <button
          onClick={() => openChat()}
          className="absolute bottom-6 left-6 z-10 w-14 h-14 bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-lg flex items-center justify-center transition-colors"
          title="Ask the AI assistant"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
        </button>
      )}
    </div>
  );
}
