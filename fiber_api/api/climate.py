"""
Climate and weather API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import ClimateDataResponse
from services.data_fetchers import get_weather_data_raw
from transformers import transform_climate_data

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float


@router.post("/api/datacenter-climate", response_model=ClimateDataResponse)
async def datacenter_climate_endpoint(request: CoordinatesRequest) -> ClimateDataResponse:
    """Get comprehensive weather data from multiple NOAA APIs."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_weather_data_raw(coordinates)
        return transform_climate_data(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Datacenter climate API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

