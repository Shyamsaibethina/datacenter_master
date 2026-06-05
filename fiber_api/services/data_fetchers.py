"""
Raw data fetchers for external APIs (EIA, OpenEI, NOAA, USGS, Overpass, etc.)
"""
import asyncio
import logging
import math
from typing import Dict, Any
from datetime import datetime, timedelta
import httpx
from fastapi import HTTPException

from config import (
    API_CONFIG, ELECTRICITY_APIS, WEATHER_APIS, WATER_APIS, WIND_APIS,
    TRANSPORTATION_APIS, STATE_ID_MAP, STATE_ABBREV_MAP
)
from utils import normalize_us_lon, create_bbox
from database import get_broadband_core, get_transmission_lines_core
from cache import cached_coordinate_query

logger = logging.getLogger("uvicorn.error")


async def get_electricity_price_raw(city: str) -> Dict[str, Any]:
    """Get electricity price data from EIA API."""
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
    now = datetime.now()
    three_months_ago = now - timedelta(days=90)
    start_date = three_months_ago.strftime('%Y-%m')
    end_date = start_date
    
    url = f"{ELECTRICITY_APIS['EIA_BASE']}/electricity/retail-sales/data?api_key={API_CONFIG['EIA_API_KEY']}&data[]=price&facets[sectorid][]=IND&facets[stateid][]={state_id}&frequency=monthly&start={start_date}&end={end_date}&sort[0][column]=period&sort[0][direction]=desc&length=1"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"EIA API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="EIA API request timed out.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"EIA API connection error: {str(e)}")


