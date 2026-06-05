"""
Transform raw API responses into structured Pydantic models.
"""
from typing import Dict, Any, List, Optional
from models import (
    Coordinates, BoundingBox,
    ElectricityPriceData, ElectricityPriceResponse,
    GeneratorData, GeneratorCapacityResponse,
    UtilityRate, UtilityRatesResponse,
    TransmissionLine, TransmissionLinesResponse,
    WeatherStation, WeatherAlert, HistoricalWeatherData, ClimateDataResponse,
    WaterMonitoringSite, WaterSiteType, WaterResourcesResponse,
    WindTurbine, WindTurbinesResponse,
    BroadbandProvider, CensusBlock, BroadbandResponse,
    TransportationFeature, TransportationType, TransportationResponse,
    HighwayAccessResponse, RailConnectivityResponse
)
import logging
from datetime import datetime

logger = logging.getLogger("uvicorn.error")


# ──────────────────────────────────────────────────────────────────────────────
# Electricity Transformers
# ──────────────────────────────────────────────────────────────────────────────

def transform_electricity_price(city: str, raw_data: Dict[str, Any]) -> ElectricityPriceResponse:
    """Transform raw EIA API response to ElectricityPriceResponse."""
    try:
        response = ElectricityPriceResponse(
            city=city,
            state=city.split(',')[-1].strip() if ',' in city else "",
            source="EIA_API"
        )
        
        if raw_data.get('response', {}).get('data'):
            data_points = []
            for item in raw_data['response']['data']:
                price_data = ElectricityPriceData(
                    period=item.get('period', ''),
                    state_id=item.get('stateid', ''),
                    state_name=item.get('stateDescription', ''),
                    sector=item.get('sectorName', 'Industrial'),
                    price=float(item.get('price', 0)),
                    sales=float(item.get('sales', 0)) if item.get('sales') else None,
                    revenue=float(item.get('revenue', 0)) if item.get('revenue') else None
                )
                data_points.append(price_data)
            
            if data_points:
                response.latest_price = data_points[0]
                response.historical_data = data_points
        
        return response
    except Exception as e:
        logger.error(f"Error transforming electricity price data: {e}")
        return ElectricityPriceResponse(
            city=city,
            state="",
            source="EIA_API",
            success=False,
            error=str(e)
        )


def transform_utility_rates(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> UtilityRatesResponse:
    """Transform raw OpenEI API response to UtilityRatesResponse."""
    try:
        response = UtilityRatesResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="OpenEI_API"
        )
        
        # Handle both list and dict responses from OpenEI API
        items = []
        if isinstance(raw_data, list):
            items = raw_data
        elif isinstance(raw_data, dict) and 'items' in raw_data:
            items = raw_data['items']
        elif isinstance(raw_data, dict) and 'result' in raw_data:
            items = raw_data['result']
        
        if items:
            rates = []
            for item in items:
                if isinstance(item, dict):
                    # Extract energy charge from energyratestructure safely
                    energy_charge = None
                    if item.get('energyratestructure') and len(item['energyratestructure']) > 0:
                        first_tier = item['energyratestructure'][0]
                        if isinstance(first_tier, list) and len(first_tier) > 0:
                            if isinstance(first_tier[0], dict) and 'rate' in first_tier[0]:
                                energy_charge = first_tier[0]['rate']
                    
                    # Extract demand charge from demandratestructure safely
                    demand_charge = None
                    if item.get('demandratestructure') and len(item['demandratestructure']) > 0:
                        first_tier = item['demandratestructure'][0]
                        if isinstance(first_tier, list) and len(first_tier) > 0:
                            if isinstance(first_tier[0], dict) and 'rate' in first_tier[0]:
                                demand_charge = first_tier[0]['rate']
                    
                    # Convert timestamps to readable dates
                    start_date = None
                    end_date = None
                    if item.get('startdate'):
                        try:
                            from datetime import datetime
                            start_date = datetime.fromtimestamp(item['startdate']).strftime('%Y-%m-%d')
                        except:
                            start_date = str(item['startdate'])
                    
                    if item.get('enddate'):
                        try:
                            from datetime import datetime
                            end_date = datetime.fromtimestamp(item['enddate']).strftime('%Y-%m-%d')
                        except:
                            end_date = str(item['enddate'])
                    
                    rate = UtilityRate(
                        utility_name=item.get('utility', 'Unknown'),
                        rate_name=item.get('name', 'Unknown Rate'),
                        sector=item.get('sector', 'Industrial'),
                        description=item.get('description'),
                        fixed_charge=float(item['fixedchargefirstmeter']) if item.get('fixedchargefirstmeter') else None,
                        demand_charge=demand_charge,
                        energy_charge=energy_charge,
                        minimum_charge=item.get('mincharge'),
                        effective_date=start_date,
                        end_date=end_date,
                        approved=item.get('approved', True),
                        uri=item.get('uri')
                    )
                    rates.append(rate)
            
            response.rates = rates
            response.count = len(rates)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming utility rates data: {e}")
        return UtilityRatesResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="OpenEI_API",
            success=False,
            error=str(e)
        )


