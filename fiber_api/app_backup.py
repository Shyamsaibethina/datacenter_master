import os
import logging
import json
import math
import httpx
import asyncio
import numpy as np
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from pydantic import BaseModel


from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import duckdb

# Import models and transformers
from models import (
    GeocodingResult,
    ElectricityPriceResponse,
    UtilityRatesResponse,
    TransmissionLinesResponse,
    ClimateDataResponse,
    WaterResourcesResponse,
    WindTurbinesResponse,
    BroadbandResponse,
    TransportationResponse,
    HighwayAccessResponse,
    RailConnectivityResponse,
    Coordinates
)
from transformers import (
    transform_electricity_price,
    transform_utility_rates,
    transform_transmission_lines,
    transform_climate_data,
    transform_water_resources,
    transform_wind_turbines_state,
    transform_wind_turbines_location,
    transform_broadband_data,
    transform_transportation_data,
    transform_highway_access,
    transform_rail_connectivity
)

logger = logging.getLogger("uvicorn.error")

# ──────────────────────────────────────────────────────────────────────────────
# Environment Configuration
# ──────────────────────────────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
S3_BLOCKS_GEO = os.environ.get("S3_BLOCKS_GEO", "s3://broadbandinfo/fiber/census_blocks/*.parquet")
S3_BLOCKS_GLOB = os.environ.get("S3_BLOCKS_GLOB", "s3://broadbandinfo/fiber/blocks/*.parquet")

# Extract bucket and prefix for state-based queries
S3_GEO_BUCKET = S3_BLOCKS_GEO.replace("s3://", "").split("/")[0]
S3_GEO_PREFIX = "/".join(S3_BLOCKS_GEO.replace("s3://", "").split("/")[1:]).replace("*.parquet", "")

S3_BROADBAND_BUCKET = S3_BLOCKS_GLOB.replace("s3://", "").split("/")[0]
S3_BROADBAND_PREFIX = "/".join(S3_BLOCKS_GLOB.replace("s3://", "").split("/")[1:]).replace("*.parquet", "")

# State bounding boxes for fast state lookup (no scan needed)
STATE_BOUNDS = {
    "AL": (-88.5, 30.2, -84.9, 35.0), "AK": (-179.1, 51.2, -129.9, 71.4),
    "AZ": (-114.8, 31.3, -109.0, 37.0), "AR": (-94.6, 33.0, -89.6, 36.5),
    "CA": (-124.4, 32.5, -114.1, 42.0), "CO": (-109.1, 37.0, -102.0, 41.0),
    "CT": (-73.7, 40.9, -71.8, 42.1), "DE": (-75.8, 38.4, -75.0, 39.8),
    "DC": (-77.1, 38.8, -76.9, 39.0), "FL": (-87.6, 24.5, -80.0, 31.0),
    "GA": (-85.6, 30.4, -80.8, 35.0), "HI": (-160.2, 18.9, -154.8, 22.2),
    "ID": (-117.2, 42.0, -111.0, 49.0), "IL": (-91.5, 37.0, -87.0, 42.5),
    "IN": (-88.1, 37.8, -84.8, 41.8), "IA": (-96.6, 40.4, -90.1, 43.5),
    "KS": (-102.1, 37.0, -94.6, 40.0), "KY": (-89.6, 36.5, -81.9, 39.1),
    "LA": (-94.0, 28.9, -88.8, 33.0), "ME": (-71.1, 43.0, -66.9, 47.5),
    "MD": (-79.5, 37.9, -75.0, 39.7), "MA": (-73.5, 41.2, -69.9, 42.9),
    "MI": (-87.5, 41.7, -82.4, 48.2), "MN": (-97.2, 43.5, -89.5, 49.4),
    "MS": (-91.7, 30.2, -88.1, 35.0), "MO": (-95.8, 36.0, -89.1, 40.6),
    "MT": (-116.1, 44.4, -104.0, 49.0), "NE": (-104.1, 40.0, -95.3, 43.0),
    "NV": (-120.0, 35.0, -114.0, 42.0), "NH": (-72.6, 42.7, -70.6, 45.3),
    "NJ": (-75.6, 38.9, -73.9, 41.4), "NM": (-109.1, 31.3, -103.0, 37.0),
    "NY": (-79.8, 40.3, -71.8, 45.0), "NC": (-84.3, 33.8, -75.4, 36.6),
    "ND": (-104.1, 45.9, -96.6, 49.0), "OH": (-84.8, 38.4, -80.5, 42.0),
    "OK": (-103.0, 33.6, -94.4, 37.0), "OR": (-124.6, 41.9, -116.5, 46.3),
    "PA": (-80.5, 39.7, -74.7, 42.3), "RI": (-71.9, 41.1, -71.1, 42.0),
    "SC": (-83.4, 32.0, -78.5, 35.2), "SD": (-104.1, 42.5, -96.4, 45.9),
    "TN": (-90.3, 35.0, -81.6, 36.7), "TX": (-106.6, 25.8, -93.5, 36.5),
    "UT": (-114.1, 37.0, -109.0, 42.0), "VT": (-73.4, 42.7, -71.5, 45.0),
    "VA": (-83.7, 36.5, -75.2, 39.5), "WA": (-124.8, 45.5, -116.9, 49.0),
    "WV": (-82.6, 37.2, -77.7, 40.6), "WI": (-92.9, 42.5, -86.2, 47.3),
    "WY": (-111.1, 41.0, -104.1, 45.0),
}

# Global DuckDB connection
con = None

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic Models for API Requests
# ──────────────────────────────────────────────────────────────────────────────

class GeocodeRequest(BaseModel):
    city: str

def get_candidate_states(lon: float, lat: float, buffer_deg: float = 0.5) -> List[str]:
    """Get list of states that could contain the point (with buffer for radius)."""
    candidates = []
    for state, (minx, miny, maxx, maxy) in STATE_BOUNDS.items():
        if (minx - buffer_deg <= lon <= maxx + buffer_deg and 
            miny - buffer_deg <= lat <= maxy + buffer_deg):
            # Calculate how "centered" the point is within the bbox
            # Points closer to edges get higher scores (worse)
            # Use minimum distance to any edge
            dist_to_west = abs(lon - minx)
            dist_to_east = abs(lon - maxx)
            dist_to_south = abs(lat - miny)
            dist_to_north = abs(lat - maxy)
            min_edge_distance = min(dist_to_west, dist_to_east, dist_to_south, dist_to_north)
            # Prefer states where point is furthest from edges (more centered)
            score = -min_edge_distance  # Negative so we can sort ascending (best first)
            candidates.append((state, score))
    # Sort by score (most negative = furthest from edges = most centered)
    candidates.sort(key=lambda x: x[1])
    return [state for state, _ in candidates]

# ──────────────────────────────────────────────────────────────────────────────
# DuckDB Initialization
# ──────────────────────────────────────────────────────────────────────────────
def _init_duckdb():
    """Initialize DuckDB with S3 and spatial extensions."""
    import boto3
    
    c = duckdb.connect(database=":memory:")
    
    # Install and load extensions
    for ext in ["httpfs", "spatial"]:
        try:
            c.execute(f"INSTALL {ext};")
        except Exception as e:
            logger.debug(f"Extension {ext} already installed or failed: {e}")
        try:
            c.execute(f"LOAD {ext};")
            logger.info(f"✓ Loaded {ext} extension")
        except Exception as e:
            logger.error(f"✗ Failed to load {ext}: {e}")
            raise
    
    # Configure S3 access using boto3 credentials (works with IAM roles)
    c.execute("SET s3_region = ?", [AWS_REGION])
    
    try:
        sess = boto3.Session()
        creds = sess.get_credentials()
        if creds:
            frozen = creds.get_frozen_credentials()
            c.execute("SET s3_access_key_id = ?", [frozen.access_key])
            c.execute("SET s3_secret_access_key = ?", [frozen.secret_key])
            if getattr(frozen, "token", None):
                c.execute("SET s3_session_token = ?", [frozen.token])
            c.execute("SET s3_url_style = 'path';")
            logger.info("✓ Injected AWS credentials into DuckDB")
    except Exception as e:
        logger.warning(f"Failed to inject AWS creds: {e}")
    
    # Test spatial extension
    try:
        c.execute("SELECT ST_AsText(ST_Point(0,0))").fetchone()
        logger.info("✓ Spatial functions working")
    except Exception as e:
        logger.error(f"✗ Spatial functions not available: {e}")
        raise
    
    return c

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI App Setup
# ──────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global con
    try:
        con = _init_duckdb()
        logger.info("✓ DuckDB initialized successfully")
        yield
    except Exception as e:
        logger.exception("Startup failed during DuckDB initialization")
        raise
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

