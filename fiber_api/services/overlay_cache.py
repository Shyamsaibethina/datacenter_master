"""
One-time overlay datasets for the map (full US transmission + water sites).

Built once, cached to disk under data_cache/overlays/, kept in memory after load.
"""
import asyncio
import json
import logging
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

import httpx

from config import API_CONFIG, STATE_BOUNDS
from database import LOCAL_DATA_DIR, get_all_transmission_geojson

logger = logging.getLogger("uvicorn.error")

OVERLAY_DIR = os.path.join(LOCAL_DATA_DIR, "overlays")
TRANSMISSION_CACHE = os.path.join(OVERLAY_DIR, "transmission_all.json")
WATER_CACHE = os.path.join(OVERLAY_DIR, "water_all.json")

_transmission_mem: Optional[Dict[str, Any]] = None
_water_mem: Optional[Dict[str, Any]] = None


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


async def _fetch_state_water(client: httpx.AsyncClient, abbr: str, bounds: tuple) -> list:
    west, south, east, north = bounds
    bbox = f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"
    base = f"https://waterservices.usgs.gov/nwis/site/?format=mapper&bBox={bbox}&siteStatus=active"
    headers = {"User-Agent": API_CONFIG["USER_AGENT"]}

    async def _fetch(site_type: str) -> list:
        url = f"{base}&siteType={site_type}"
        try:
            resp = await client.get(url, headers=headers, timeout=45.0)
            if not resp.is_success:
                return []
            root = ET.fromstring(resp.text)
            features = []
            for s in root.findall(".//site"):
                try:
                    slon = float(s.get("lng", 0))
                    slat = float(s.get("lat", 0))
                except (TypeError, ValueError):
                    continue
                kind = "groundwater" if site_type == "GW" else "surface"
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [slon, slat]},
                    "properties": {
                        "identifier": s.get("sno"),
                        "name": s.get("sna"),
                        "agency": s.get("agc", "USGS"),
                        "kind": kind,
                    },
                })
            return features
        except Exception as e:
            logger.warning(f"Water fetch failed for {abbr} ({site_type}): {e}")
            return []

    st, gw = await asyncio.gather(_fetch("ST"), _fetch("GW"))
    return st + gw


async def _build_water_all() -> Dict[str, Any]:
    logger.info("Building US water overlay (all states, first time only)…")
    sem = asyncio.Semaphore(8)

    async def _one(abbr: str, bounds: tuple) -> list:
        async with sem:
            async with httpx.AsyncClient() as client:
                return await _fetch_state_water(client, abbr, bounds)

    batches = await asyncio.gather(
        *[_one(abbr, bounds) for abbr, bounds in STATE_BOUNDS.items()]
    )

    seen: set = set()
    features = []
    for batch in batches:
        for feat in batch:
            sid = feat["properties"].get("identifier")
            if sid and sid in seen:
                continue
            if sid:
                seen.add(sid)
            features.append(feat)

    data = {"type": "FeatureCollection", "count": len(features), "features": features}
    _write_json(WATER_CACHE, data)
    logger.info(f"Water overlay cached: {len(features)} sites")
    return data


def get_transmission_overlay_all() -> Dict[str, Any]:
    global _transmission_mem
    if _transmission_mem is not None:
        return _transmission_mem

    cached = _read_json(TRANSMISSION_CACHE)
    if cached is not None:
        _transmission_mem = cached
        return cached

    data = get_all_transmission_geojson()
    _write_json(TRANSMISSION_CACHE, data)
    _transmission_mem = data
    return data


async def get_water_overlay_all() -> Dict[str, Any]:
    global _water_mem
    if _water_mem is not None:
        return _water_mem

    cached = _read_json(WATER_CACHE)
    if cached is not None and cached.get("count", 0) > 0:
        _water_mem = cached
        return cached

    data = await _build_water_all()
    _water_mem = data
    return data