def transform_generator_capacity(coordinates: Dict[str, float], state_id: str, raw_data: Dict[str, Any]) -> GeneratorCapacityResponse:
    """Transform raw EIA generator capacity API response."""
    try:
        radius_miles = raw_data.get('query', {}).get('radius_miles', 100)
        
        response = GeneratorCapacityResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            state=state_id,
            radius_miles=radius_miles,
            source="EIA_API"
        )
        
        if raw_data.get('response', {}).get('data'):
            generators = []
            total_capacity = 0
            
            for item in raw_data['response']['data']:
                capacity = float(item.get('nameplate-capacity-mw', 0))
                
                gen_data = GeneratorData(
                    period=item.get('period', ''),
                    state_id=item.get('stateid', ''),
                    state_name=item.get('stateDescription'),
                    plant_id=item.get('plantid'),
                    plant_name=item.get('plantName'),
                    generator_id=item.get('generatorid'),
                    technology=item.get('technology'),
                    energy_source=item.get('energy-source-code'),
                    prime_mover=item.get('prime-mover-code'),
                    nameplate_capacity_mw=capacity,
                    operating_year=item.get('operating-year-month'),
                    retirement_year=item.get('retirement-year-month'),
                    status=item.get('status'),
                    latitude=item.get('latitude'),
                    longitude=item.get('longitude'),
                    distance_km=item.get('distance_km'),
                    distance_miles=item.get('distance_miles')
                )
                generators.append(gen_data)
                total_capacity += capacity
            
            response.generators = generators
            response.count = len(generators)
            response.total_capacity_mw = round(total_capacity, 2)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming generator capacity data: {e}")
        return GeneratorCapacityResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            state=state_id,
            source="EIA_API",
            success=False,
            error=str(e)
        )


def transform_transmission_lines(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> TransmissionLinesResponse:
    """Transform raw transmission lines data to TransmissionLinesResponse."""
    try:
        response = TransmissionLinesResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            radius_km=raw_data.get('query', {}).get('radius_km', 5.0),
            source="Transmission_API"
        )
        
        if 'features' in raw_data:
            lines = []
            for feature in raw_data['features']:
                props = feature.get('properties', {})
                
                # Handle VOLTAGE: -999999 means unknown/not available
                voltage = props.get('VOLTAGE')
                voltage_kv = voltage if voltage and voltage != -999999 else None
                
                # Handle OWNER: "NOT AVAILABLE" means unknown
                owner = props.get('OWNER')
                owner = owner if owner and owner != "NOT AVAILABLE" else None
                
                line = TransmissionLine(
                    line_id=props.get('ID'),
                    voltage_kv=voltage_kv,
                    owner=owner,
                    status=props.get('STATUS'),
                    distance_km=props.get('distance_km', 0),
                    geometry=feature.get('geometry'),
                    properties=props
                )
                lines.append(line)
            
            response.lines = lines
            response.count = len(lines)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming transmission lines data: {e}")
        return TransmissionLinesResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Transmission_API",
            success=False,
            error=str(e)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Weather Transformers
# ──────────────────────────────────────────────────────────────────────────────

