"""
Site features, scoring, and training dataset API endpoints.
"""
import logging
import asyncio
from typing import List, Optional, Dict
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.data_fetchers import (
    get_broadband_data_raw, get_transmission_lines_raw, get_weather_data_raw,
    get_water_resources_raw, get_transportation_counts_raw
)
from utils import safe_mean, safe_min, safe_count, safe_float, sanitize_value, sanitize_float
from cache import cache_key, get_from_cache, set_cache, get_cache_stats, clear_cache

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

# Cache configuration
CACHE_PRECISION = 6  # ~1.2 km cells - good balance
CACHE_TTL = 3600  # 1 hour


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float


class TrainingDatasetRequest(BaseModel):
    coordinates: List[CoordinatesRequest]
    include_target: Optional[bool] = False


class ScoreRequest(BaseModel):
    lat: float
    lon: float
    # Optional per-domain weight overrides. Missing keys fall back to defaults,
    # and the final set is renormalized to sum to 1 so callers can't skew totals.
    weights: Optional[dict] = None


class CandidatesRequest(BaseModel):
    # Bounding box of the region the user drew on the map.
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    grid_size: int = 5          # NxN lattice; 5 -> 25 points
    top_k: int = 10
    weights: Optional[dict] = None   # optional per-domain weight override
    # Fast grid scoring: local DuckDB only (transmission + broadband). Skips
    # Open-Meteo / USGS / Overpass — the sources that made rectangle draw 60s+.
    fast: bool = True


# ──────────────────────────────────────────────────────────────────────────────
# Scoring helpers (pure functions, no I/O — reused by /site-score and /site-candidates)
# ──────────────────────────────────────────────────────────────────────────────

# Wind intentionally excluded: site_features_endpoint never fetches turbine data,
# so the old wind_score was always 0 and silently dragged overall_score down.
# Remaining weights renormalized to sum to 1.0.
DEFAULT_WEIGHTS = {
    "broadband": 0.30,
    "transmission": 0.25,
    "climate": 0.20,
    "water": 0.15,
    "transport": 0.10,
}


def normalize(value, min_val, max_val):
    """Linear normalization to 0-1 range. None -> 0."""
    if value is None:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def compute_subscores(features: dict) -> dict:
    """Map a raw feature vector to per-domain 0-1 subscores."""
    broadband = normalize(features.get("avg_download_speed_mbps"), 100, 1000)
    transmission = 1 - normalize(features.get("nearest_transmission_km"), 0, 50)

    # Climate: closer to 70F average high is better for cooling efficiency.
    # If temp data is missing, score neutral (0.5) instead of falsely perfect —
    # a null avg_temp_max_f must not read as an ideal 70F.
    avg_temp_max = features.get("avg_temp_max_f")
    if avg_temp_max is None:
        climate = 0.5
    else:
        temp_deviation = abs(avg_temp_max - 70)
        climate = 1 - normalize(temp_deviation, 0, 30)

    surf = features.get("num_surface_water_sites")
    ground = features.get("num_groundwater_sites")
    if surf is None and ground is None:
        water = 0.5
    else:
        water = normalize((surf or 0) + (ground or 0), 0, 20)

    hw = features.get("num_highways_within_50km")
    rw = features.get("num_railways_within_100km")
    if hw is None and rw is None:
        transport = 0.5
    else:
        transport_count = (hw or 0) + (rw or 0)
        transport = normalize(transport_count, 0, 10)

    return {
        "broadband": round(broadband, 3),
        "transmission": round(transmission, 3),
        "climate": round(climate, 3),
        "water": round(water, 3),
        "transport": round(transport, 3),
    }


def compute_score(features: dict, weights: Optional[dict] = None) -> dict:
    """
    Compute overall suitability score + subscores from a feature vector.
    Overall is normalized by the sum of weights actually used, so partial
    weight overrides still yield a 0-1 score.
    """
    subscores = compute_subscores(features)
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    # Only weight domains we actually have a subscore for.
    active = {k: w[k] for k in subscores if k in w and w[k] is not None}
    weight_sum = sum(active.values()) or 1.0

    overall = sum(subscores[k] * active[k] for k in active) / weight_sum

    return {"overall_score": round(overall, 3), "subscores": subscores}


