"""
Pydantic models for API responses.
These models provide structured, typed responses that clients can easily consume.
"""
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


# ──────────────────────────────────────────────────────────────────────────────
# Base Models
# ──────────────────────────────────────────────────────────────────────────────

class Coordinates(BaseModel):
    """Geographic coordinates."""
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")


class BoundingBox(BaseModel):
    """Geographic bounding box."""
    minx: float
    miny: float
    maxx: float
    maxy: float


class APIResponse(BaseModel):
    """Base response model for all API endpoints."""
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str
    success: bool = True
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Geocoding Models
# ──────────────────────────────────────────────────────────────────────────────

class GeocodingResult(APIResponse):
    """Geocoding API response."""
    city: str
    display_name: Optional[str] = None
    coordinates: Coordinates
    source: str = "OpenStreetMap Nominatim"


# ──────────────────────────────────────────────────────────────────────────────
# Electricity & Energy Models
# ──────────────────────────────────────────────────────────────────────────────

class ElectricityPriceData(BaseModel):
    """EIA electricity price data point."""
    period: str
    state_id: str
    state_name: str
    sector: str
    price: float = Field(..., description="Price in cents per kWh")
    sales: Optional[float] = Field(None, description="Sales in million kWh")
    revenue: Optional[float] = Field(None, description="Revenue in million dollars")


class GeneratorData(BaseModel):
    """EIA generator capacity data point."""
    period: str
    state_id: str
    state_name: Optional[str] = None
    plant_id: Optional[str] = None
    plant_name: Optional[str] = None
    generator_id: Optional[str] = None
    technology: Optional[str] = None
    energy_source: Optional[str] = None
    prime_mover: Optional[str] = None
    nameplate_capacity_mw: float = Field(..., description="Nameplate capacity in MW")
    operating_year: Optional[int] = None
    retirement_year: Optional[int] = None
    status: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = Field(None, description="Distance from query point in km")
    distance_miles: Optional[float] = Field(None, description="Distance from query point in miles")


class ElectricityPriceResponse(APIResponse):
    """Electricity price API response."""
    city: str
    state: str
    latest_price: Optional[ElectricityPriceData] = None
    historical_data: List[ElectricityPriceData] = []
    source: str = "EIA_API"
    units: str = "cents/kWh"


class UtilityRate(BaseModel):
    """Individual utility rate structure."""
    utility_name: str
    rate_name: str
    sector: str
    description: Optional[str] = None
    fixed_charge: Optional[float] = Field(None, description="Fixed monthly charge in dollars")
    demand_charge: Optional[float] = Field(None, description="Demand charge in $/kW")
    energy_charge: Optional[float] = Field(None, description="Energy charge in $/kWh")
    minimum_charge: Optional[float] = None
    effective_date: Optional[str] = None
    end_date: Optional[str] = None
    approved: bool = True
    uri: Optional[str] = None


class UtilityRatesResponse(APIResponse):
    """Utility rates API response."""
    coordinates: Coordinates
    rates: List[UtilityRate] = []
    count: int = 0
    radius_searched: float = Field(10.0, description="Search radius in miles")
    source: str = "OpenEI_API"


class GeneratorCapacityResponse(APIResponse):
    """Generator capacity API response."""
    coordinates: Coordinates
    state: str
    radius_miles: float = 100
    generators: List[GeneratorData] = []
    total_capacity_mw: float = 0
    count: int = 0
    source: str = "EIA_API"
    units: str = "MW"


class TransmissionLine(BaseModel):
    """Transmission line feature."""
    line_id: Optional[str] = None
    voltage_kv: Optional[float] = None
    owner: Optional[str] = None
    status: Optional[str] = None
    distance_km: float
    geometry: Optional[Dict[str, Any]] = None  # GeoJSON geometry
    properties: Dict[str, Any] = {}


class TransmissionLinesResponse(APIResponse):
    """Transmission lines API response."""
    coordinates: Coordinates
    radius_km: float
    lines: List[TransmissionLine] = []
    count: int = 0
    source: str = "Transmission_API"


# ──────────────────────────────────────────────────────────────────────────────
# Weather & Climate Models
# ──────────────────────────────────────────────────────────────────────────────