def transform_climate_data(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> ClimateDataResponse:
    """Transform Open-Meteo weather data to ClimateDataResponse."""
    try:
        response = ClimateDataResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Open-Meteo_API"
        )
        
        # Extract pre-calculated metrics
        metrics = raw_data.get('metrics', {})
        
        # Store summary with all the calculated metrics
        response.historical_summary = {
            "avg_temp_max_f": metrics.get('avg_temp_max_f'),
            "avg_temp_min_f": metrics.get('avg_temp_min_f'),
            "avg_precip_in": metrics.get('avg_precip_in'),
            "avg_wind_speed_mph": metrics.get('avg_wind_speed_mph'),
            "temp_variability_index": metrics.get('temp_variability_index'),
            "data_points": raw_data.get('data_points', 0)
        }
        
        # Note: Open-Meteo doesn't provide weather stations or alerts
        # Those features are removed in favor of direct historical data
        
        return response
    except Exception as e:
        logger.error(f"Error transforming climate data: {e}")
        return ClimateDataResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Open-Meteo_API",
            success=False,
            error=str(e)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Water Resources Transformers
# ──────────────────────────────────────────────────────────────────────────────

def transform_water_resources(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> WaterResourcesResponse:
    """Transform raw USGS water data to WaterResourcesResponse."""
    try:
        response = WaterResourcesResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="USGS_APIs"
        )
        
        # Process surface water sites
        if 'surface_water_sites' in raw_data and raw_data['surface_water_sites']:
            surface_sites = []
            for feature in raw_data['surface_water_sites'].get('features', []):
                props = feature.get('properties', {})
                geom = feature.get('geometry', {})
                coords = geom.get('coordinates', [0, 0])
                
                site = WaterMonitoringSite(
                    site_id=props.get('identifier', ''),
                    site_name=props.get('name', ''),
                    site_type=WaterSiteType.SURFACE,
                    coordinates=Coordinates(lat=coords[1], lon=coords[0]),
                    agency=props.get('agency', 'USGS'),
                    active=props.get('active', True),
                    parameters_monitored=props.get('parameters', []),
                    drainage_area_sq_mi=props.get('drainageArea')
                )
                surface_sites.append(site)
            response.surface_water_sites = surface_sites
        
        # Process groundwater sites
        if 'groundwater_sites' in raw_data and raw_data['groundwater_sites']:
            ground_sites = []
            for feature in raw_data['groundwater_sites'].get('features', []):
                props = feature.get('properties', {})
                geom = feature.get('geometry', {})
                coords = geom.get('coordinates', [0, 0])
                
                site = WaterMonitoringSite(
                    site_id=props.get('identifier', ''),
                    site_name=props.get('name', ''),
                    site_type=WaterSiteType.GROUNDWATER,
                    coordinates=Coordinates(lat=coords[1], lon=coords[0]),
                    agency=props.get('agency', 'USGS'),
                    active=props.get('active', True),
                    parameters_monitored=props.get('parameters', []),
                    well_depth_ft=props.get('wellDepth')
                )
                ground_sites.append(site)
            response.groundwater_sites = ground_sites
        
        response.total_sites = len(response.surface_water_sites) + len(response.groundwater_sites)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming water resources data: {e}")
        return WaterResourcesResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="USGS_APIs",
            success=False,
            error=str(e)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Wind Energy Transformers
# ──────────────────────────────────────────────────────────────────────────────

def transform_wind_turbines_state(city: str, raw_data: List[Dict[str, Any]]) -> WindTurbinesResponse:
    """Transform raw USGS wind turbine data (by state) to WindTurbinesResponse."""
    try:
        response = WindTurbinesResponse(
            location=city,
            source="USGS_Wind_API"
        )
        
        if isinstance(raw_data, list):
            turbines = []
            total_capacity = 0
            
            for item in raw_data:
                turbine = WindTurbine(
                    project_name=item.get('p_name'),
                    project_year=item.get('p_year'),
                    turbine_capacity_kw=float(item.get('t_cap', 0)) if item.get('t_cap') else None,
                    hub_height_m=float(item.get('t_hh', 0)) if item.get('t_hh') else None,
                    rotor_diameter_m=float(item.get('t_rd', 0)) if item.get('t_rd') else None,
                    total_height_m=float(item.get('t_ttlh', 0)) if item.get('t_ttlh') else None,
                    coordinates=Coordinates(
                        lat=float(item.get('ylat', 0)),
                        lon=float(item.get('xlong', 0))
                    ),
                    offshore=bool(item.get('t_offshore', False)),
                    confidence_level=item.get('t_conf_loc')
                )
                turbines.append(turbine)
                
                if turbine.turbine_capacity_kw:
                    total_capacity += turbine.turbine_capacity_kw / 1000  # Convert to MW
            
            response.turbines = turbines
            response.count = len(turbines)
            response.total_capacity_mw = round(total_capacity, 2)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming wind turbines data: {e}")
        return WindTurbinesResponse(
            location=city,
            source="USGS_Wind_API",
            success=False,
            error=str(e)
        )