def build_reasons(subscores: dict, features: dict) -> List[str]:
    """
    Deterministic human-readable explanations of why a site scores the way it
    does. Cheap and side-effect free — feeds the map popup and the LLM prompt.
    """
    reasons: List[str] = []

    nt = features.get("nearest_transmission_km")
    if nt is not None:
        if nt <= 5:
            reasons.append(f"Transmission line {nt:.1f} km away — strong grid access")
        elif nt <= 20:
            reasons.append(f"Nearest transmission line {nt:.1f} km away — moderate grid access")
        else:
            reasons.append(f"Nearest transmission line {nt:.1f} km away — limited grid access")

    dl = features.get("avg_download_speed_mbps")
    nfib = features.get("num_fiber_providers")
    if dl is not None:
        fiber_note = f", {int(nfib)} fiber provider(s)" if nfib else ""
        if dl >= 500:
            reasons.append(f"Avg broadband {dl:.0f} Mbps{fiber_note} — excellent connectivity")
        elif dl >= 100:
            reasons.append(f"Avg broadband {dl:.0f} Mbps{fiber_note} — adequate connectivity")
        else:
            reasons.append(f"Avg broadband {dl:.0f} Mbps{fiber_note} — weak connectivity")

    tmax = features.get("avg_temp_max_f")
    if tmax is not None:
        dev = abs(tmax - 70)
        if dev <= 10:
            reasons.append(f"Avg high {tmax:.0f}°F — favorable for cooling efficiency")
        elif dev <= 20:
            reasons.append(f"Avg high {tmax:.0f}°F — moderate cooling load")
        else:
            reasons.append(f"Avg high {tmax:.0f}°F — high cooling load")

    surf = features.get("num_surface_water_sites")
    ground = features.get("num_groundwater_sites")
    if surf is not None or ground is not None:
        water_sites = (surf or 0) + (ground or 0)
        if water_sites >= 8:
            reasons.append(f"{int(water_sites)} nearby water monitoring sites — good cooling-water options")
        elif water_sites > 0:
            reasons.append(f"{int(water_sites)} nearby water site(s) — limited cooling-water options")
        else:
            reasons.append("No nearby water sites detected — cooling-water supply uncertain")

    highways = features.get("num_highways_within_50km")
    railways = features.get("num_railways_within_100km")
    if highways is None and railways is None:
        reasons.append("Transportation data unavailable — logistics score estimated as neutral")
    elif (highways or 0) + (railways or 0) > 0:
        reasons.append(
            f"{int(highways or 0)} major highway(s) and {int(railways or 0)} rail line(s) nearby — solid logistics access"
        )
    else:
        reasons.append("Sparse transportation infrastructure nearby — logistics may be challenging")

    return reasons