class WeatherStation(BaseModel):
    """Weather station information."""
    station_id: str
    name: str
    latitude: float
    longitude: float
    elevation: Optional[float] = None
    distance_km: Optional[float] = None
    data_coverage: Optional[float] = Field(None, ge=0, le=1)


class WeatherAlert(BaseModel):
    """Active weather alert."""
    id: str
    event: str
    severity: str
    urgency: str
    certainty: str
    headline: str
    description: Optional[str] = None
    onset: Optional[datetime] = None
    expires: Optional[datetime] = None


class HistoricalWeatherData(BaseModel):
    """Historical weather data point."""
    date: str
    temp_max: Optional[float] = Field(None, description="Maximum temperature in °F")
    temp_min: Optional[float] = Field(None, description="Minimum temperature in °F")
    precipitation: Optional[float] = Field(None, description="Precipitation in inches")
    snow: Optional[float] = Field(None, description="Snowfall in inches")
    wind_speed: Optional[float] = Field(None, description="Average wind speed in mph")


class ClimateDataResponse(APIResponse):
    """Climate data API response."""
    coordinates: Coordinates
    current_conditions: Optional[Dict[str, Any]] = None
    active_alerts: List[WeatherAlert] = []
    nearest_station: Optional[WeatherStation] = None
    historical_summary: Dict[str, Any] = {}
    historical_data: List[HistoricalWeatherData] = []
    years_of_data: int = 5
    source: str = "NOAA_APIs"


# ──────────────────────────────────────────────────────────────────────────────
# Water Resources Models
# ──────────────────────────────────────────────────────────────────────────────

class WaterSiteType(str, Enum):
    """Types of water monitoring sites."""
    SURFACE = "surface_water"
    GROUNDWATER = "groundwater"
    SPRING = "spring"
    RESERVOIR = "reservoir"


class WaterMonitoringSite(BaseModel):
    """Water monitoring site."""
    site_id: str
    site_name: str
    site_type: WaterSiteType
    coordinates: Coordinates
    distance_km: Optional[float] = None
    agency: str = "USGS"
    active: bool = True
    parameters_monitored: List[str] = []
    drainage_area_sq_mi: Optional[float] = None
    well_depth_ft: Optional[float] = None


class WaterResourcesResponse(APIResponse):
    """Water resources API response."""
    coordinates: Coordinates
    radius_miles: float = 25
    surface_water_sites: List[WaterMonitoringSite] = []
    groundwater_sites: List[WaterMonitoringSite] = []
    total_sites: int = 0
    source: str = "USGS_APIs"


# ──────────────────────────────────────────────────────────────────────────────
# Wind Energy Models
# ──────────────────────────────────────────────────────────────────────────────

class WindTurbine(BaseModel):
    """Wind turbine information."""
    project_name: Optional[str] = None
    project_year: Optional[int] = None
    turbine_capacity_kw: Optional[float] = None
    hub_height_m: Optional[float] = None
    rotor_diameter_m: Optional[float] = None
    total_height_m: Optional[float] = None
    coordinates: Coordinates
    offshore: bool = False
    confidence_level: Optional[int] = Field(None, ge=1, le=3)
    distance_km: Optional[float] = None


class WindTurbinesResponse(APIResponse):
    """Wind turbines API response."""
    location: Union[str, Coordinates]  # Can be state name or coordinates
    turbines: List[WindTurbine] = []
    count: int = 0
    total_capacity_mw: float = 0
    search_radius_km: Optional[float] = None
    source: str = "USGS_Wind_API"


# ──────────────────────────────────────────────────────────────────────────────
# Broadband & Connectivity Models
# ──────────────────────────────────────────────────────────────────────────────

class BroadbandProvider(BaseModel):
    """Broadband provider information."""
    provider_id: Optional[str] = None
    provider_name: str
    technology: str
    max_download_speed_mbps: float
    max_upload_speed_mbps: float
    low_latency: Optional[bool] = None
    business_service: Optional[bool] = None
    consumer_service: Optional[bool] = None