def transform_wind_turbines_location(coordinates: Dict[str, float], raw_data: List[Dict[str, Any]]) -> WindTurbinesResponse:
    """Transform raw USGS wind turbine data (by location) to WindTurbinesResponse."""
    try:
        response = WindTurbinesResponse(
            location=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="USGS_Wind_API",
            search_radius_km=50  # Default from the function
        )
        
        if isinstance(raw_data, list):
            turbines = []
            total_capacity = 0
            
            for item in raw_data:
                turbine = WindTurbine(
                    project_name=item.get('p_name'),
                    project_year=item.get('p_year'),
                    turbine_capacity_kw=float(item.get('t_cap', 0)) if item.get('t_cap') else None,
                    hub_height_m=float(item.get('t_hh', 0)) if item.get('t_hh') else None,
                    rotor_diameter_m=float(item.get('t_rd', 0)) if item.get('t_rd') else None,
                    coordinates=Coordinates(
                        lat=float(item.get('ylat', 0)),
                        lon=float(item.get('xlong', 0))
                    ),
                    confidence_level=item.get('t_conf_loc')
                )
                
                # Calculate distance
                import math
                lat1, lon1 = coordinates['lat'], coordinates['lon']
                lat2, lon2 = turbine.coordinates.lat, turbine.coordinates.lon
                R = 6371  # Earth's radius in km
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                turbine.distance_km = round(R * c, 2)
                
                turbines.append(turbine)
                
                if turbine.turbine_capacity_kw:
                    total_capacity += turbine.turbine_capacity_kw / 1000  # Convert to MW
            
            response.turbines = sorted(turbines, key=lambda x: x.distance_km or float('inf'))
            response.count = len(turbines)
            response.total_capacity_mw = round(total_capacity, 2)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming wind turbines location data: {e}")
        return WindTurbinesResponse(
            location=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="USGS_Wind_API",
            success=False,
            error=str(e)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Broadband Transformers
# ──────────────────────────────────────────────────────────────────────────────

def transform_broadband_data(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> BroadbandResponse:
    """Transform raw broadband data to BroadbandResponse."""
    try:
        response = BroadbandResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            radius_km=raw_data.get('radius_km', 0.5),
            source="Broadband_API"
        )
        
        if 'results' in raw_data:
            # Group by census block
            blocks_map = {}
            all_providers = set()
            fiber_providers = set()
            max_down = 0
            max_up = 0
            
            for result in raw_data['results']:
                block_id = result.get('block_geoid', '')
                if block_id not in blocks_map:
                    blocks_map[block_id] = CensusBlock(
                        block_geoid=block_id,
                        distance_km=result.get('distance_km', 0),
                        providers=[]
                    )
                
                # Create provider
                provider = BroadbandProvider(
                    provider_id=result.get('frn'),
                    provider_name=result.get('provider', 'Unknown'),
                    technology='Fiber' if result.get('tech_code') == 50 else 'Unknown',
                    max_download_speed_mbps=float(result.get('max_down', 0) or 0),
                    max_upload_speed_mbps=float(result.get('max_up', 0) or 0),
                    low_latency=result.get('low_latency') == '1' or result.get('low_latency') == 1,
                    business_service=result.get('biz_res') in ['B', 'X'],
                    consumer_service=result.get('biz_res') in ['R', 'X']
                )
                
                blocks_map[block_id].providers.append(provider)
                all_providers.add(provider.provider_name)
                
                # Track fiber
                if 'fiber' in provider.technology.lower():
                    blocks_map[block_id].fiber_available = True
                    fiber_providers.add(provider.provider_name)
                    if provider.business_service:
                        blocks_map[block_id].business_fiber_available = True
                
                # Track max speeds
                if provider.max_download_speed_mbps > max_down:
                    max_down = provider.max_download_speed_mbps
                if provider.max_upload_speed_mbps > max_up:
                    max_up = provider.max_upload_speed_mbps
                
                # Update block max speeds
                if not blocks_map[block_id].max_download_available or provider.max_download_speed_mbps > blocks_map[block_id].max_download_available:
                    blocks_map[block_id].max_download_available = provider.max_download_speed_mbps
                if not blocks_map[block_id].max_upload_available or provider.max_upload_speed_mbps > blocks_map[block_id].max_upload_available:
                    blocks_map[block_id].max_upload_available = provider.max_upload_speed_mbps
            
            response.census_blocks = sorted(blocks_map.values(), key=lambda x: x.distance_km)
            response.unique_providers = sorted(list(all_providers))
            response.fiber_providers = sorted(list(fiber_providers))
            response.max_speeds = {
                "download_mbps": max_down,
                "upload_mbps": max_up
            }
            response.blocks_searched = raw_data.get('candidates_checked', len(blocks_map))
            response.blocks_with_service = len(blocks_map)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming broadband data: {e}")
        return BroadbandResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Broadband_API",
            success=False,
            error=str(e)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Transportation Transformers
# ──────────────────────────────────────────────────────────────────────────────

def transform_transportation_data(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> TransportationResponse:
    """Transform raw Overpass API data to TransportationResponse."""
    try:
        response = TransportationResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            search_radius_km=25,  # Default from the function
            source="Overpass_API"
        )
        
        if 'elements' in raw_data:
            for element in raw_data['elements']:
                tags = element.get('tags', {})
                
                # Skip elements that don't have recognizable transportation tags
                if not any(key in tags for key in ['highway', 'railway', 'aeroway', 'harbour']):
                    continue
                
                # Determine feature type first
                feature_type = None
                if 'highway' in tags:
                    if tags['highway'] == 'motorway_junction':
                        feature_type = TransportationType.JUNCTION
                    else:
                        feature_type = TransportationType.HIGHWAY
                elif 'railway' in tags:
                    feature_type = TransportationType.RAILWAY
                elif 'aeroway' in tags and tags['aeroway'] == 'aerodrome':
                    feature_type = TransportationType.AIRPORT
                elif 'harbour' in tags and tags.get('harbour') == 'yes':
                    feature_type = TransportationType.PORT
                
                # Skip if we couldn't determine the feature type
                if not feature_type:
                    continue
                
                # Create feature with required feature_type
                feature = TransportationFeature(
                    osm_id=str(element.get('id', '')),
                    feature_type=feature_type,
                    tags=tags
                )
                
                # Set geometry if available
                if 'geometry' in element:
                    feature.geometry = {
                        "type": "LineString",
                        "coordinates": [[pt['lon'], pt['lat']] for pt in element['geometry']]
                    }
                elif 'lat' in element and 'lon' in element:
                    feature.geometry = {
                        "type": "Point",
                        "coordinates": [element['lon'], element['lat']]
                    }
                
                # Set additional properties and add to appropriate list
                feature.name = tags.get('name')
                feature.ref = tags.get('ref')
                
                if feature.feature_type == TransportationType.HIGHWAY:
                    feature.classification = tags['highway']
                    if tags['highway'] in ['motorway', 'trunk', 'primary']:
                        response.highways.append(feature)
                
                elif feature.feature_type == TransportationType.JUNCTION:
                    feature.classification = tags['highway']
                    response.highway_junctions.append(feature)
                
                elif feature.feature_type == TransportationType.RAILWAY:
                    feature.classification = tags['railway']
                    if tags['railway'] == 'rail':
                        response.railways.append(feature)
                    elif tags['railway'] == 'station':
                        response.rail_stations.append(feature)
                
                elif feature.feature_type == TransportationType.AIRPORT:
                    feature.classification = tags.get('aerodrome:type', 'unknown')
                    response.airports.append(feature)
                
                elif feature.feature_type == TransportationType.PORT:
                    response.ports.append(feature)
        
        response.total_features = (
            len(response.highways) + len(response.railways) + 
            len(response.airports) + len(response.ports) +
            len(response.highway_junctions) + len(response.rail_stations)
        )
        
        return response
    except Exception as e:
        logger.error(f"Error transforming transportation data: {e}")
        return TransportationResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            search_radius_km=25,
            source="Overpass_API",
            success=False,
            error=str(e)
        )


