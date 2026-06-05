"""
Electricity and energy API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from models import ElectricityPriceResponse, UtilityRatesResponse, GeneratorCapacityResponse
from services.data_fetchers import get_electricity_price_raw, get_utility_rates_raw, get_generator_capacity_raw
from transformers import transform_electricity_price, transform_utility_rates, transform_generator_capacity

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class CityRequest(BaseModel):
    city: str


class CoordinatesRequest(BaseModel):
    lat: float
    lon: float
    state: Optional[str] = None  # Optional 2-letter state code (e.g., "TX", "VA")

class GeneratorCapacityRequest(CoordinatesRequest):
    radius_miles: int = 5


@router.post("/api/electricity-price", response_model=ElectricityPriceResponse)
async def electricity_price_endpoint(request: CityRequest) -> ElectricityPriceResponse:
    """Get electricity price data from EIA API."""
    try:
        raw_data = await get_electricity_price_raw(request.city)
        return transform_electricity_price(request.city, raw_data)
    except Exception as e:
        logger.exception(f"Electricity price API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/utility-rates", response_model=UtilityRatesResponse)
async def utility_rates_endpoint(request: CoordinatesRequest) -> UtilityRatesResponse:
    """Get utility rates from OpenEI API."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_utility_rates_raw(coordinates)
        return transform_utility_rates(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Utility rates API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/generator-capacity", response_model=GeneratorCapacityResponse)
async def generator_capacity_endpoint(request: GeneratorCapacityRequest) -> GeneratorCapacityResponse:
    """Get operating generator capacity near coordinates from EIA API."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon, "state": request.state}
        raw_data = await get_generator_capacity_raw(coordinates, request.radius_miles)
        # Extract state_id from query metadata (set by get_generator_capacity_raw)
        state_id = raw_data.get('query', {}).get('state', '')
        # Fallback: try to get from first generator if available
        if not state_id:
            data = raw_data.get('response', {}).get('data', [])
            if data:
                state_id = data[0].get('stateid', '')
        return transform_generator_capacity(coordinates, state_id, raw_data)
    except Exception as e:
        logger.exception(f"Generator capacity API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