async def get_utility_rates_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get utility rates from OpenEI API."""
    lat, lon = coordinates['lat'], coordinates['lon']
    radius = 10
    sector = "Commercial"
    
    url = f"{ELECTRICITY_APIS['OPENEI_BASE']}?version=latest&format=json&api_key={API_CONFIG['OPENEI_API_KEY']}&lat={lat}&lon={lon}&radius={radius}&sector={sector}&approved=true&detail=full&limit=50"

    print(url)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"OpenEI API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="OpenEI API request timed out.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"OpenEI API connection error: {str(e)}")


import time

# Per-state cache: {state_id: (generators_list, timestamp)}
_state_generators_cache = {}
_generators_cache_ttl = 86400  # 24 hours


async def get_generators_for_state(state_id: str) -> list:
    """Get all generators for a specific state from EIA API (cached per state for 24h)."""
    global _state_generators_cache
    
    # Check if we have valid cached data for this state
    if state_id in _state_generators_cache:
        generators, cache_time = _state_generators_cache[state_id]
        if (time.time() - cache_time) < _generators_cache_ttl:
            logger.info(f"Using cached data for state {state_id}: {len(generators)} generators")
            return generators
    
    # Fetch data for this state
    logger.info(f"Fetching generators for state {state_id} from EIA API...")
    all_generators = []
    offset = 0
    batch_size = 5000
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        while True:
            try:
                # Request generators for this specific state using facets, with explicit fields
                url = f"{ELECTRICITY_APIS['EIA_BASE']}/electricity/operating-generator-capacity/data?api_key={API_CONFIG['EIA_API_KEY']}&frequency=monthly&data[0]=latitude&data[1]=longitude&data[2]=nameplate-capacity-mw&facets[stateid][]={state_id}&sort[0][column]=period&sort[0][direction]=desc&offset={offset}&length={batch_size}"
                
                response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
                if not response.is_success:
                    raise HTTPException(status_code=response.status_code, detail=f"EIA API request failed: {response.status_code}")
                
                data = response.json()
                batch = data.get('response', {}).get('data', [])
                
                if not batch:
                    break
                
                all_generators.extend(batch)
                logger.info(f"Fetched batch of {len(batch)} generators (total: {len(all_generators)})")
                
                # If we got fewer than batch_size, we've reached the end
                if len(batch) < batch_size:
                    break
                
                offset += batch_size
                
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="EIA API request timed out.")
            except httpx.RequestError as e:
                raise HTTPException(status_code=503, detail=f"EIA API connection error: {str(e)}")
    
    # Cache the results for this state
    _state_generators_cache[state_id] = (all_generators, time.time())
    logger.info(f"✅ Cached {len(all_generators)} generators for state {state_id}")
    
    return all_generators


async def get_generator_capacity_raw(coordinates: Dict[str, float], radius_miles: int = 5) -> Dict[str, Any]:
    """Get operating generator capacity near coordinates."""
    from utils import get_candidate_states
    import math
    
    lat, lon = coordinates['lat'], coordinates['lon']
    provided_state = coordinates.get('state')
    
    # Step 1: Find what state the point is in
    if provided_state:
        # Use provided state directly (from city_state column)
        state_id = provided_state.upper()
        logger.info(f"Using provided state: {state_id} for ({lat}, {lon})")
    else:
        # Fall back to coordinate-based detection
        states = get_candidate_states(lon, lat, buffer_deg=1.0)
        if not states:
            raise HTTPException(status_code=400, detail=f"Could not determine state for coordinates")
        state_id = states[0]  # Use most likely state
        logger.info(f"Point ({lat}, {lon}) detected in state: {state_id}")
    
    # Step 2: Get all generators in that state (cached per state)
    state_generators = await get_generators_for_state(state_id)
    
    # Step 3: Filter by 100 mile radius
    radius_km = radius_miles * 1.60934
    
    filtered_generators = []
    no_coords = 0
    invalid_coords = 0
    
    for item in state_generators:
        # Check if has coordinates and convert to float
        gen_lat = item.get('latitude')
        gen_lon = item.get('longitude')
        
        if gen_lat is None or gen_lon is None:
            no_coords += 1
            continue
        
        try:
            gen_lat = float(gen_lat)
            gen_lon = float(gen_lon)
        except (ValueError, TypeError):
            invalid_coords += 1
            continue
        
        # Calculate distance using Haversine formula
        R = 6371  # Earth's radius in km
        dlat = math.radians(gen_lat - lat)
        dlon = math.radians(gen_lon - lon)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(gen_lat)) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance_km = R * c
        
        # Filter by radius
        if distance_km <= radius_km:
            item['distance_km'] = round(distance_km, 2)
            item['distance_miles'] = round(distance_km / 1.60934, 2)
            filtered_generators.append(item)
    
    # Sort by distance
    filtered_generators.sort(key=lambda x: x['distance_km'])
    
    logger.info(f"Filtering stats: {len(state_generators)} total, {no_coords} missing coords, {invalid_coords} invalid coords, {len(filtered_generators)} within {radius_miles} miles")
    
    return {
        'response': {
            'data': filtered_generators
        },
        'query': {
            'state': state_id,
            'radius_miles': radius_miles,
            'coordinates': coordinates
        }
    }


async def get_transmission_lines_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get transmission lines data directly from the transmission logic."""
    lat, lon = coordinates['lat'], coordinates['lon']
    
    try:
        # get_transmission_lines_core is synchronous (blocking DuckDB); offload to a
        # thread so the event loop can run the other domains' async calls concurrently.
        return await asyncio.to_thread(
            get_transmission_lines_core, lon=lon, lat=lat, radius_km=5.0, limit=100
        )
    except Exception as e:
        logger.error(f"Transmission lines error: {e}")
        return {"error": str(e), "features": []}


