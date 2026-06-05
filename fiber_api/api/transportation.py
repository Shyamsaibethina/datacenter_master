"""
Transportation and logistics API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import TransportationResponse, HighwayAccessResponse, RailConnectivityResponse
from services.data_fetchers import get_transportation_data_raw, get_highway_data_raw, get_rail_data_raw
from transformers import transform_transportation_data, transform_highway_access, transform_rail_connectivity

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float


@router.post("/api/transportation-logistics", response_model=TransportationResponse)
async def transportation_logistics_endpoint(request: CoordinatesRequest) -> TransportationResponse:
    """Get comprehensive transportation data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_transportation_data_raw(coordinates)
        return transform_transportation_data(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Transportation logistics API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/highway-access", response_model=HighwayAccessResponse)
async def highway_access_endpoint(request: CoordinatesRequest) -> HighwayAccessResponse:
    """Get highway access data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_highway_data_raw(coordinates)
        return transform_highway_access(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Highway access API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/rail-connectivity", response_model=RailConnectivityResponse)
async def rail_connectivity_endpoint(request: CoordinatesRequest) -> RailConnectivityResponse:
    """Get rail connectivity data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_rail_data_raw(coordinates)
        return transform_rail_connectivity(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Rail connectivity API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

