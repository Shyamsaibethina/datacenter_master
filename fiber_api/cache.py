"""
Geohash-based caching for coordinate queries.
Nearby coordinates map to the same cache key, maximizing cache hits.
Persists to disk to survive restarts.
"""
import time
import logging
import os
import pickle
from typing import Any, Optional, Dict
from functools import wraps
import hashlib
import json

logger = logging.getLogger("uvicorn.error")

# Cache file location
CACHE_FILE = "/tmp/geocache.pkl"
STATS_FILE = "/tmp/geocache_stats.json"

# Simple in-memory cache
_cache: Dict[str, tuple[Any, float]] = {}

# Cache statistics
_stats = {
    "hits": 0,
    "misses": 0,
    "evictions": 0
}

# Load cache from disk on startup
def _load_cache_from_disk():
    """Load cache and stats from disk if they exist."""
    global _cache, _stats
    
    # Load cache data
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                _cache = pickle.load(f)
            logger.info(f"Loaded {len(_cache)} cache entries from disk")
        except Exception as e:
            logger.warning(f"Could not load cache from disk: {e}")
            _cache = {}
    
    # Load stats
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                _stats = json.load(f)
            logger.info(f"Loaded cache stats from disk: {_stats}")
        except Exception as e:
            logger.warning(f"Could not load cache stats from disk: {e}")
            _stats = {"hits": 0, "misses": 0, "evictions": 0}

def _save_cache_to_disk():
    """Save cache and stats to disk."""
    try:
        # Save cache data
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(_cache, f)
        
        # Save stats
        with open(STATS_FILE, 'w') as f:
            json.dump(_stats, f)
            
        logger.debug(f"Saved {len(_cache)} cache entries to disk")
    except Exception as e:
        logger.warning(f"Could not save cache to disk: {e}")

# Load on module import
_load_cache_from_disk()


def geohash_encode(lat: float, lon: float, precision: int = 6) -> str:
    """
    Encode latitude/longitude to geohash.
    Pure Python implementation - no external dependencies.
    
    Precision levels:
    - 5: ~4.9 km cells (large area)
    - 6: ~1.2 km cells (good for most APIs)
    - 7: ~150 m cells (high resolution)
    - 8: ~19 m cells (very precise)
    """
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    
    lat_min, lat_max = -90.0, 90.0
    lon_min, lon_max = -180.0, 180.0
    
    geohash = []
    bits = 0
    bit = 0
    ch = 0
    
    while len(geohash) < precision:
        if bit % 2 == 0:  # even bit: longitude
            mid = (lon_min + lon_max) / 2
            if lon > mid:
                ch |= (1 << (4 - bits))
                lon_min = mid
            else:
                lon_max = mid
        else:  # odd bit: latitude
            mid = (lat_min + lat_max) / 2
            if lat > mid:
                ch |= (1 << (4 - bits))
                lat_min = mid
            else:
                lat_max = mid
        
        bits += 1
        if bits == 5:
            geohash.append(base32[ch])
            bits = 0
            ch = 0
        bit += 1
    
    return ''.join(geohash)


def cache_key(lat: float, lon: float, precision: int = 6, namespace: str = "") -> str:
    """
    Generate cache key from coordinates using geohash.
    
    Args:
        lat: Latitude
        lon: Longitude
        precision: Geohash precision (default 6 ≈ 1.2km cells)
        namespace: Optional namespace prefix for different cache types
    """
    gh = geohash_encode(lat, lon, precision)
    if namespace:
        return f"{namespace}:{gh}"
    return gh


def get_from_cache(key: str) -> Optional[Any]:
    """
    Retrieve value from cache if exists and not expired.
    """
    item = _cache.get(key)
    if not item:
        _stats["misses"] += 1
        return None
    
    value, expiry = item
    if time.time() > expiry:
        del _cache[key]
        _stats["evictions"] += 1
        _stats["misses"] += 1
        return None
    
    _stats["hits"] += 1
    return value


def set_cache(key: str, value: Any, ttl: int = 3600):
    """
    Store value in cache with TTL (time to live in seconds).
    Persists to disk every 10 entries.
    
    Args:
        key: Cache key
        value: Value to cache
        ttl: Time to live in seconds (default 3600 = 1 hour)
    """
    _cache[key] = (value, time.time() + ttl)
    
    # Persist to disk periodically (every 10 entries)
    if len(_cache) % 10 == 0:
        _save_cache_to_disk()


def clear_cache():
    """Clear all cached values and delete cache files."""
    _cache.clear()
    _stats["hits"] = 0
    _stats["misses"] = 0
    _stats["evictions"] = 0
    
    # Delete cache files
    try:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        if os.path.exists(STATS_FILE):
            os.remove(STATS_FILE)
    except Exception as e:
        logger.warning(f"Could not delete cache files: {e}")


def get_cache_stats() -> dict:
    """Get cache statistics."""
    total = _stats["hits"] + _stats["misses"]
    hit_rate = (_stats["hits"] / total * 100) if total > 0 else 0
    
    return {
        "size": len(_cache),
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "evictions": _stats["evictions"],
        "hit_rate_pct": round(hit_rate, 2)
    }


def cached_coordinate_query(precision: int = 6, ttl: int = 3600, namespace: str = ""):
    """
    Decorator for caching functions that take (lat, lon) coordinates.
    
    Usage:
        @cached_coordinate_query(precision=6, ttl=3600)
        async def my_api_call(coordinates: dict):
            # coordinates should have 'lat' and 'lon' keys
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(coordinates: dict, *args, **kwargs):
            lat = coordinates.get("lat")
            lon = coordinates.get("lon")
            
            if lat is None or lon is None:
                # No coordinates, skip cache
                return await func(coordinates, *args, **kwargs)
            
            # Generate cache key
            key = cache_key(lat, lon, precision, namespace or func.__name__)
            
            # Try to get from cache
            cached_value = get_from_cache(key)
            if cached_value is not None:
                logger.debug(f"Cache HIT for {func.__name__} at ({lat}, {lon}) -> {key}")
                return cached_value
            
            # Cache miss - call function
            logger.debug(f"Cache MISS for {func.__name__} at ({lat}, {lon}) -> {key}")
            result = await func(coordinates, *args, **kwargs)
            
            # Store in cache
            set_cache(key, result, ttl)
            
            return result
        
        return wrapper
    return decorator


def cached_feature_vector(precision: int = 6, ttl: int = 3600):
    """
    Specialized decorator for feature vector caching.
    Caches the entire feature computation result.
    """
    return cached_coordinate_query(precision=precision, ttl=ttl, namespace="features")