@cached_coordinate_query(precision=4, ttl=604800 * 4, namespace="climate")
async def get_weather_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get historical weather data from Open-Meteo API and calculate metrics.
    
    Cached at geohash precision 4 (~20km) because climate is uniform at that scale.
    TTL of 4 weeks since historical averages barely change.
    """
    from datetime import datetime, timedelta
    import statistics
    
    lat, lon = coordinates['lat'], coordinates['lon']
    
    # Use 2 years instead of 5 to reduce payload size and be friendlier to rate limits
    end_date = datetime.now() - timedelta(days=7)
    start_date = end_date - timedelta(days=365 * 2)
    
    # Open-Meteo Archive API for historical data
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start_date.strftime('%Y-%m-%d')}"
        f"&end_date={end_date.strftime('%Y-%m-%d')}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
        f"&temperature_unit=fahrenheit"
        f"&precipitation_unit=inch"
        f"&wind_speed_unit=mph"
        f"&timezone=America/New_York"
    )
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # Retry with exponential backoff for 429 rate limits
            response = None
            for attempt in range(3):
                response = await client.get(url)
                if response.status_code != 429:
                    break
                wait = 2 ** attempt
                logger.warning(f"Open-Meteo 429, retrying in {wait}s (attempt {attempt+1}/3)")
                await asyncio.sleep(wait)
            
            if not response.is_success:
                logger.warning(f"Open-Meteo failed with {response.status_code} for ({lat},{lon}), returning empty metrics")
                return {"metrics": {}, "data_points": 0}
            
            data = response.json()
            daily = data.get('daily', {})
            
            # Extract arrays
            temp_max_list = [t for t in daily.get('temperature_2m_max', []) if t is not None]
            temp_min_list = [t for t in daily.get('temperature_2m_min', []) if t is not None]
            precip_list = [p for p in daily.get('precipitation_sum', []) if p is not None]
            wind_list = [w for w in daily.get('wind_speed_10m_max', []) if w is not None]
            
            # Calculate metrics
            avg_temp_max_f = statistics.mean(temp_max_list) if temp_max_list else None
            avg_temp_min_f = statistics.mean(temp_min_list) if temp_min_list else None
            avg_precip_in = statistics.mean(precip_list) if precip_list else None
            avg_wind_speed_mph = statistics.mean(wind_list) if wind_list else None
            
            # Temperature variability index: coefficient of variation of daily max temps
            temp_variability_index = None
            if temp_max_list and avg_temp_max_f and avg_temp_max_f != 0:
                temp_std = statistics.stdev(temp_max_list) if len(temp_max_list) > 1 else 0
                temp_variability_index = temp_std / abs(avg_temp_max_f)
            
            result = {
                "location": {"latitude": lat, "longitude": lon},
                "metrics": {
                    "avg_temp_max_f": round(avg_temp_max_f, 2) if avg_temp_max_f else None,
                    "avg_temp_min_f": round(avg_temp_min_f, 2) if avg_temp_min_f else None,
                    "avg_precip_in": round(avg_precip_in, 4) if avg_precip_in else None,
                    "avg_wind_speed_mph": round(avg_wind_speed_mph, 2) if avg_wind_speed_mph else None,
                    "temp_variability_index": round(temp_variability_index, 4) if temp_variability_index else None
                },
                "data_points": len(temp_max_list)
            }
            
            logger.info(f"Weather data for ({lat}, {lon}): {len(temp_max_list)} days of data")
            return result
            
        except Exception as e:
            logger.error(f"Weather data error for ({lat},{lon}): {e}")
            return {"metrics": {}, "data_points": 0}


async def get_water_resources_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get water resources data from USGS Water Services (mapper XML format).
    
    Uses waterservices.usgs.gov which is reliable and has no rate limits.
    Returns site counts parsed from the mapper XML response.
    """
    import xml.etree.ElementTree as ET

    lat, lon = coordinates['lat'], coordinates['lon']
    radius_miles = coordinates.get('radius_miles', 25)
    
    normalized_lon = normalize_us_lon(lon)
    radius_degrees = radius_miles / 69.0
    # bbox format for USGS: west,south,east,north
    west = normalized_lon - radius_degrees
    south = lat - radius_degrees
    east = normalized_lon + radius_degrees
    north = lat + radius_degrees
    bbox_str = f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"
    
    result = {
        "location": {"latitude": lat, "longitude": normalized_lon},
        "surface_water_sites": {"features": []},
        "groundwater_sites": {"features": []}
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            base = "https://waterservices.usgs.gov/nwis/site/"

            surface_url = f"{base}?format=mapper&bBox={bbox_str}&siteType=ST&siteStatus=active"
            ground_url = f"{base}?format=mapper&bBox={bbox_str}&siteType=GW&siteStatus=active"

            surface_resp, ground_resp = await asyncio.gather(
                client.get(surface_url, headers={"User-Agent": API_CONFIG["USER_AGENT"]}),
                client.get(ground_url, headers={"User-Agent": API_CONFIG["USER_AGENT"]}),
                return_exceptions=True,
            )

            def parse_mapper_xml(resp) -> list:
                """Parse USGS mapper XML into GeoJSON Point features so both the
                transformer (reads geometry.coordinates) and the map overlay can
                consume the same shape."""
                if isinstance(resp, Exception) or not resp.is_success:
                    return []
                try:
                    root = ET.fromstring(resp.text)
                    features = []
                    for s in root.findall(".//site"):
                        try:
                            slon = float(s.get("lng", 0))
                            slat = float(s.get("lat", 0))
                        except (TypeError, ValueError):
                            continue
                        features.append({
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [slon, slat]},
                            "properties": {
                                "identifier": s.get("sno"),
                                "name": s.get("sna"),
                                "agency": s.get("agc", "USGS"),
                                "active": True,
                            },
                        })
                    return features
                except Exception:
                    return []

            surface_sites = parse_mapper_xml(surface_resp)
            ground_sites = parse_mapper_xml(ground_resp)

            result["surface_water_sites"] = {"features": surface_sites}
            result["groundwater_sites"] = {"features": ground_sites}

            logger.info(f"Water resources for ({lat},{normalized_lon}): {len(surface_sites)} surface, {len(ground_sites)} ground")
            return result
            
        except Exception as e:
            logger.error(f"Water resources error: {e}")
            result["error"] = str(e)
            return result