app = FastAPI(
    title="Broadband Geo API",
    version="1.0",
    description="Query broadband data by geographic point using DuckDB"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.router.lifespan_context = lifespan

# ──────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    """Health check endpoint."""
    if con is None:
        return {"ok": False, "error": "Database not initialized"}
    
    try:
        # Test that we can query S3
        con.execute(f"SELECT 1 FROM read_parquet('{S3_BLOCKS_GEO}') LIMIT 1").fetchone()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/broadband/at_point")
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
    
    Uses a two-phase approach:
    1. Use bounding boxes to quickly filter candidate census blocks
    2. Perform exact spatial check on candidates
    3. Join with broadband data
    
    This avoids loading full geometries for blocks that can't possibly contain the point.
    """
    return _get_broadband_core(lon=lon, lat=lat, radius_km=radius_km, min_download=min_download, min_upload=min_upload, limit=limit)


@app.get("/transmission/at_point")
def transmission_at_point(
    lon: float = Query(..., description="Longitude (WGS84)"),
    lat: float = Query(..., description="Latitude (WGS84)"),
    radius_km: float = Query(5.0, ge=0.1, le=100, description="Search radius in kilometers"),
    limit: int = Query(100, ge=1, le=1000, description="Max results to return")
):
    """
    Find transmission lines at a given point.
    
    Queries the resilience_power.parquet file from S3 and returns transmission
    lines within the specified radius of the given coordinate.
    
    Uses bbox pre-filtering for fast queries.
    """
    return _get_transmission_lines_core(lon=lon, lat=lat, radius_km=radius_km, limit=limit)

@app.get("/debug/s3-access")
async def debug_s3():
    try:
        import boto3
        s3 = boto3.client('s3')
        response = s3.head_object(Bucket='broadbandinfo', Key='fiber/census_blocks/FL.parquet')
        return {"status": "success", "metadata": response}
    except Exception as e:
        return {"status": "error", "error": str(e)}



@app.get("/debug/geo_sample")
def debug_geo_sample(limit: int = Query(5, ge=1, le=100)):
    """Debug endpoint to check what's in the geo parquet files."""
    global con
    
    if con is None:
        raise HTTPException(503, "Database not initialized")
    
    try:
        # Check what columns exist
        col_sql = f"SELECT * FROM read_parquet('{S3_BLOCKS_GEO}', union_by_name=true) LIMIT 0"
        con.execute(col_sql)
        columns = [desc[0] for desc in con.description]
        
        # Get sample data
        sample_sql = f"""
        SELECT block_geoid, minx, miny, maxx, maxy
        FROM read_parquet('{S3_BLOCKS_GEO}', union_by_name=true)
        LIMIT {int(limit)}
        """
        results = con.execute(sample_sql).fetchall()
        
        # Get count
        count_sql = f"SELECT COUNT(*) FROM read_parquet('{S3_BLOCKS_GEO}', union_by_name=true)"
        total = con.execute(count_sql).fetchone()[0]
        
        return {
            "s3_path": S3_BLOCKS_GEO,
            "columns": columns,
            "total_rows": total,
            "sample": [
                {
                    "block_geoid": row[0],
                    "minx": row[1],
                    "miny": row[2],
                    "maxx": row[3],
                    "maxy": row[4]
                }
                for row in results
            ]
        }
    except Exception as e:
        logger.exception(f"Error in debug_geo_sample: {e}")
        return {
            "error": str(e),
            "s3_path": S3_BLOCKS_GEO
        }


@app.get("/debug/broadband_sample")
def debug_broadband_sample(limit: int = Query(5, ge=1, le=100)):
    """Debug endpoint to check what's in the broadband parquet files."""
    global con
    
    if con is None:
        raise HTTPException(503, "Database not initialized")
    
    try:
        # Check what columns exist
        col_sql = f"SELECT * FROM read_parquet('{S3_BLOCKS_GLOB}', union_by_name=true) LIMIT 0"
        con.execute(col_sql)
        columns = [desc[0] for desc in con.description]
        
        # Get sample data
        sample_sql = f"""
        SELECT *
        FROM read_parquet('{S3_BLOCKS_GLOB}', union_by_name=true)
        LIMIT {int(limit)}
        """
        results = con.execute(sample_sql).fetchall()
        
        # Get count
        count_sql = f"SELECT COUNT(*) FROM read_parquet('{S3_BLOCKS_GLOB}', union_by_name=true)"
        total = con.execute(count_sql).fetchone()[0]
        
        return {
            "s3_path": S3_BLOCKS_GLOB,
            "columns": columns,
            "total_rows": total,
            "sample": [dict(zip(columns, row)) for row in results]
        }
    except Exception as e:
        logger.exception(f"Error in debug_broadband_sample: {e}")
        return {
            "error": str(e),
            "s3_path": S3_BLOCKS_GLOB
        }


@app.get("/debug/bbox_check")
def debug_bbox_check(
    lon: float = Query(..., description="Longitude"),
    lat: float = Query(..., description="Latitude"),
    radius_km: float = Query(1.0, description="Radius in km")
):
    """Debug endpoint to check bbox filtering."""
    global con
    
    if con is None:
        raise HTTPException(503, "Database not initialized")
    
    try:
        deg_buffer = radius_km / 111.0
        
        # Check how many blocks are near this point
        debug_sql = f"""
        SELECT 
            block_geoid,
            minx, miny, maxx, maxy,
            CASE 
                WHEN ? BETWEEN minx AND maxx THEN 'lon_inside'
                ELSE 'lon_outside'
            END as lon_status,
            CASE
                WHEN ? BETWEEN miny AND maxy THEN 'lat_inside'
                ELSE 'lat_outside'
            END as lat_status
        FROM read_parquet('{S3_BLOCKS_GEO}', union_by_name=true)
        WHERE minx BETWEEN ? - 0.1 AND ? + 0.1
          OR maxx BETWEEN ? - 0.1 AND ? + 0.1
          OR miny BETWEEN ? - 0.1 AND ? + 0.1
          OR maxy BETWEEN ? - 0.1 AND ? + 0.1
        LIMIT 10
        """
        
        results = con.execute(
            debug_sql,
            [lon, lat, lon, lon, lon, lon, lat, lat, lat, lat]
        ).fetchall()
        
        return {
            "query_point": {"lon": lon, "lat": lat},
            "radius_km": radius_km,
            "deg_buffer": deg_buffer,
            "search_box": {
                "minx": lon - deg_buffer,
                "maxx": lon + deg_buffer,
                "miny": lat - deg_buffer,
                "maxy": lat + deg_buffer
            },
            "nearby_blocks": [
                {
                    "block_geoid": row[0],
                    "minx": row[1],
                    "miny": row[2],
                    "maxx": row[3],
                    "maxy": row[4],
                    "lon_status": row[5],
                    "lat_status": row[6]
                }
                for row in results
            ]
        }
    except Exception as e:
        logger.exception(f"Error in debug_bbox_check: {e}")
        return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# Geocoding API Endpoint (from Next.js /api/geocode)
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/geocode", response_model=GeocodingResult)
async def geocode_endpoint(request: GeocodeRequest) -> GeocodingResult:
    """
    Geocoding endpoint using OpenStreetMap Nominatim.
    Returns a structured GeocodingResult model.
    """
    try:
        city = request.city
        
        if not city or not isinstance(city, str):
            raise HTTPException(status_code=400, detail="City name is required")
        
        # Use OpenStreetMap Nominatim for geocoding (free, no API key required)
        from urllib.parse import quote
        encoded_city = quote(city.strip())
        geocode_url = f"https://nominatim.openstreetmap.org/search?format=json&q={encoded_city}&limit=1&countrycodes=us"

        logger.info(f"Geocoding URL: {geocode_url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    geocode_url,
                    headers={
                        'User-Agent': 'DatacenterPlanningApp/1.0 (contact@datacenterplanning.com)'
                    }
                )
                logger.info(f"Geocode response status: {response.status_code}")
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Geocoding service timed out")
            except httpx.RequestError as e:
                raise HTTPException(status_code=503, detail=f"Geocoding service error: {str(e)}")
        
        if not response.is_success:
            raise HTTPException(status_code=response.status_code, detail=f"Geocoding service returned {response.status_code}: {response.text[:200]}")
        
        try:
            data = response.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse geocoding response: {str(e)}")
        
        if not data or len(data) == 0:
            raise HTTPException(
                status_code=404, 
                detail=f'Could not find coordinates for "{city}". Please try a more specific location (e.g., "San Francisco, CA")'
            )
        
        result = data[0]
        latitude = float(result['lat'])
        longitude = float(result['lon'])
        
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            raise HTTPException(status_code=500, detail="Invalid coordinates received from geocoding service")
        
        return GeocodingResult(
            city=city,
            display_name=result.get('display_name', city),
            coordinates=Coordinates(lat=latitude, lon=longitude),
            source="OpenStreetMap Nominatim"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Geocoding error: {e}")
        raise HTTPException(status_code=500, detail="Failed to geocode city. Please try again.")


# ──────────────────────────────────────────────────────────────────────────────
# API Configuration and Constants (from Next.js server)
# ──────────────────────────────────────────────────────────────────────────────

# API Keys and Configuration
API_CONFIG = {
    "USER_AGENT": "DatacenterMCP/1.0 (contact@datacenter-planning.com)",
    "EIA_API_KEY": "B2BcRsfRYupoKyjyMrGiN62clJsKumSuB1R5uKCY",
    "NOAA_CDO_TOKEN": "FqpipxmwolxLAMVeTEAkxREnKoVZuUpX",
    "USGS_API_KEY": "c1Sg9HqhwKgPKKaG6SsYJKTLGfdZ3YGGGz26wW8Y",
    "OPENEI_API_KEY": "FhosGzYJcpbsbFRH2O0KXY1dJq2vfAbsEGRp2PB3"
}

# State name to abbreviation mapping
STATE_ID_MAP = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA',
    'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA',
    'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
    'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO',
    'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
    'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH',
    'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT',
    'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
    'district of columbia': 'DC'
}

# State abbreviation to name mapping
STATE_ABBREV_MAP = {
    'AL': 'alabama', 'AK': 'alaska', 'AZ': 'arizona', 'AR': 'arkansas', 'CA': 'california',
    'CO': 'colorado', 'CT': 'connecticut', 'DE': 'delaware', 'FL': 'florida', 'GA': 'georgia',
    'HI': 'hawaii', 'ID': 'idaho', 'IL': 'illinois', 'IN': 'indiana', 'IA': 'iowa',
    'KS': 'kansas', 'KY': 'kentucky', 'LA': 'louisiana', 'ME': 'maine', 'MD': 'maryland',
    'MA': 'massachusetts', 'MI': 'michigan', 'MN': 'minnesota', 'MS': 'mississippi', 'MO': 'missouri',
    'MT': 'montana', 'NE': 'nebraska', 'NV': 'nevada', 'NH': 'new hampshire', 'NJ': 'new jersey',
    'NM': 'new mexico', 'NY': 'new york', 'NC': 'north carolina', 'ND': 'north dakota', 'OH': 'ohio',
    'OK': 'oklahoma', 'OR': 'oregon', 'PA': 'pennsylvania', 'RI': 'rhode island', 'SC': 'south carolina',
    'SD': 'south dakota', 'TN': 'tennessee', 'TX': 'texas', 'UT': 'utah', 'VT': 'vermont',
    'VA': 'virginia', 'WA': 'washington', 'WV': 'west virginia', 'WI': 'wisconsin', 'WY': 'wyoming',
    'DC': 'district of columbia'
}

# API Endpoints
ELECTRICITY_APIS = {
    "EIA_BASE": "https://api.eia.gov/v2",
    "OPENEI_BASE": "https://api.openei.org/utility_rates"
}

WEATHER_APIS = {
    "NWS_API_BASE": "https://api.weather.gov",
    "NOAA_CDO_BASE": "https://www.ncdc.noaa.gov/cdo-web/api/v2",
    "NOAA_ACCESS_BASE": "https://www.ncei.noaa.gov/access/services/data/v1"
}

WATER_APIS = {
    "USGS_OGC_BASE": "https://labs.waterdata.usgs.gov/api/nldi/linked-data/nwissite"
}

WIND_APIS = {
    "USGS_BASE": "https://eerscmap.usgs.gov/uswtdb/api/turbines"
}

# Broadband API configuration no longer needed - calling functions directly

TRANSPORTATION_APIS = {
    "OVERPASS_BASE": "https://overpass-api.de/api/interpreter"
}

# Utility functions
def normalize_us_lon(lon: float) -> float:
    """Normalize longitude for US coordinates (ensure negative for continental US)."""
    if lon > 0 and lon < 180:
        return -lon
    return lon

def create_bbox(lat: float, lon: float, radius_deg: float) -> str:
    """Create bbox string for API requests."""
    return f"{lon-radius_deg},{lat-radius_deg},{lon+radius_deg},{lat+radius_deg}"


# ──────────────────────────────────────────────────────────────────────────────
# Raw Data API Helper Functions (from Next.js server)
# ──────────────────────────────────────────────────────────────────────────────

async def get_electricity_price_raw(city: str) -> Dict[str, Any]:
    """Get electricity price data from EIA API."""
    # Extract state from city string (e.g., "San Francisco, CA" -> "california")
    state_part = city.split(',')[-1].strip() if ',' in city else None
    
    if not state_part:
        raise HTTPException(status_code=400, detail="City must include state (e.g., 'Austin, TX')")
    
    abbrev = state_part.upper()
    if abbrev not in STATE_ABBREV_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown state abbreviation: {abbrev}")
    
    state_name = STATE_ABBREV_MAP[abbrev]
    
    state_id = STATE_ID_MAP.get(state_name.lower())
    if not state_id:
        raise HTTPException(status_code=400, detail=f"Unknown state: {state_name}")
    
    # Calculate date range accounting for 2-month lag
    from datetime import datetime, timedelta
    now = datetime.now()
    three_months_ago = now - timedelta(days=90)
    start_date = three_months_ago.strftime('%Y-%m')
    end_date = start_date  # Same month for most recent available data
    
    url = f"{ELECTRICITY_APIS['EIA_BASE']}/electricity/retail-sales/data?api_key={API_CONFIG['EIA_API_KEY']}&data[]=price&facets[sectorid][]=IND&facets[stateid][]={state_id}&frequency=monthly&start={start_date}&end={end_date}&sort[0][column]=period&sort[0][direction]=desc&length=1"
    print(url)
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"EIA API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="EIA API request timed out. The service may be slow or unavailable.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"EIA API connection error: {str(e)}")


