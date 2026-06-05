"""
Water resources API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from models import WaterResourcesResponse
from services.data_fetchers import get_water_resources_raw
from services.overlay_cache import get_water_overlay_all
from transformers import transform_water_resources

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float


@router.post("/api/water-resources", response_model=WaterResourcesResponse)
async def water_resources_endpoint(request: CoordinatesRequest) -> WaterResourcesResponse:
    """Get water resources data from USGS APIs."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_water_resources_raw(coordinates)
        return transform_water_resources(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Water resources API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/water/at_point")
async def water_at_point(
    lon: float = Query(..., description="Longitude (WGS84)"),
    lat: float = Query(..., description="Latitude (WGS84)"),
    radius_miles: float = Query(25.0, ge=1, le=60, description="Search radius in miles"),
):
    """Water monitoring sites near a point as a GeoJSON FeatureCollection.

    Lightweight map-overlay endpoint: returns surface + groundwater sites as
    Point features, each tagged with a `kind` property for client styling.
    """
    raw = await get_water_resources_raw({"lat": lat, "lon": lon, "radius_miles": radius_miles})

    features = []
    for feat in raw.get("surface_water_sites", {}).get("features", []):
        feat = {**feat, "properties": {**feat.get("properties", {}), "kind": "surface"}}
        features.append(feat)
    for feat in raw.get("groundwater_sites", {}).get("features", []):
        feat = {**feat, "properties": {**feat.get("properties", {}), "kind": "groundwater"}}
        features.append(feat)

    return {"type": "FeatureCollection", "count": len(features), "features": features}


@router.get("/water/all")
async def water_all():
    """All US water monitoring sites. Built once from USGS, cached to disk."""
    return await get_water_overlay_all()