async def get_wind_turbines_raw(city: str) -> Dict[str, Any]:
    """Get wind turbines by state from USGS API."""
    state_part = city.split(',')[-1].strip() if ',' in city else None
    
    if not state_part:
        raise HTTPException(status_code=400, detail="City must include state (e.g., 'Austin, TX')")
    
    abbrev = state_part.upper()
    if abbrev not in STATE_ABBREV_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown state abbreviation: {abbrev}")
    
    state_name = STATE_ABBREV_MAP[abbrev]
    
    select_fields = ['p_name', 'p_year', 'p_cap', 't_cap', 't_hh', 't_rd', 't_ttlh', 'ylat', 'xlong', 't_offshore', 't_conf_loc']
    select_str = ','.join(select_fields)
    
    url = f"{WIND_APIS['USGS_BASE']}?t_state=eq.{state_name.upper()}&t_offshore=eq.0&t_conf_loc=gte.2&select={select_str}&order=t_cap.desc&limit=100"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"USGS Wind API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="USGS Wind API request timed out.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"USGS Wind API connection error: {str(e)}")


async def get_wind_turbines_near_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get wind turbines near location from USGS API."""
    lat, lon = coordinates['lat'], coordinates['lon']
    radius_km = 50
    limit = 100
    
    lat_delta = radius_km / 111
    lon_delta = radius_km / (111 * abs(math.cos(math.radians(lat))))
    
    min_lat = lat - lat_delta
    max_lat = lat + lat_delta
    min_lon = lon - lon_delta
    max_lon = lon + lon_delta
    
    url = f"{WIND_APIS['USGS_BASE']}?ylat=gte.{min_lat}&ylat=lte.{max_lat}&xlong=gte.{min_lon}&xlong=lte.{max_lon}&t_conf_loc=gte.2&select=p_name,p_year,t_cap,t_hh,t_rd,ylat,xlong&order=t_cap.desc&limit={limit}"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(url, headers={'User-Agent': API_CONFIG['USER_AGENT']})
            if not response.is_success:
                raise HTTPException(status_code=response.status_code, detail=f"USGS Wind API request failed: {response.status_code}")
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="USGS Wind API request timed out.")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"USGS Wind API connection error: {str(e)}")


async def get_broadband_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get broadband connectivity data."""
    lat, lon = coordinates['lat'], coordinates['lon']
    
    try:
        # get_broadband_core is synchronous (blocking DuckDB); offload to a thread so
        # the event loop can run the other domains' async calls concurrently.
        return await asyncio.to_thread(
            get_broadband_core, lon=lon, lat=lat, radius_km=0.5, limit=100
        )
    except Exception as e:
        logger.error(f"Broadband API Error: {e}")
        return {"error": str(e), "results": []}


