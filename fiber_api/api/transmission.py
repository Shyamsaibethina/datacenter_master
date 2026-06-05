"""
Transmission lines API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from models import TransmissionLinesResponse
from services.data_fetchers import get_transmission_lines_raw
from services.overlay_cache import get_transmission_overlay_all
from transformers import transform_transmission_lines
from database import get_transmission_lines_core

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float


@router.get("/transmission/at_point")
def transmission_at_point(
    lon: float = Query(..., description="Longitude (WGS84)"),
    lat: float = Query(..., description="Latitude (WGS84)"),
    radius_km: float = Query(5.0, ge=0.1, le=100, description="Search radius in kilometers"),
    limit: int = Query(100, ge=1, le=1000, description="Max results to return")
):
    """
    Find transmission lines at a given point.
    Uses bbox pre-filtering for fast queries.
    """
    return get_transmission_lines_core(lon=lon, lat=lat, radius_km=radius_km, limit=limit)


@router.get("/transmission/all")
def transmission_all():
    """All US transmission lines (simplified). Built once, cached to disk."""
    return get_transmission_overlay_all()


@router.post("/api/transmission-lines", response_model=TransmissionLinesResponse)
async def transmission_lines_endpoint(request: CoordinatesRequest) -> TransmissionLinesResponse:
    """Get transmission lines data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_transmission_lines_raw(coordinates)
        return transform_transmission_lines(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Transmission lines API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