def transform_highway_access(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> HighwayAccessResponse:
    """Transform raw Overpass API highway data to HighwayAccessResponse."""
    try:
        response = HighwayAccessResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Overpass_API"
        )
        
        if 'elements' in raw_data:
            for element in raw_data['elements']:
                tags = element.get('tags', {})
                
                # Determine feature type
                feature_type = TransportationType.JUNCTION if tags.get('highway') == 'motorway_junction' else TransportationType.HIGHWAY
                
                feature = TransportationFeature(
                    osm_id=str(element.get('id', '')),
                    feature_type=feature_type,
                    name=tags.get('name'),
                    ref=tags.get('ref'),
                    tags=tags
                )
                
                # Set geometry
                if 'geometry' in element:
                    feature.geometry = {
                        "type": "LineString",
                        "coordinates": [[pt['lon'], pt['lat']] for pt in element['geometry']]
                    }
                elif 'lat' in element and 'lon' in element:
                    feature.geometry = {
                        "type": "Point",
                        "coordinates": [element['lon'], element['lat']]
                    }
                
                # Classify
                if 'highway' in tags:
                    feature.classification = tags['highway']
                    
                    if tags['highway'] == 'motorway':
                        response.motorways.append(feature)
                    elif tags['highway'] == 'trunk':
                        response.trunk_roads.append(feature)
                    elif tags['highway'] == 'motorway_junction':
                        feature.feature_type = TransportationType.JUNCTION
                        response.junctions.append(feature)
        
        response.total_features = len(response.motorways) + len(response.trunk_roads) + len(response.junctions)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming highway access data: {e}")
        return HighwayAccessResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Overpass_API",
            success=False,
            error=str(e)
        )