def _features_from_sources(
    broadband: dict,
    transmission: dict,
    climate: dict,
    water: dict,
    transport: dict,
    *,
    fast: bool,
) -> dict:
    """Turn raw fetcher outputs into a numeric feature vector."""
    broadband_results = broadband.get("results", [])
    avg_download = safe_mean([b.get("max_down") for b in broadband_results])
    avg_upload = safe_mean([b.get("max_up") for b in broadband_results])
    num_providers = len(set(b.get("provider") for b in broadband_results if b.get("provider")))
    num_fiber = len([b for b in broadband_results if b.get("tech_code") in [50, "50"]])

    transmission_features = transmission.get("features", [])
    if not transmission_features:
        transmission_features = transmission.get("lines", [])

    voltages = []
    distances = []
    for line in transmission_features:
        v = line.get("voltage_kv")
        if v is None:
            props = line.get("properties", {})
            v = props.get("VOLTAGE") or props.get("voltage") or props.get("voltage_kv")
        if v is not None and v > 0:
            voltages.append(v)
        dist = line.get("distance_km")
        if dist is None:
            dist = line.get("properties", {}).get("distance_km")
        if dist is not None:
            distances.append(dist)

    if fast:
        return {
            "avg_download_speed_mbps": sanitize_float(avg_download),
            "avg_upload_speed_mbps": sanitize_float(avg_upload),
            "num_providers": sanitize_float(num_providers),
            "num_fiber_providers": sanitize_float(num_fiber),
            "avg_voltage_kv": sanitize_float(safe_mean(voltages)),
            "nearest_transmission_km": sanitize_float(safe_min(distances)),
            "num_transmission_lines": sanitize_float(len(transmission_features)),
            "avg_temp_max_f": None,
            "avg_temp_min_f": None,
            "avg_precip_in": None,
            "avg_wind_speed_mph": None,
            "temp_variability_index": None,
            "wind_solar_complementarity": None,
            "num_surface_water_sites": None,
            "num_groundwater_sites": None,
            "num_highways_within_50km": None,
            "num_railways_within_100km": None,
        }

    climate_metrics = climate.get("metrics", {}) if isinstance(climate, dict) else {}
    surface_water = water.get("surface_water_sites", {})
    groundwater = water.get("groundwater_sites", {})
    transport_error = transport.get("error")
    num_highways = None if transport_error else transport.get("num_highways", 0)
    num_railways = None if transport_error else transport.get("num_railways", 0)

    return {
        "avg_download_speed_mbps": sanitize_float(avg_download),
        "avg_upload_speed_mbps": sanitize_float(avg_upload),
        "num_providers": sanitize_float(num_providers),
        "num_fiber_providers": sanitize_float(num_fiber),
        "avg_voltage_kv": sanitize_float(safe_mean(voltages)),
        "nearest_transmission_km": sanitize_float(safe_min(distances)),
        "num_transmission_lines": sanitize_float(len(transmission_features)),
        "avg_temp_max_f": sanitize_float(safe_float(climate_metrics.get("avg_temp_max_f"))),
        "avg_temp_min_f": sanitize_float(safe_float(climate_metrics.get("avg_temp_min_f"))),
        "avg_precip_in": sanitize_float(safe_float(climate_metrics.get("avg_precip_in"))),
        "avg_wind_speed_mph": sanitize_float(safe_float(climate_metrics.get("avg_wind_speed_mph"))),
        "temp_variability_index": sanitize_float(safe_float(climate_metrics.get("temp_variability_index"))),
        "wind_solar_complementarity": None,
        "num_surface_water_sites": sanitize_float(
            len(surface_water.get("features", [])) if isinstance(surface_water, dict) else 0
        ),
        "num_groundwater_sites": sanitize_float(
            len(groundwater.get("features", [])) if isinstance(groundwater, dict) else 0
        ),
        "num_highways_within_50km": sanitize_float(num_highways),
        "num_railways_within_100km": sanitize_float(num_railways),
    }


async def fetch_site_features(lat: float, lon: float, *, fast: bool = False) -> dict:
    """
    Fetch + cache a feature vector for one point.

    fast=True: local DuckDB only (broadband + transmission) — used for rectangle
    grid scoring so we don't fan out to Open-Meteo / USGS / Overpass per cell.
    """
    coordinates = {"lat": lat, "lon": lon}
    ns = "features_fast" if fast else "features"
    key = cache_key(lat, lon, precision=CACHE_PRECISION, namespace=ns)
    cached = get_from_cache(key)
    if cached is not None:
        return cached

    if fast:
        broadband, transmission = await asyncio.gather(
            get_broadband_data_raw(coordinates),
            get_transmission_lines_raw(coordinates),
        )
        features = _features_from_sources(
            broadband, transmission, {}, {}, {}, fast=True
        )
    else:
        broadband, transmission, climate, water, transport = await asyncio.gather(
            get_broadband_data_raw(coordinates),
            get_transmission_lines_raw(coordinates),
            get_weather_data_raw(coordinates),
            get_water_resources_raw(coordinates),
            get_transportation_counts_raw(coordinates),
        )
        features = _features_from_sources(
            broadband, transmission, climate, water, transport, fast=False
        )

    result = sanitize_value({"coordinates": coordinates, "features": features})
    set_cache(key, result, ttl=CACHE_TTL)
    return result