async def get_utility_rates_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get utility rates from OpenEI API."""
    lat, lon = coordinates['lat'], coordinates['lon']
    radius = 10
    sector = "Industrial"
    
    url = f"{ELECTRICITY_APIS['OPENEI_BASE']}?version=latest&format=json&api_key={API_CONFIG['OPENEI_API_KEY']}&lat={lat}&lon={lon}&radius={radius}&sector={sector}&approved=true&detail=full&limit=50"

    print(url)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"OpenEI API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="OpenEI API request timed out. The service may be slow or unavailable.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"OpenEI API connection error: {str(e)}")


def _get_transmission_lines_core(lon: float, lat: float, radius_km: float = 5.0, limit: int = 100) -> Dict[str, Any]:
    """Core transmission lines logic without FastAPI dependencies."""
    global con
    
    if con is None:
        raise HTTPException(503, "Database not initialized")
    
    # Validate coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise HTTPException(400, f"Invalid coordinates: lon={lon}, lat={lat}")
    
    logger.info(f"Transmission query: point=({lon}, {lat}), radius={radius_km}km")
    
    try:
        import time
        start_time = time.time()
        
        # Phase 0: Determine which state contains the point (instant, no S3 access)
        # Use 0 buffer and take only the first state (bounding boxes can overlap)
        all_candidates = get_candidate_states(lon, lat, buffer_deg=0.0)
        candidate_states = [all_candidates[0]] if all_candidates else []
        
        # Calculate degree buffer for spatial queries within the state
        radius_deg = radius_km / 111.0
        deg_buffer = radius_deg
        
        if not candidate_states:
            logger.warning(f"No candidate states for point ({lon}, {lat})")
            return {
                "type": "FeatureCollection",
                "query": {
                    "point": {"lon": lon, "lat": lat},
                    "radius_km": radius_km
                },
                "count": 0,
                "features": [],
                "message": "Point outside known US boundaries"
            }
        
        logger.info(f"Scanning states for transmission lines: {candidate_states}")
        
        # Get state bounding boxes for additional filtering
        state_bounds_filter = []
        for state in candidate_states:
            if state in STATE_BOUNDS:
                minx, miny, maxx, maxy = STATE_BOUNDS[state]
                state_bounds_filter.append(f"(minx <= {maxx} AND maxx >= {minx} AND miny <= {maxy} AND maxy >= {miny})")
        
        state_bounds_sql = " OR ".join(state_bounds_filter) if state_bounds_filter else "TRUE"
        
        # Phase 1: Fast bbox filter on Parquet (no geometry operations needed)
        # Only look at transmission lines within the candidate state(s)
        query_sql = f"""
        SELECT 
            * EXCLUDE (geom, minx, miny, maxx, maxy),
            ST_AsGeoJSON(geom) as geometry_json,
            ST_Distance(geom, ST_Point(?, ?)) * 111.0 as distance_km
        FROM read_parquet('s3://transmissioninfo/resilience_power.parquet')
        WHERE ({state_bounds_sql})
          AND minx <= ? + ? AND maxx >= ? - ?
          AND miny <= ? + ? AND maxy >= ? - ?
          AND ST_DWithin(geom, ST_Point(?, ?), ?)
        ORDER BY distance_km
        LIMIT ?
        """
        
        results_cursor = con.execute(
            query_sql,
            [
                lon, lat,  # For ST_Distance
                lon, deg_buffer, lon, deg_buffer,  # minx/maxx bbox
                lat, deg_buffer, lat, deg_buffer,  # miny/maxy bbox
                lon, lat, radius_deg,  # For ST_DWithin
                int(limit)
            ]
        )
        
        cols = [desc[0] for desc in results_cursor.description]
        rows = results_cursor.fetchall()
        
        # Format results as GeoJSON features
        features = []
        for row in rows:
            import json
            row_dict = dict(zip(cols, row))
            
            geometry_json = json.loads(row_dict.pop('geometry_json')) if row_dict.get('geometry_json') else None
            distance_km = round(row_dict.pop('distance_km'), 3)
            
            # Remaining columns are properties
            properties = row_dict
            properties['distance_km'] = distance_km
            
            features.append({
                "type": "Feature",
                "geometry": geometry_json,
                "properties": properties
            })
        
        total_time = time.time() - start_time
        logger.info(f"Found {len(features)} transmission lines in {total_time:.2f}s")
        
        return {
            "type": "FeatureCollection",
            "query": {
                "point": {"lon": lon, "lat": lat},
                "radius_km": radius_km
            },
            "count": len(features),
            "features": features,
            "states_scanned": candidate_states,
            "timing": {
                "total_s": round(total_time, 2)
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in transmission_at_point: {e}")
        raise HTTPException(500, f"Query failed: {str(e)}")


async def get_transmission_lines_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get transmission lines data directly from the transmission logic."""
    lat, lon = coordinates['lat'], coordinates['lon']
    
    # Call the core transmission logic
    try:
        return _get_transmission_lines_core(lon=lon, lat=lat, radius_km=5.0, limit=100)
    except Exception as e:
        logger.error(f"Transmission lines error: {e}")
        return {"error": str(e), "features": []}