OVERPASS_MIRRORS = [
    TRANSPORTATION_APIS['OVERPASS_BASE'],
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


async def make_overpass_request(query: str) -> Dict[str, Any]:
    """Make Overpass API request, trying multiple mirrors on connection failure."""
    last_error = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for mirror in OVERPASS_MIRRORS:
            try:
                response = await client.post(
                    mirror,
                    data=query,
                    headers={
                        'User-Agent': API_CONFIG['USER_AGENT'],
                        'Content-Type': 'text/plain',
                    }
                )
                if response.is_success:
                    return response.json()
                last_error = f"Overpass {mirror} returned {response.status_code}"
                logger.warning(last_error)
            except (httpx.TimeoutException, httpx.RequestError) as e:
                last_error = f"Overpass {mirror}: {type(e).__name__}: {e}"
                logger.warning(last_error)
                continue

    logger.error(f"All Overpass mirrors failed. Last: {last_error}")
    return {"error": last_error, "elements": []}


async def get_transportation_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get comprehensive transportation data."""
    lat, lon = coordinates['lat'], coordinates['lon']
    search_radius = 25  # km
    
    query = f"""[out:json][timeout:60];
    (
      way(around:{search_radius * 1000},{lat},{lon})["highway"~"^(motorway|trunk|primary)$"];
      way(around:{search_radius * 1000},{lat},{lon})["railway"="rail"];
      node(around:{search_radius * 1000},{lat},{lon})["highway"="motorway_junction"];
      node(around:{search_radius * 1000},{lat},{lon})["railway"="station"];
      node(around:50000,{lat},{lon})["aeroway"="aerodrome"]["aerodrome:type"~"^(international|regional)$"];
      node(around:100000,{lat},{lon})["place"="city"]["harbour"="yes"];
    );
    out tags;"""
    
    return await make_overpass_request(query)


@cached_coordinate_query(precision=5, ttl=604800, namespace="transport_counts")
async def get_transportation_counts_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """
    Lightweight transport fetch for site scoring: returns only element COUNTS
    via Overpass `out count;` (no geometry, no tags), so the payload is a few
    bytes instead of ~9MB. Cached at a coarse geohash (~5km cells) since
    transport infrastructure is regional and shared across nearby grid points.
    """
    lat, lon = coordinates['lat'], coordinates['lon']
    radius_m = 25000  # matches get_transportation_data_raw way radius

    query = f"""[out:json][timeout:60];
    way(around:{radius_m},{lat},{lon})["highway"~"^(motorway|trunk|primary)$"];
    out count;
    way(around:{radius_m},{lat},{lon})["railway"="rail"];
    out count;
    """

    raw = await make_overpass_request(query)
    counts = [e for e in raw.get("elements", []) if e.get("type") == "count"]

    def _ways(count_el) -> int:
        try:
            return int(count_el.get("tags", {}).get("ways", 0))
        except (TypeError, ValueError):
            return 0

    return {
        "num_highways": _ways(counts[0]) if len(counts) > 0 else 0,
        "num_railways": _ways(counts[1]) if len(counts) > 1 else 0,
        "error": raw.get("error"),
    }


async def get_highway_data_raw(coordinates: Dict[str, float]) -> Dict[str, Any]:
    """Get highway access data."""
    lat, lon = coordinates['lat'], coordinates['lon']
    
    query = f"""[out:json][timeout:60];
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
    
    query = f"""[out:json][timeout:60];
    (
      way(around:100000,{lat},{lon})["railway"="rail"];
      node(around:100000,{lat},{lon})["railway"="station"];
      node(around:100000,{lat},{lon})["public_transport"="station"]["railway"];
    );
    out geom;"""
    
    return await make_overpass_request(query)

