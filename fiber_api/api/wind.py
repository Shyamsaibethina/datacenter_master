"""
Wind energy API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import WindTurbinesResponse
from services.data_fetchers import get_wind_turbines_raw, get_wind_turbines_near_raw
from transformers import transform_wind_turbines_state, transform_wind_turbines_location

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class CityRequest(BaseModel):
    city: str


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float


@router.post("/api/wind-turbines-by-state", response_model=WindTurbinesResponse)
async def wind_turbines_by_state_endpoint(request: CityRequest) -> WindTurbinesResponse:
    """Get wind turbines by state from USGS API."""
    try:
        raw_data = await get_wind_turbines_raw(request.city)
        return transform_wind_turbines_state(request.city, raw_data)
    except Exception as e:
        logger.exception(f"Wind turbines by state API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/wind-turbines-near-location", response_model=WindTurbinesResponse)
async def wind_turbines_near_location_endpoint(request: CoordinatesRequest) -> WindTurbinesResponse:
    """Get wind turbines near location from USGS API."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_wind_turbines_near_raw(coordinates)
        return transform_wind_turbines_location(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Wind turbines near location API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