async def get_weather_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get comprehensive weather data from multiple NOAA APIs."""
    lat, lon = coordinates['lat'], coordinates['lon']
    radius = 0.1  # degrees (~7 miles)
    years = 5
    
    # Normalize longitude for US
    normalized_lon = normalize_us_lon(lon)
    
    result = {
        "location": {"latitude": lat, "longitude": normalized_lon},
        "current_conditions": None,
        "active_alerts": None,
        "stations": None,
        "historical_data": None
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # STEP 1: Get NWS gridpoint and current conditions
            point_url = f"{WEATHER_APIS['NWS_API_BASE']}/points/{lat},{normalized_lon}"
            point_response = await client.get(point_url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if point_response.is_success:
                result["nws_point"] = point_response.json()
            
            # STEP 2: Get active weather alerts
            alerts_url = f"{WEATHER_APIS['NWS_API_BASE']}/alerts/active?point={lat},{normalized_lon}"
            alerts_response = await client.get(alerts_url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if alerts_response.is_success:
                result["active_alerts"] = alerts_response.json()
            
            # STEP 3: Find best weather station for historical data
            extent = f"{lat - radius},{normalized_lon - radius},{lat + radius},{normalized_lon + radius}"
            stations_url = f"{WEATHER_APIS['NOAA_CDO_BASE']}/stations?datasetid=GHCND&extent={extent}&limit=5&sortfield=datacoverage&sortorder=desc"
            stations_response = await client.get(
                stations_url, 
                headers={'User-Agent': API_CONFIG['USER_AGENT'], 'token': API_CONFIG['NOAA_CDO_TOKEN']}
            )
            if stations_response.is_success:
                stations_data = stations_response.json()
                result["stations"] = stations_data
                
                # STEP 4: Fetch historical weather data if station found
                if stations_data.get('results') and len(stations_data['results']) > 0:
                    best_station = stations_data['results'][0]
                    
                    from datetime import datetime, timedelta
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=365 * years)
                    
                    weather_url = f"{WEATHER_APIS['NOAA_ACCESS_BASE']}?dataset=daily-summaries&stations={best_station['id'][6:]}&startDate={start_date.strftime('%Y-%m-%d')}&endDate={end_date.strftime('%Y-%m-%d')}&dataTypes=TMAX,TMIN,PRCP,SNOW,SNWD,AWND&units=standard&format=json"
                    
                    weather_response = await client.get(weather_url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
                    if weather_response.is_success:
                        result["historical_data"] = weather_response.json()
            
            return result
            
        except Exception as e:
            logger.error(f"Weather data error: {e}")
            result["error"] = str(e)
            return result


async def get_water_resources_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get water resources data from USGS APIs."""
    lat, lon = coordinates['lat'], coordinates['lon']
    radius_miles = 25
    
    # Normalize longitude for US
    normalized_lon = normalize_us_lon(lon)
    
    # Convert radius from miles to degrees (approximate)
    radius_degrees = radius_miles / 69.0
    
    # Create proper bbox
    bbox = create_bbox(lat, normalized_lon, radius_degrees)
    
    result = {
        "location": {"latitude": lat, "longitude": normalized_lon},
        "surface_water_sites": None,
        "groundwater_sites": None
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Find nearby surface water monitoring locations (streams/rivers)
            surface_water_url = f"{WATER_APIS['USGS_OGC_BASE']}/collections/monitoring-locations/items?bbox={bbox}&site_type_code=ST&limit=50&f=json"
            surface_response = await client.get(surface_water_url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if surface_response.is_success:
                result["surface_water_sites"] = surface_response.json()
            
            # Find nearby groundwater monitoring locations
            groundwater_url = f"{WATER_APIS['USGS_OGC_BASE']}/collections/monitoring-locations/items?bbox={bbox}&site_type_code=GW&limit=50&f=json"
            groundwater_response = await client.get(groundwater_url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if groundwater_response.is_success:
                result["groundwater_sites"] = groundwater_response.json()
            
            return result
            
        except Exception as e:
            logger.error(f"Water resources error: {e}")
            result["error"] = str(e)
            return result


async def get_wind_turbines_raw(city: str) -> Dict[str, Any]:
    """Get wind turbines by state from USGS API."""
    # Extract state from city string
    state_part = city.split(',')[-1].strip() if ',' in city else None
    
    if not state_part:
        raise HTTPException(status_code=400, detail="City must include state (e.g., 'Austin, TX')")
    
    abbrev = state_part.upper()
    if abbrev not in STATE_ABBREV_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown state abbreviation: {abbrev}")
    
    state_name = STATE_ABBREV_MAP[abbrev]
    
    # Build query parameters
    select_fields = ['p_name', 'p_year', 'p_cap', 't_cap', 't_hh', 't_rd', 't_ttlh', 'ylat', 'xlong', 't_offshore', 't_conf_loc']
    select_str = ','.join(select_fields)
    
    url = f"{WIND_APIS['USGS_BASE']}?t_state=eq.{state_name.upper()}&t_offshore=eq.0&t_conf_loc=gte.2&select={select_str}&order=t_cap.desc&limit=100"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"USGS Wind API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="USGS Wind API request timed out. The service may be slow or unavailable.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"USGS Wind API connection error: {str(e)}")


async def get_wind_turbines_near_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get wind turbines near location from USGS API."""
    lat, lon = coordinates['lat'], coordinates['lon']
    radius_km = 50
    limit = 100
    
    # Convert radius to approximate lat/lon bounds
    lat_delta = radius_km / 111  # Rough conversion: 1 degree ≈ 111 km
    lon_delta = radius_km / (111 * abs(math.cos(math.radians(lat))))
    
    min_lat = lat - lat_delta
    max_lat = lat + lat_delta
    min_lon = lon - lon_delta
    max_lon = lon + lon_delta
    
    # Build query for geographic bounds
    url = f"{WIND_APIS['USGS_BASE']}?ylat=gte.{min_lat}&ylat=lte.{max_lat}&xlong=gte.{min_lon}&xlong=lte.{max_lon}&t_conf_loc=gte.2&select=p_name,p_year,t_cap,t_hh,t_rd,ylat,xlong&order=t_cap.desc&limit={limit}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"USGS Wind API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="USGS Wind API request timed out. The service may be slow or unavailable.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"USGS Wind API connection error: {str(e)}")


def _get_broadband_core(lon: float, lat: float, radius_km: float = 0.5, min_download: Optional[float] = None, min_upload: Optional[float] = None, limit: int = 100) -> Dict[str, Any]:
    """Core broadband logic without FastAPI dependencies."""
    global con
    
    if con is None:
        raise HTTPException(503, "Database not initialized")
    
    # Validate coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise HTTPException(400, f"Invalid coordinates: lon={lon}, lat={lat}")
    
    logger.info(f"Query: point=({lon}, {lat}), radius={radius_km}km, min_down={min_download}, min_up={min_upload}")
    
    try:
        import time
        start_time = time.time()
        
        # Phase 0: Determine which state contains the point (instant, no S3 access)
        # Use 0 buffer and take only the first state (bounding boxes can overlap)
        all_candidates = get_candidate_states(lon, lat, buffer_deg=0.0)
        candidate_states = [all_candidates[0]] if all_candidates else []
        
        # Calculate degree buffer for spatial queries within the state
        deg_buffer = radius_km / 111.0  # rough conversion: 1 degree ≈ 111km at equator
        
        if not candidate_states:
            logger.warning(f"No candidate states for point ({lon}, {lat})")
            return {
                "point": {"lon": lon, "lat": lat},
                "radius_km": radius_km,
                "results": [],
                "method": "state_filter",
                "message": "Point outside known US boundaries"
            }
        
        # Build S3 paths for only the relevant state(s)
        state_paths = [f"s3://{S3_GEO_BUCKET}/{S3_GEO_PREFIX}{state}.parquet" for state in candidate_states]

        logger.info(f"Scanning states: {candidate_states}")
        
        # Phase 1: Fast bbox filter - only scan relevant state parquet files
        bbox_sql = f"""
        SELECT block_geoid
        FROM read_parquet([{','.join([f"'{p}'" for p in state_paths])}], union_by_name=true)
        WHERE ? BETWEEN minx - ? AND maxx + ?
          AND ? BETWEEN miny - ? AND maxy + ?
        LIMIT 500
        """

        
        bbox_result = con.execute(
            bbox_sql,
            [lon, deg_buffer, deg_buffer, lat, deg_buffer, deg_buffer]
        ).fetchall()
        
        if not bbox_result:
            return {
                "point": {"lon": lon, "lat": lat},
                "radius_km": radius_km,
                "results": [],
                "method": "bbox_filter",
                "message": "No census blocks found in search area"
            }
        
        candidate_geoids = [row[0] for row in bbox_result]
        bbox_time = time.time() - start_time
        logger.info(f"Found {len(candidate_geoids)} candidate blocks after bbox filter in {bbox_time:.2f}s")
        
        # Safety: Limit candidates to prevent memory issues
        if len(candidate_geoids) > 100:
            logger.warning(f"Too many candidates ({len(candidate_geoids)}), limiting to 100")
            candidate_geoids = candidate_geoids[:100]
        
        # Phase 2: Exact spatial check - now load geometry only for candidates
        # Build parameterized query to avoid SQL injection
        placeholders = ",".join(["?"] * len(candidate_geoids))
        radius_deg = radius_km / 111.0
        
        spatial_sql = f"""
        SELECT 
            block_geoid,
            ST_Distance(geometry, ST_Point(?, ?)) * 111.0 as distance_km
        FROM read_parquet([{','.join([f"'{p}'" for p in state_paths])}], union_by_name=true)
        WHERE block_geoid IN ({placeholders})
          AND ST_DWithin(geometry, ST_Point(?, ?), ?)
        ORDER BY distance_km
        LIMIT 50
        """
        
        spatial_result = con.execute(
            spatial_sql,
            [lon, lat] + candidate_geoids + [lon, lat, radius_deg]
        ).fetchall()
        
        if not spatial_result:
            return {
                "point": {"lon": lon, "lat": lat},
                "radius_km": radius_km,
                "results": [],
                "method": "spatial_filter",
                "message": "No census blocks within radius after spatial check",
                "candidates_checked": len(candidate_geoids)
            }
        
        spatial_time = time.time() - start_time - bbox_time
        logger.info(f"Found {len(spatial_result)} blocks after spatial check in {spatial_time:.2f}s")
        
        # Phase 3: Join with broadband data
        matching_geoids = [row[0] for row in spatial_result]
        distances = {row[0]: row[1] for row in spatial_result}
        
        # Build state-specific broadband paths (same states as geo query)
        broadband_paths = [f"s3://{S3_BROADBAND_BUCKET}/{S3_BROADBAND_PREFIX}{state}.parquet" for state in candidate_states]
        
        # Build filter conditions
        where_clauses = ["b.block_geoid IN ({})".format(
            ",".join([f"'{g}'" for g in matching_geoids])
        )]
        
        if min_download is not None:
            where_clauses.append(f"b.max_down >= {min_download}")
        if min_upload is not None:
            where_clauses.append(f"b.max_up >= {min_upload}")
        
        where_sql = " AND ".join(where_clauses)
        
        # Query with flexible column selection (handles different schemas)
        # Only scan broadband files for the relevant states
        broadband_sql = f"""
        SELECT *
        FROM read_parquet([{','.join([f"'{p}'" for p in broadband_paths])}], union_by_name=true) b
        WHERE {where_sql}
        LIMIT {int(limit)}
        """
        
        broadband_time_start = time.time()
        cur = con.execute(broadband_sql)
        broadband_time = time.time() - broadband_time_start
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        
        # Format results with distance
        results = []
        for row in rows:
            record = dict(zip(cols, row))
            record['distance_km'] = round(distances.get(record['block_geoid'], 0), 3)
            results.append(record)
        
        # Sort by distance
        results.sort(key=lambda x: x['distance_km'])
        
        total_time = time.time() - start_time
        logger.info(f"Returning {len(results)} broadband records in {total_time:.2f}s total (broadband query: {broadband_time:.2f}s)")
        
        return {
            "point": {"lon": lon, "lat": lat},
            "radius_km": radius_km,
            "results": results,
            "method": "state_optimized_spatial",
            "states_scanned": candidate_states,
            "candidates_checked": len(candidate_geoids),
            "blocks_matched": len(spatial_result),
            "timing": {
                "bbox_filter_s": round(bbox_time, 2),
                "spatial_check_s": round(spatial_time, 2),
                "broadband_query_s": round(broadband_time, 2),
                "total_s": round(total_time, 2)
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in broadband_at_point: {e}")
        raise HTTPException(500, f"Query failed: {str(e)}")


async def make_broadband_request(params: Dict[str, Any]) -> Dict[str, Any]:
    """Make broadband API request by calling the broadband function directly."""
    try:
        # Extract parameters
        lon = params.get('lon')
        lat = params.get('lat')
        radius_km = params.get('radius_km', 0.5)
        min_download = params.get('min_download')
        min_upload = params.get('min_upload')
        limit = params.get('limit', 100)
        
        # Call the core broadband function
        return _get_broadband_core(
            lon=lon, 
            lat=lat, 
            radius_km=radius_km,
            min_download=min_download,
            min_upload=min_upload,
            limit=limit
        )
            
    except Exception as e:
        logger.error(f"Broadband API Error: {e}")
        return {"error": str(e), "results": []}


async def get_broadband_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get broadband connectivity data."""
    lat, lon = coordinates['lat'], coordinates['lon']
    
    params = {
        'lat': lat,
        'lon': lon,
        'radius_km': 0.5,
        'limit': 100
    }
    
    return await make_broadband_request(params)


async def make_overpass_request(query: str) -> Dict[str, Any]:
    """Make Overpass API request for transportation data."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    TRANSPORTATION_APIS['OVERPASS_BASE'],
                    data=query,
                    headers={
                        'User-Agent': API_CONFIG['USER_AGENT'],
                        'Content-Type': 'text/plain',
                    }
                )
                
                if not response.is_success:
                    raise HTTPException(status_code=response.status_code, detail=f"Overpass API request failed: {response.status_code}")
                
                return response.json()
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Overpass API request timed out. The service may be slow or unavailable.")
            except httpx.RequestError as e:
                raise HTTPException(status_code=503, detail=f"Overpass API connection error: {str(e)}")
            
    except Exception as e:
        logger.error(f"Overpass API Error: {e}")
        return {"error": str(e), "elements": []}


async def get_transportation_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get comprehensive transportation data."""
    lat, lon = coordinates['lat'], coordinates['lon']
    search_radius = 25  # km
    
    # Comprehensive transportation query
    query = f"""[out:json][timeout:30];
    (
      way(around:{search_radius * 1000},{lat},{lon})["highway"~"^(motorway|trunk|primary)$"];
      way(around:{search_radius * 1000},{lat},{lon})["railway"="rail"];
      node(around:{search_radius * 1000},{lat},{lon})["highway"="motorway_junction"];
      node(around:{search_radius * 1000},{lat},{lon})["railway"="station"];
      node(around:50000,{lat},{lon})["aeroway"="aerodrome"]["aerodrome:type"~"^(international|regional)$"];
      node(around:100000,{lat},{lon})["place"="city"]["harbour"="yes"];
    );
    out geom;"""
    
    return await make_overpass_request(query)


async def get_highway_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get highway access data."""
    lat, lon = coordinates['lat'], coordinates['lon']
    
    # Focused highway query
    query = f"""[out:json][timeout:30];
    (
      way(around:50000,{lat},{lon})["highway"="motorway"];
      way(around:50000,{lat},{lon})["highway"="trunk"];
      node(around:50000,{lat},{lon})["highway"="motorway_junction"];
    );
    out geom;"""
    
    return await make_overpass_request(query)


async def get_rail_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get rail connectivity data."""
    lat, lon = coordinates['lat'], coordinates['lon']
    
    # Rail infrastructure query
    query = f"""[out:json][timeout:30];
    (
      way(around:100000,{lat},{lon})["railway"="rail"];
      node(around:100000,{lat},{lon})["railway"="station"];
      node(around:100000,{lat},{lon})["public_transport"="station"]["railway"];
    );
    out geom;"""
    
    return await make_overpass_request(query)



# ──────────────────────────────────────────────────────────────────────────────
# Individual API Endpoints for Each Tool
# ──────────────────────────────────────────────────────────────────────────────

class CityRequest(BaseModel):
    city: str

class CoordinatesRequest(BaseModel):
    lat: float
    lon: float

# ──────────────────────────────────────────────────────────────────────────────
# Electricity & Energy APIs
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/electricity-price", response_model=ElectricityPriceResponse)
async def electricity_price_endpoint(request: CityRequest) -> ElectricityPriceResponse:
    """Get electricity price data from EIA API."""
    try:
        raw_data = await get_electricity_price_raw(request.city)
        return transform_electricity_price(request.city, raw_data)
    except Exception as e:
        logger.exception(f"Electricity price API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/utility-rates", response_model=UtilityRatesResponse)
async def utility_rates_endpoint(request: CoordinatesRequest) -> UtilityRatesResponse:
    """Get utility rates from OpenEI API."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_utility_rates_raw(coordinates)
        return transform_utility_rates(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Utility rates API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/transmission-lines", response_model=TransmissionLinesResponse)
async def transmission_lines_endpoint(request: CoordinatesRequest) -> TransmissionLinesResponse:
    """Get transmission lines data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_transmission_lines_raw(coordinates)
        return transform_transmission_lines(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Transmission lines API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Weather & Climate APIs
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/datacenter-climate", response_model=ClimateDataResponse)
async def datacenter_climate_endpoint(request: CoordinatesRequest) -> ClimateDataResponse:
    """Get comprehensive weather data from multiple NOAA APIs."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_weather_data_raw(coordinates)
        return transform_climate_data(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Datacenter climate API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Water Resources APIs
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/water-resources", response_model=WaterResourcesResponse)
async def water_resources_endpoint(request: CoordinatesRequest) -> WaterResourcesResponse:
    """Get water resources data from USGS APIs."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_water_resources_raw(coordinates)
        return transform_water_resources(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Water resources API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Wind Energy APIs
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/wind-turbines-by-state", response_model=WindTurbinesResponse)
async def wind_turbines_by_state_endpoint(request: CityRequest) -> WindTurbinesResponse:
    """Get wind turbines by state from USGS API."""
    try:
        raw_data = await get_wind_turbines_raw(request.city)
        return transform_wind_turbines_state(request.city, raw_data)
    except Exception as e:
        logger.exception(f"Wind turbines by state API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/wind-turbines-near-location", response_model=WindTurbinesResponse)
async def wind_turbines_near_location_endpoint(request: CoordinatesRequest) -> WindTurbinesResponse:
    """Get wind turbines near location from USGS API."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_wind_turbines_near_raw(coordinates)
        return transform_wind_turbines_location(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Wind turbines near location API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Broadband & Connectivity APIs
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/broadband-connectivity", response_model=BroadbandResponse)
async def broadband_connectivity_endpoint(request: CoordinatesRequest) -> BroadbandResponse:
    """Get broadband connectivity data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_broadband_data_raw(coordinates)
        return transform_broadband_data(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Broadband connectivity API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))




# ──────────────────────────────────────────────────────────────────────────────
# Transportation & Logistics APIs
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/transportation-logistics", response_model=TransportationResponse)
async def transportation_logistics_endpoint(request: CoordinatesRequest) -> TransportationResponse:
    """Get comprehensive transportation data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_transportation_data_raw(coordinates)
        return transform_transportation_data(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Transportation logistics API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/highway-access", response_model=HighwayAccessResponse)
async def highway_access_endpoint(request: CoordinatesRequest) -> HighwayAccessResponse:
    """Get highway access data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_highway_data_raw(coordinates)
        return transform_highway_access(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Highway access API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rail-connectivity", response_model=RailConnectivityResponse)
async def rail_connectivity_endpoint(request: CoordinatesRequest) -> RailConnectivityResponse:
    """Get rail connectivity data."""
    try:
        coordinates = {"lat": request.lat, "lon": request.lon}
        raw_data = await get_rail_data_raw(coordinates)
        return transform_rail_connectivity(coordinates, raw_data)
    except Exception as e:
        logger.exception(f"Rail connectivity API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Helper utilities for safe aggregation
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_value(val):
    """Recursively sanitize values to be JSON-compliant (replace inf/NaN with None)."""
    if isinstance(val, dict):
        return {k: sanitize_value(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_value(v) for v in val]
    elif isinstance(val, float):
        if not np.isfinite(val):
            return None
        return val
    return val


def safe_mean(values):
    """Compute mean of numeric values, filtering out None and NaN."""
    vals = [v for v in values if isinstance(v, (int, float)) and not np.isnan(v)]
    result = float(np.mean(vals)) if vals else None
    return None if result and not np.isfinite(result) else result


def safe_min(values):
    """Compute minimum of numeric values, filtering out None and NaN."""
    vals = [v for v in values if isinstance(v, (int, float)) and not np.isnan(v)]
    result = float(np.min(vals)) if vals else None
    return None if result and not np.isfinite(result) else result


def safe_count(values):
    """Count non-None values."""
    return len([v for v in values if v is not None])


# ──────────────────────────────────────────────────────────────────────────────
# /api/site-features - Aggregated Feature Vector for Model Input
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/site-features")
async def site_features_endpoint(request: CoordinatesRequest):
    """
    Aggregate all key metrics across domains into a numeric feature vector.
    
    Calls all existing APIs in parallel and extracts key features for ML/decision models.
    """
    coordinates = {"lat": request.lat, "lon": request.lon}

    try:
        # Run all async API calls in parallel using asyncio.gather
        # broadband, transmission, climate, water, wind, transport = await asyncio.gather(
        #     get_broadband_data_raw(coordinates),
        #     get_transmission_lines_raw(coordinates),
        #     get_weather_data_raw(coordinates),
        #     get_water_resources_raw(coordinates),
        #     get_wind_turbines_near_raw(coordinates),
        #     get_transportation_data_raw(coordinates),
        # )

        broadband, transmission, climate, water, transport = await asyncio.gather(
            get_broadband_data_raw(coordinates),
            get_transmission_lines_raw(coordinates),
            get_weather_data_raw(coordinates),
            get_water_resources_raw(coordinates),
            get_transportation_data_raw(coordinates),
        )

        # ─────────────────────────────────────────────────────────────────────
        # Extract Broadband Features
        # ─────────────────────────────────────────────────────────────────────
        broadband_results = broadband.get("results", [])
        avg_download = safe_mean([b.get("max_down") for b in broadband_results])
        avg_upload = safe_mean([b.get("max_up") for b in broadband_results])
        num_providers = len(set(b.get("provider") for b in broadband_results if b.get("provider")))
        
        # Count fiber providers (technology code 50 or similar)
        num_fiber = len([b for b in broadband_results if b.get("tech_code") in [50, "50"]])

        # ─────────────────────────────────────────────────────────────────────
        # Extract Transmission Features
        # ─────────────────────────────────────────────────────────────────────
        # Response can have either "features" or "lines" key
        transmission_features = transmission.get("features", [])
        if not transmission_features:
            transmission_features = transmission.get("lines", [])
        
        logger.info(f"Transmission response keys: {list(transmission.keys())}")
        logger.info(f"Number of transmission features/lines: {len(transmission_features)}")
        
        # Log the first line structure for debugging
        if transmission_features:
            first_line = transmission_features[0]
            logger.info(f"First transmission line keys: {list(first_line.keys())}")
            if 'properties' in first_line:
                logger.info(f"First line properties keys: {list(first_line['properties'].keys())}")
        
        # Extract voltage - it can be at top level (voltage_kv) or in properties (VOLTAGE)
        voltages = []
        distances = []
        for i, line in enumerate(transmission_features):
            # Try top-level voltage_kv first
            v = line.get("voltage_kv")
            if v is None:
                # Try properties
                props = line.get("properties", {})
                v = props.get("VOLTAGE") or props.get("voltage") or props.get("voltage_kv")
            
            # Log what we found for first few lines
            if i < 3 and v is not None:
                logger.info(f"Line {i} voltage: {v}")
            
            # Only add positive voltages (voltage should never be negative)
            if v is not None and v > 0:
                voltages.append(v)
            
            # Distance can also be at top level or in properties
            dist = line.get("distance_km")
            if dist is None:
                dist = line.get("properties", {}).get("distance_km")
            if dist is not None:
                distances.append(dist)
        
        logger.info(f"All extracted voltages ({len(voltages)} total): {voltages}")
        
        avg_voltage = safe_mean(voltages)
        logger.info(f"Computed avg_voltage: {avg_voltage}")
        
        nearest_transmission = safe_min(distances)
        num_transmission_lines = len(transmission_features)

        # ─────────────────────────────────────────────────────────────────────
        # Extract Climate Features
        # ─────────────────────────────────────────────────────────────────────
        hist_data = climate.get("historical_data", [])
        if isinstance(hist_data, list):
            def safe_float(val):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None
            
            temp_max_values = [v for v in (safe_float(d.get("TMAX")) for d in hist_data) if v is not None]
            temp_min_values = [v for v in (safe_float(d.get("TMIN")) for d in hist_data) if v is not None]
            precip_values = [v for v in (safe_float(d.get("PRCP")) for d in hist_data) if v is not None]
            wind_values = [v for v in (safe_float(d.get("AWND")) for d in hist_data) if v is not None]

            avg_temp_max = safe_mean(temp_max_values)
            avg_temp_min = safe_mean(temp_min_values)
            avg_precip = safe_mean(precip_values)
            avg_wind_speed = safe_mean(wind_values)

            # Temperature variability index: std(TMAX) / mean(TMAX)
            temp_variability_index = None
            if temp_max_values:
                std_temp = np.std(temp_max_values)
                mean_temp = np.mean(temp_max_values)
                if mean_temp > 0:
                    temp_variability_index = std_temp / mean_temp
        else:
            avg_temp_max = avg_temp_min = avg_precip = avg_wind_speed = temp_variability_index = None

        # ─────────────────────────────────────────────────────────────────────
        # Extract Water Resources Features
        # ─────────────────────────────────────────────────────────────────────
        surface_water = water.get("surface_water_sites", {})
        groundwater = water.get("groundwater_sites", {})

        num_surface_sites = len(surface_water.get("features", [])) if isinstance(surface_water, dict) else 0
        num_ground_sites = len(groundwater.get("features", [])) if isinstance(groundwater, dict) else 0

        # ─────────────────────────────────────────────────────────────────────
        # Extract Wind Turbine Features
        # ─────────────────────────────────────────────────────────────────────
        # turbines = wind if isinstance(wind, list) else []
        # avg_turbine_capacity = safe_mean([t.get("t_cap") for t in turbines])
        # num_turbines = safe_count(turbines)
        # avg_hub_height = safe_mean([t.get("t_hh") for t in turbines])

        # ─────────────────────────────────────────────────────────────────────
        # Extract Transportation Features
        # ─────────────────────────────────────────────────────────────────────
        transport_elements = transport.get("elements", [])
        
        highways = [e for e in transport_elements if e.get("tags", {}).get("highway") in ["motorway", "trunk", "primary"]]
        railways = [e for e in transport_elements if e.get("tags", {}).get("railway") == "rail"]
        
        num_highways = safe_count(highways)
        num_railways = safe_count(railways)

        # ─────────────────────────────────────────────────────────────────────
        # Build Feature Vector
        # ─────────────────────────────────────────────────────────────────────
        def sanitize_float(value):
            """Convert inf/NaN to None for JSON compliance."""
            if value is None:
                return None
            if isinstance(value, (int, float)):
                if not np.isfinite(value):  # catches inf, -inf, nan
                    return None
            return value
        
        features = {
            # Broadband Infrastructure
            "avg_download_speed_mbps": sanitize_float(avg_download),
            "avg_upload_speed_mbps": sanitize_float(avg_upload),
            "num_providers": sanitize_float(num_providers),
            "num_fiber_providers": sanitize_float(num_fiber),

            # Power Transmission Infrastructure
            "avg_voltage_kv": sanitize_float(avg_voltage),
            "nearest_transmission_km": sanitize_float(nearest_transmission),
            "num_transmission_lines": sanitize_float(num_transmission_lines),

            # Climate and Environmental Factors
            "avg_temp_max_f": sanitize_float(avg_temp_max),
            "avg_temp_min_f": sanitize_float(avg_temp_min),
            "avg_precip_in": sanitize_float(avg_precip),
            "avg_wind_speed_mph": sanitize_float(avg_wind_speed),
            "temp_variability_index": sanitize_float(temp_variability_index),
            "wind_solar_complementarity": None,  # Placeholder - would need solar data

            # Water Resources
            "num_surface_water_sites": sanitize_float(num_surface_sites),
            "num_groundwater_sites": sanitize_float(num_ground_sites),

            # Transportation and Logistics
            "num_highways_within_50km": sanitize_float(num_highways),
            "num_railways_within_100km": sanitize_float(num_railways)
        }

        response = {"coordinates": coordinates, "features": features}
        return sanitize_value(response)

    except Exception as e:
        logger.exception(f"Site features aggregation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# /api/training-dataset - Export Features for ML Training
# ──────────────────────────────────────────────────────────────────────────────

class TrainingDatasetRequest(BaseModel):
    coordinates: CoordinatesRequest
    include_target: Optional[bool] = False  # For future labeled data

@app.post("/api/training-dataset")
async def training_dataset_endpoint(request: TrainingDatasetRequest):
    """
    Generate a training dataset from multiple coordinates.

    Returns features suitable for ML training with proper data types and null handling.
    """
    try:
        dataset = []
        coordinates = request.coordinates

        try:
            # Get features for this coordinate
            features_response = await site_features_endpoint(request.coordinates)
            features = features_response["features"]

            # Add coordinate info
            row = {
                "latitude": coordinates.lat,
                "longitude": coordinates.lon,
                **features
            }

            dataset.append(row)

        except Exception as e:
            logger.warning(f"Failed to get features for coordinates (lat: {coord.lat}, lon: {coord.lon}): {e}")

        if not dataset:
            raise HTTPException(status_code=400, detail="No valid coordinates provided or all failed to process")

        # Convert to format suitable for ML libraries
        import pandas as pd
        df = pd.DataFrame(dataset)

        # Ensure proper data types
        numeric_columns = [
            'avg_download_speed_mbps', 'avg_upload_speed_mbps', 'num_providers', 'num_fiber_providers',
            'avg_voltage_kv', 'nearest_transmission_km', 'num_transmission_lines',
            'avg_temp_max_f', 'avg_temp_min_f', 'avg_precip_in', 'avg_wind_speed_mph', 'temp_variability_index',
            'num_surface_water_sites', 'num_groundwater_sites',
            'num_highways_within_50km', 'num_railways_within_100km'
        ]

        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Replace inf/NaN with None for JSON compliance
        df = df.replace([np.inf, -np.inf, np.nan], None)

        response = {
            "dataset": df.to_dict('records'),
            "metadata": {
                "num_samples": len(dataset),
                "feature_columns": list(df.columns),
                "numeric_features": numeric_columns,
                "coordinate_system": "WGS84"
            }
        }
        
        # Sanitize the entire response to catch any remaining inf/NaN
        return sanitize_value(response)

    except Exception as e:
        logger.exception(f"Training dataset generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# /api/site-score - Normalized Site Suitability Score
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/site-score")
async def site_score_endpoint(request: CoordinatesRequest):
    """
    Compute a normalized site suitability score based on weighted subscores
    from each domain (broadband, energy, water, climate, wind, transport).
    
    Returns:
    - overall_score: Weighted composite score (0-1)
    - subscores: Individual domain scores (0-1)
    - features_used: Raw feature values
    """
    try:
        # Get aggregated features
        feature_resp = await site_features_endpoint(request)
        features = feature_resp["features"]

        # ─────────────────────────────────────────────────────────────────────
        # Normalization Helper
        # ─────────────────────────────────────────────────────────────────────
        def normalize(value, min_val, max_val):
            """Linear normalization to 0-1 range."""
            if value is None:
                return 0.0
            return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))

        # ─────────────────────────────────────────────────────────────────────
        # Compute Domain-Specific Subscores
        # ─────────────────────────────────────────────────────────────────────
        
        # Broadband: Higher download speed is better (100-1000 Mbps range)
        broadband_score = normalize(features.get("avg_download_speed_mbps"), 100, 1000)
        
        # Transmission: Closer is better (0-50km range, inverted)
        transmission_score = 1 - normalize(features.get("nearest_transmission_km"), 0, 50)
        
        # Climate: Cooler is better for datacenters (target ~70F, penalize deviation)
        temp_deviation = abs((features.get("avg_temp_max_f") or 70) - 70)
        climate_score = 1 - normalize(temp_deviation, 0, 30)
        
        # Water: More sites nearby is better (0-20 sites range)
        total_water_sites = (features.get("num_surface_water_sites") or 0) + (features.get("num_groundwater_sites") or 0)
        water_score = normalize(total_water_sites, 0, 20)
        
        # Wind: Higher capacity turbines nearby indicate renewable energy potential
        wind_score = normalize(features.get("avg_turbine_capacity_kw"), 1000, 5000)
        
        # Transportation: More infrastructure is better
        transport_count = (
            (features.get("num_highways_within_50km") or 0) +
            (features.get("num_railways_within_100km") or 0)
        )
        transport_score = normalize(transport_count, 0, 10)

        # ─────────────────────────────────────────────────────────────────────
        # Weighted Composite Score
        # ─────────────────────────────────────────────────────────────────────
        weights = {
            "broadband": 0.25,
            "transmission": 0.20,
            "climate": 0.15,
            "water": 0.15,
            "wind": 0.15,
            "transport": 0.10,
        }

        overall = (
            broadband_score * weights["broadband"] +
            transmission_score * weights["transmission"] +
            climate_score * weights["climate"] +
            water_score * weights["water"] +
            wind_score * weights["wind"] +
            transport_score * weights["transport"]
        )

        return {
            "coordinates": feature_resp["coordinates"],
            "overall_score": round(overall, 3),
            "subscores": {
                "broadband": round(broadband_score, 3),
                "transmission": round(transmission_score, 3),
                "climate": round(climate_score, 3),
                "water": round(water_score, 3),
                "wind": round(wind_score, 3),
                "transport": round(transport_score, 3)
            },
            "features_used": features,
        }

    except Exception as e:
        logger.exception(f"Site scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