class CensusBlock(BaseModel):
    """Census block with broadband data."""
    block_geoid: str
    distance_km: float
    providers: List[BroadbandProvider] = []
    max_download_available: Optional[float] = None
    max_upload_available: Optional[float] = None
    fiber_available: bool = False
    business_fiber_available: bool = False


class BroadbandResponse(APIResponse):
    """Broadband connectivity API response."""
    coordinates: Coordinates
    radius_km: float
    census_blocks: List[CensusBlock] = []
    unique_providers: List[str] = []
    fiber_providers: List[str] = []
    max_speeds: Dict[str, float] = {}
    blocks_searched: int = 0
    blocks_with_service: int = 0
    source: str = "Broadband_API"


# ──────────────────────────────────────────────────────────────────────────────
# Transportation & Logistics Models
# ──────────────────────────────────────────────────────────────────────────────

class TransportationType(str, Enum):
    """Types of transportation infrastructure."""
    HIGHWAY = "highway"
    RAILWAY = "railway"
    AIRPORT = "airport"
    PORT = "port"
    JUNCTION = "junction"


class TransportationFeature(BaseModel):
    """Transportation infrastructure feature."""
    osm_id: Optional[str] = None
    feature_type: TransportationType
    name: Optional[str] = None
    ref: Optional[str] = Field(None, description="Reference number (e.g., I-80)")
    classification: Optional[str] = Field(None, description="e.g., motorway, trunk, primary")
    distance_km: Optional[float] = None
    geometry: Optional[Dict[str, Any]] = None  # GeoJSON geometry
    tags: Dict[str, Any] = {}


class TransportationResponse(APIResponse):
    """Transportation logistics API response."""
    coordinates: Coordinates
    search_radius_km: float
    highways: List[TransportationFeature] = []
    railways: List[TransportationFeature] = []
    airports: List[TransportationFeature] = []
    ports: List[TransportationFeature] = []
    highway_junctions: List[TransportationFeature] = []
    rail_stations: List[TransportationFeature] = []
    total_features: int = 0
    source: str = "Overpass_API"


class HighwayAccessResponse(APIResponse):
    """Highway access API response."""
    coordinates: Coordinates
    search_radius_km: float = 50
    motorways: List[TransportationFeature] = []
    trunk_roads: List[TransportationFeature] = []
    junctions: List[TransportationFeature] = []
    nearest_highway_km: Optional[float] = None
    nearest_junction_km: Optional[float] = None
    total_features: int = 0
    source: str = "Overpass_API"


class RailConnectivityResponse(APIResponse):
    """Rail connectivity API response."""
    coordinates: Coordinates
    search_radius_km: float = 100
    rail_lines: List[TransportationFeature] = []
    stations: List[TransportationFeature] = []
    nearest_rail_km: Optional[float] = None
    nearest_station_km: Optional[float] = None
    freight_capable: Optional[bool] = None
    total_features: int = 0
    source: str = "Overpass_API"


# ──────────────────────────────────────────────────────────────────────────────
# Aggregated Response Models
# ──────────────────────────────────────────────────────────────────────────────

class DatacenterSiteAssessment(BaseModel):
    """Complete datacenter site assessment combining all data sources."""
    location: Coordinates
    city: Optional[str] = None
    assessment_date: datetime = Field(default_factory=datetime.now)
    
    # Infrastructure scores (0-100)
    electricity_score: Optional[float] = None
    broadband_score: Optional[float] = None
    transportation_score: Optional[float] = None
    water_score: Optional[float] = None
    climate_score: Optional[float] = None
    renewable_energy_score: Optional[float] = None
    
    # Detailed data
    electricity_data: Optional[Union[ElectricityPriceResponse, UtilityRatesResponse]] = None
    transmission_data: Optional[TransmissionLinesResponse] = None
    broadband_data: Optional[BroadbandResponse] = None
    transportation_data: Optional[TransportationResponse] = None
    water_data: Optional[WaterResourcesResponse] = None
    climate_data: Optional[ClimateDataResponse] = None
    wind_data: Optional[WindTurbinesResponse] = None
    
    # Overall assessment
    overall_score: Optional[float] = None
    strengths: List[str] = []
    weaknesses: List[str] = []
    recommendations: List[str] = []
