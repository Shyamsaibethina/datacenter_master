"""
Geocoding API endpoints.
Uses Photon (Komoot) as primary geocoder with Nominatim as fallback.
Caches all results in-memory since city coordinates are stable.
"""
import asyncio
import logging
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from urllib.parse import quote
from typing import Dict, Optional

from models import GeocodingResult, Coordinates

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

# Pre-seeded cache of major US metro areas commonly queried for datacenter siting
_SEED_CACHE: Dict[str, GeocodingResult] = {
    k: GeocodingResult(city=v[0], display_name=v[1], coordinates=Coordinates(lat=v[2], lon=v[3]), source="built-in")
    for k, v in {
        "columbus, ohio": ("Columbus, Ohio", "Columbus, Franklin County, Ohio, USA", 39.9612, -82.9988),
        "columbus, oh": ("Columbus, OH", "Columbus, Franklin County, Ohio, USA", 39.9612, -82.9988),
        "dallas, tx": ("Dallas, TX", "Dallas, Dallas County, Texas, USA", 32.7767, -96.7970),
        "dallas, texas": ("Dallas, Texas", "Dallas, Dallas County, Texas, USA", 32.7767, -96.7970),
        "ashburn, va": ("Ashburn, VA", "Ashburn, Loudoun County, Virginia, USA", 39.0438, -77.4874),
        "ashburn, virginia": ("Ashburn, Virginia", "Ashburn, Loudoun County, Virginia, USA", 39.0438, -77.4874),
        "phoenix, az": ("Phoenix, AZ", "Phoenix, Maricopa County, Arizona, USA", 33.4484, -112.0740),
        "phoenix, arizona": ("Phoenix, Arizona", "Phoenix, Maricopa County, Arizona, USA", 33.4484, -112.0740),
        "san jose, ca": ("San Jose, CA", "San Jose, Santa Clara County, California, USA", 37.3382, -121.8863),
        "san jose, california": ("San Jose, California", "San Jose, Santa Clara County, California, USA", 37.3382, -121.8863),
        "chicago, il": ("Chicago, IL", "Chicago, Cook County, Illinois, USA", 41.8781, -87.6298),
        "chicago, illinois": ("Chicago, Illinois", "Chicago, Cook County, Illinois, USA", 41.8781, -87.6298),
        "atlanta, ga": ("Atlanta, GA", "Atlanta, Fulton County, Georgia, USA", 33.7490, -84.3880),
        "atlanta, georgia": ("Atlanta, Georgia", "Atlanta, Fulton County, Georgia, USA", 33.7490, -84.3880),
        "des moines, iowa": ("Des Moines, Iowa", "Des Moines, Polk County, Iowa, USA", 41.5868, -93.6250),
        "des moines, ia": ("Des Moines, IA", "Des Moines, Polk County, Iowa, USA", 41.5868, -93.6250),
        "new york, ny": ("New York, NY", "New York, New York, USA", 40.7128, -74.0060),
        "los angeles, ca": ("Los Angeles, CA", "Los Angeles, Los Angeles County, California, USA", 34.0522, -118.2437),
        "seattle, wa": ("Seattle, WA", "Seattle, King County, Washington, USA", 47.6062, -122.3321),
        "portland, or": ("Portland, OR", "Portland, Multnomah County, Oregon, USA", 45.5152, -122.6784),
        "denver, co": ("Denver, CO", "Denver, Denver County, Colorado, USA", 39.7392, -104.9903),
        "salt lake city, ut": ("Salt Lake City, UT", "Salt Lake City, Salt Lake County, Utah, USA", 40.7608, -111.8910),
        "san antonio, tx": ("San Antonio, TX", "San Antonio, Bexar County, Texas, USA", 29.4241, -98.4936),
        "houston, tx": ("Houston, TX", "Houston, Harris County, Texas, USA", 29.7604, -95.3698),
        "reno, nv": ("Reno, NV", "Reno, Washoe County, Nevada, USA", 39.5296, -119.8138),
        "las vegas, nv": ("Las Vegas, NV", "Las Vegas, Clark County, Nevada, USA", 36.1699, -115.1398),
    }.items()
}

_geocode_cache: Dict[str, GeocodingResult] = dict(_SEED_CACHE)


class GeocodeRequest(BaseModel):
    city: str


import os

MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN")


async def _try_mapbox(city: str, client: httpx.AsyncClient) -> Optional[GeocodingResult]:
    """Mapbox Search API — generous free tier, reliable."""
    if not MAPBOX_TOKEN:
        return None
    encoded = quote(city.strip())
    url = f"https://api.mapbox.com/search/geocode/v6/forward?q={encoded}&country=us&types=place&limit=1&access_token={MAPBOX_TOKEN}"
    try:
        resp = await client.get(url)
        if not resp.is_success:
            logger.warning(f"Mapbox geocode returned {resp.status_code}")
            return None
        data = resp.json()
        features = data.get("features", [])
        if not features:
            return None
        feat = features[0]
        coords = feat["geometry"]["coordinates"]  # [lon, lat]
        lon, lat = float(coords[0]), float(coords[1])
        display = feat.get("properties", {}).get("full_address", city)
        return GeocodingResult(
            city=city,
            display_name=display,
            coordinates=Coordinates(lat=lat, lon=lon),
            source="Mapbox"
        )
    except Exception as e:
        logger.warning(f"Mapbox geocode failed: {e}")
        return None


async def _try_nominatim(city: str, client: httpx.AsyncClient) -> Optional[GeocodingResult]:
    """Nominatim fallback — may 403/429 if banned."""
    encoded = quote(city.strip())
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={encoded}&limit=1&countrycodes=us"
    await asyncio.sleep(1.1)
    try:
        resp = await client.get(url, headers={"User-Agent": "DatacenterPlanningApp/1.0 (contact@datacenterplanning.com)"})
        if not resp.is_success:
            return None
        data = resp.json()
        if not data:
            return None
        result = data[0]
        lat, lon = float(result["lat"]), float(result["lon"])
        return GeocodingResult(
            city=city,
            display_name=result.get("display_name", city),
            coordinates=Coordinates(lat=lat, lon=lon),
            source="OpenStreetMap Nominatim"
        )
    except Exception as e:
        logger.warning(f"Nominatim geocode failed: {e}")
        return None


@router.post("/geocode", response_model=GeocodingResult)
async def geocode_endpoint(request: GeocodeRequest) -> GeocodingResult:
    """
    Geocoding endpoint. Tries cache → Photon → Nominatim.
    All successes are cached in-memory permanently.
    """
    city = request.city
    if not city or not isinstance(city, str):
        raise HTTPException(status_code=400, detail="City name is required")

    cache_key = city.strip().lower()
    if cache_key in _geocode_cache:
        logger.info(f"Geocode cache HIT: {city}")
        return _geocode_cache[cache_key]

    async with httpx.AsyncClient(timeout=15.0) as client:
        result = await _try_mapbox(city, client)
        if not result:
            result = await _try_nominatim(city, client)

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f'Could not find coordinates for "{city}". Please try a more specific location (e.g., "San Francisco, CA")'
        )

    if not (-90 <= result.coordinates.lat <= 90) or not (-180 <= result.coordinates.lon <= 180):
        raise HTTPException(status_code=500, detail="Invalid coordinates received from geocoding service")

    _geocode_cache[cache_key] = result
    logger.info(f"Geocoded '{city}' → ({result.coordinates.lat}, {result.coordinates.lon}) via {result.source}")
    return result

