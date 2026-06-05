"""
Utility functions for data sanitization, normalization, and state lookups.
"""
from typing import List, Optional
import numpy as np
import httpx
import logging
from config import STATE_BOUNDS, API_CONFIG

logger = logging.getLogger("uvicorn.error")


def normalize_us_lon(lon: float) -> float:
    """Normalize longitude for US coordinates (ensure negative for continental US)."""
    if lon > 0 and lon < 180:
        return -lon
    return lon


def create_bbox(lat: float, lon: float, radius_deg: float) -> str:
    """Create bbox string for API requests."""
    return f"{lon-radius_deg},{lat-radius_deg},{lon+radius_deg},{lat+radius_deg}"


def reverse_geocode_state(lat: float, lon: float) -> Optional[str]:
    """Use Nominatim reverse geocoding to determine state from coordinates."""
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        
        # Nominatim requires a User-Agent
        headers = {'User-Agent': API_CONFIG.get('USER_AGENT', 'DatacenterAPI/1.0')}
        
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                address = data.get('address', {})
                state_name = address.get('state', '')
                
                # Map state name to abbreviation
                state_map = {v: k for k, v in {
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
                }.items()}
                
                state_abbrev = state_map.get(state_name.lower())
                if state_abbrev:
                    logger.info(f"Reverse geocoded ({lat}, {lon}) -> {state_abbrev} via Nominatim")
                    return state_abbrev
    except Exception as e:
        logger.warning(f"Reverse geocoding failed for ({lat}, {lon}): {e}")
    
    return None


def get_candidate_states(lon: float, lat: float, buffer_deg: float = 0.5) -> List[str]:
    """Get list of states that could contain the point. Uses reverse geocoding for ambiguous cases."""
    exact_matches = []
    buffered_matches = []
    
    for state, (minx, miny, maxx, maxy) in STATE_BOUNDS.items():
        # Check if point is exactly within state bounds (no buffer)
        if (minx <= lon <= maxx and miny <= lat <= maxy):
            # Calculate how centered the point is
            dist_to_west = abs(lon - minx)
            dist_to_east = abs(lon - maxx)
            dist_to_south = abs(lat - miny)
            dist_to_north = abs(lat - maxy)
            min_edge_distance = min(dist_to_west, dist_to_east, dist_to_south, dist_to_north)
            exact_matches.append((state, min_edge_distance))
        # Check with buffer for nearby states
        elif (minx - buffer_deg <= lon <= maxx + buffer_deg and 
              miny - buffer_deg <= lat <= maxy + buffer_deg):
            dist_to_west = abs(lon - minx)
            dist_to_east = abs(lon - maxx)
            dist_to_south = abs(lat - miny)
            dist_to_north = abs(lat - maxy)
            min_edge_distance = min(dist_to_west, dist_to_east, dist_to_south, dist_to_north)
            buffered_matches.append((state, min_edge_distance))
    
    # If multiple exact matches OR very close to edge, use reverse geocoding
    if len(exact_matches) > 1:
        distances = [dist for _, dist in exact_matches]
        max_dist = max(distances)
        min_dist = min(distances)
        # Ambiguous if: distances similar OR any state is very close to edge
        is_ambiguous = (max_dist - min_dist) < 2.0 or min_dist < 0.5
        
        if is_ambiguous:
            logger.info(f"Ambiguous/border case for ({lat}, {lon}), using reverse geocoding")
            geocoded_state = reverse_geocode_state(lat, lon)
            if geocoded_state:
                # Put geocoded state first
                other_states = [s for s, _ in exact_matches if s != geocoded_state]
                return [geocoded_state] + other_states
    
    # Sort by distance from edge (larger = more centered, better)
    exact_matches.sort(key=lambda x: x[1], reverse=True)
    buffered_matches.sort(key=lambda x: x[1], reverse=True)
    
    # Prioritize exact matches, then buffered matches
    result = [state for state, _ in exact_matches] + [state for state, _ in buffered_matches]
    return result


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


def sanitize_float(value):
    """Convert inf/NaN to None for JSON compliance."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if not np.isfinite(value):  # catches inf, -inf, nan
            return None
    return value


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


def safe_float(val):
    """Safely convert value to float, returning None on error."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