@router.post("/api/site-features")
async def site_features_endpoint(request: CoordinatesRequest):
    """
    Aggregate all key metrics across domains into a numeric feature vector.
    Calls all existing APIs in parallel and extracts key features for ML/decision models.
    Uses geohash-based caching to avoid redundant API calls for nearby coordinates.
    """
    try:
        return await fetch_site_features(request.lat, request.lon, fast=False)
    except Exception as e:
        logger.exception(f"Site features aggregation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/training-dataset")
async def training_dataset_endpoint(request: TrainingDatasetRequest):
    """
    Generate a training dataset from multiple coordinates.
    Returns features suitable for ML training with proper data types and null handling.
    """
    try:
        dataset = []

        for coord in request.coordinates:
            try:
                # Get features for this coordinate
                features_response = await site_features_endpoint(coord)
                features = features_response["features"]

                # Add coordinate info
                row = {
                    "latitude": coord.lat,
                    "longitude": coord.lon,
                    **features
                }

                dataset.append(row)

            except Exception as e:
                logger.warning(f"Failed to get features for coordinates (lat: {coord.lat}, lon: {coord.lon}): {e}")
                continue

        if not dataset:
            raise HTTPException(status_code=400, detail="No valid coordinates provided or all failed to process")

        # Convert to format suitable for ML libraries
        df = pd.DataFrame(dataset)

        # Ensure proper data types
        numeric_columns = [
            'avg_download_speed_mbps', 'avg_upload_speed_mbps', 'num_providers', 'num_fiber_providers',
            'avg_voltage_kv', 'nearest_transmission_km', 'num_transmission_lines',
            'avg_temp_max_f', 'avg_temp_min_f', 'avg_precip_in', 'avg_wind_speed_mph', 'temp_variability_index',
            'num_surface_water_sites', 'num_groundwater_sites',
            'num_highways_within_50km', 'num_railways_within_100km'
        ]

        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Replace inf/NaN with None for JSON compliance
        df = df.replace([np.inf, -np.inf, np.nan], None)

        response = {
            "dataset": df.to_dict('records'),
            "metadata": {
                "num_samples": len(dataset),
                "feature_columns": list(df.columns),
                "numeric_features": numeric_columns,
                "coordinate_system": "WGS84"
            }
        }
        
        return sanitize_value(response)

    except Exception as e:
        logger.exception(f"Training dataset generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/site-score")