def transform_rail_connectivity(coordinates: Dict[str, float], raw_data: Dict[str, Any]) -> RailConnectivityResponse:
    """Transform raw Overpass API rail data to RailConnectivityResponse."""
    try:
        response = RailConnectivityResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Overpass_API"
        )
        
        if 'elements' in raw_data:
            for element in raw_data['elements']:
                tags = element.get('tags', {})
                
                feature = TransportationFeature(
                    osm_id=str(element.get('id', '')),
                    feature_type=TransportationType.RAILWAY,
                    name=tags.get('name'),
                    tags=tags
                )
                
                # Set geometry
                if 'geometry' in element:
                    feature.geometry = {
                        "type": "LineString",
                        "coordinates": [[pt['lon'], pt['lat']] for pt in element['geometry']]
                    }
                elif 'lat' in element and 'lon' in element:
                    feature.geometry = {
                        "type": "Point",
                        "coordinates": [element['lon'], element['lat']]
                    }
                
                # Classify
                if 'railway' in tags:
                    feature.classification = tags['railway']
                    
                    if tags['railway'] == 'rail':
                        response.rail_lines.append(feature)
                        # Check if it's freight capable
                        if tags.get('usage') in ['freight', 'main', 'branch'] or tags.get('service') == 'freight':
                            response.freight_capable = True
                    elif tags['railway'] == 'station' or (tags.get('public_transport') == 'station'):
                        response.stations.append(feature)
        
        response.total_features = len(response.rail_lines) + len(response.stations)
        
        return response
    except Exception as e:
        logger.error(f"Error transforming rail connectivity data: {e}")
        return RailConnectivityResponse(
            coordinates=Coordinates(lat=coordinates['lat'], lon=coordinates['lon']),
            source="Overpass_API",
            success=False,
            error=str(e)
        )
