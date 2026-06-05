"""
Broadband connectivity API endpoints.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from models import BroadbandResponse
from services.data_fetchers import get_broadband_data_raw
from transformers import transform_broadband_data
from database import get_broadband_core

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float


@router.get("/broadband/at_point")
def broadband_at_point(
    lon: float = Query(..., description="Longitude (WGS84)"),
    lat: float = Query(..., description="Latitude (WGS84)"),
    radius_km: float = Query(0.5, ge=0.1, le=50, description="Search radius in kilometers"),
    min_download: Optional[float] = Query(None, description="Minimum download speed in Mbps"),
    min_upload: Optional[float] = Query(None, description="Minimum upload speed in Mbps"),
    limit: int = Query(100, ge=1, le=1000, description="Max results to return")
):
    """
    Find broadband availability at a given point.
    Uses a two-phase approach: bbox filtering and exact spatial check.
    """
    return get_broadband_core(
        lon=lon, lat=lat, radius_km=radius_km, 
        min_download=min_download, min_upload=min_upload, limit=limit
    )


@router.post("/api/broadband-connectivity", response_model=BroadbandResponse)
async def broadband_connectivity_endpoint(request: CoordinatesRequest) -> BroadbandResponse:
    """Get broadband connectivity data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_broadband_data_raw(coordinates)
        return transform_broadband_data(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Broadband connectivity API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