async def site_score_endpoint(request: ScoreRequest):
    """
    Compute a normalized site suitability score based on weighted subscores
    from each domain (broadband, energy, water, climate, transport).

    Accepts optional per-domain weight overrides; missing domains fall back to
    defaults and the result is renormalized so overall_score stays in 0-1.

    Returns:
    - overall_score: Weighted composite score (0-1)
    - subscores: Individual domain scores (0-1)
    - reasons: Deterministic human-readable rationale
    - features_used: Raw feature values
    """
    try:
        # site_features still takes plain coordinates.
        feature_resp = await site_features_endpoint(
            CoordinatesRequest(lat=request.lat, lon=request.lon)
        )
        features = feature_resp["features"]

        scored = compute_score(features, request.weights)
        reasons = build_reasons(scored["subscores"], features)

        return {
            "coordinates": feature_resp["coordinates"],
            "overall_score": scored["overall_score"],
            "subscores": scored["subscores"],
            "reasons": reasons,
            "features_used": features,
        }

    except Exception as e:
        logger.exception(f"Site scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Bound concurrent point scoring. Fast mode only hits local DuckDB (2 queries/point)
# so we can run more in parallel; full mode fans out to ~5 external APIs.
CANDIDATES_CONCURRENCY = 6
CANDIDATES_CONCURRENCY_FAST = 12
MAX_GRID_SIZE = 8


def _grid_points(min_lat, min_lon, max_lat, max_lon, n):
    """Generate an NxN lattice of (lat, lon) across the bbox (inclusive edges)."""
    if n <= 1:
        return [((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)]
    lats = [min_lat + (max_lat - min_lat) * i / (n - 1) for i in range(n)]
    lons = [min_lon + (max_lon - min_lon) * j / (n - 1) for j in range(n)]
    return [(lat, lon) for lat in lats for lon in lons]


@router.post("/api/site-candidates")
async def site_candidates_endpoint(request: CandidatesRequest):
    """
    Sample a grid of candidate sites across a bbox, score each, and return the
    top_k ranked sites with subscores and human-readable reasons.

    fast=True (default): local DuckDB only — power + fiber. Used for rectangle
    draw on the map. fast=False: full scoring via all external APIs (slow).
    """
    if request.max_lat <= request.min_lat or request.max_lon <= request.min_lon:
        raise HTTPException(status_code=400, detail="max_lat/max_lon must exceed min_lat/min_lon")

    grid_size = max(1, min(request.grid_size, MAX_GRID_SIZE))
    points = _grid_points(
        request.min_lat, request.min_lon, request.max_lat, request.max_lon, grid_size
    )

    concurrency = CANDIDATES_CONCURRENCY_FAST if request.fast else CANDIDATES_CONCURRENCY
    semaphore = asyncio.Semaphore(concurrency)

    async def score_point(lat: float, lon: float):
        async with semaphore:
            try:
                feature_resp = await fetch_site_features(lat, lon, fast=request.fast)
                features = feature_resp["features"]
                scored = compute_score(features, request.weights)
                reasons = build_reasons(scored["subscores"], features)
                if request.fast:
                    reasons.append("Grid score: power + connectivity only (fast mode)")
                row = {
                    "coordinates": {"lat": lat, "lon": lon},
                    "overall_score": scored["overall_score"],
                    "subscores": scored["subscores"],
                    "reasons": reasons,
                }
                if not request.fast:
                    row["features_used"] = features
                return row
            except Exception as e:
                logger.warning(f"Scoring failed for point ({lat}, {lon}): {e}")
                return None

    results = await asyncio.gather(*(score_point(lat, lon) for lat, lon in points))
    candidates = [r for r in results if r is not None]

    if not candidates:
        raise HTTPException(status_code=502, detail="All candidate points failed to score")

    candidates.sort(key=lambda c: c["overall_score"], reverse=True)
    top = candidates[: max(1, request.top_k)]

    # Cell spacing (degrees) so the client can draw each grid point as a filled
    # square for the weighted-overlay heatmap. Equals the gap between lattice
    # points; 0 when grid_size == 1.
    cell_dlat = (request.max_lat - request.min_lat) / (grid_size - 1) if grid_size > 1 else 0
    cell_dlon = (request.max_lon - request.min_lon) / (grid_size - 1) if grid_size > 1 else 0

    return sanitize_value({
        "bbox": {
            "min_lat": request.min_lat,
            "min_lon": request.min_lon,
            "max_lat": request.max_lat,
            "max_lon": request.max_lon,
        },
        "grid_size": grid_size,
        "cell_dlat": cell_dlat,
        "cell_dlon": cell_dlon,
        "num_scored": len(candidates),
        "num_requested": len(points),
        "candidates": top,
        # All scored cells (subscores are weight-independent, so the client can
        # recompute overall_score live as the user tunes weight sliders without
        # re-hitting the backend). Full payload is small (≤64 cells).
        "cells": candidates,
    })


@router.get("/api/cache/stats")
def cache_stats_endpoint():
    """
    Get cache statistics (hits, misses, size, hit rate).
    """
    return get_cache_stats()


@router.post("/api/cache/clear")
def cache_clear_endpoint():
    """
    Clear the entire cache. Use with caution.
    """
    clear_cache()
    return {"message": "Cache cleared successfully"}

