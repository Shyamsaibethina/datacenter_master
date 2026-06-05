"""
DuckDB initialization and core database query functions.
"""
import logging
import os
import threading
import time
from typing import Dict, Any, Optional, List
import duckdb
from fastapi import HTTPException

from config import (
    AWS_REGION, S3_BLOCKS_GEO, S3_GEO_BUCKET, S3_GEO_PREFIX,
    S3_BROADBAND_BUCKET, S3_BROADBAND_PREFIX, STATE_BOUNDS
)
from utils import get_candidate_states

logger = logging.getLogger("uvicorn.error")

# Global DuckDB connection
con = None

# ──────────────────────────────────────────────────────────────────────────────
# Local parquet cache
#
# Reading per-state parquet files directly from S3 over httpfs is the main
# source of slowness/timeouts (each query range-reads a 300MB+ geometry file).
# We mirror files to local disk on first use so DuckDB reads them locally
# afterwards. Big geometry files are capped with LRU eviction so we never
# exhaust the (tight) local disk.
# ──────────────────────────────────────────────────────────────────────────────
LOCAL_DATA_DIR = os.environ.get(
    "LOCAL_DATA_DIR", os.path.join(os.path.dirname(__file__), "data_cache")
)
# Hard cap for the large census-block geometry cache (LRU eviction beyond this).
GEO_CACHE_MAX_BYTES = int(os.environ.get("GEO_CACHE_MAX_BYTES", 3 * 1024 ** 3))  # 3 GB

_download_lock = threading.Lock()
_s3_client = None


def _get_s3():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3", region_name=AWS_REGION)
    return _s3_client


def _dir_size_and_files(root: str):
    """Return (total_bytes, [(atime, size, path), ...]) for files under root."""
    total = 0
    files = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith(".part"):
                continue
            p = os.path.join(dirpath, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            total += st.st_size
            files.append((st.st_atime, st.st_size, p))
    return total, files


def _evict_lru(cap_bytes: int, incoming_bytes: int):
    """Evict least-recently-used cached files until incoming bytes will fit under cap."""
    total, files = _dir_size_and_files(LOCAL_DATA_DIR)
    if total + incoming_bytes <= cap_bytes:
        return
    files.sort(key=lambda f: f[0])  # oldest atime first
    for _, size, path in files:
        if total + incoming_bytes <= cap_bytes:
            break
        try:
            os.remove(path)
            total -= size
            logger.info(f"Evicted local cache file (LRU): {path}")
        except OSError:
            pass


def ensure_local_parquet(bucket: str, key: str, cap_bytes: Optional[int] = None) -> str:
    """
    Ensure s3://bucket/key is mirrored locally; return the local file path.
    Downloads once (thread-safe), bumps atime on hits for LRU, and enforces an
    optional size cap (used for the large geometry files only).
    """
    local_path = os.path.join(LOCAL_DATA_DIR, bucket, key)

    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        try:
            os.utime(local_path, None)  # mark recently used
        except OSError:
            pass
        return local_path

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    with _download_lock:
        # Re-check inside the lock in case another thread just fetched it.
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return local_path

        s3 = _get_s3()
        size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
        if cap_bytes:
            _evict_lru(cap_bytes, size)

        tmp_path = local_path + ".part"
        logger.info(f"Downloading s3://{bucket}/{key} ({size / 1e6:.1f} MB) -> local cache")
        t0 = time.time()
        s3.download_file(bucket, key, tmp_path)
        os.replace(tmp_path, local_path)
        logger.info(f"Cached s3://{bucket}/{key} locally in {time.time() - t0:.1f}s")

    return local_path


def init_duckdb():
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


def get_broadband_core(lon: float, lat: float, radius_km: float = 0.5, 
                       min_download: Optional[float] = None, min_upload: Optional[float] = None, 
                       limit: int = 100) -> Dict[str, Any]:
    """Core broadband logic without FastAPI dependencies."""
    global con
    
    if con is None:
        raise HTTPException(503, "Database not initialized")
    
    # A single DuckDB connection is not thread-safe for concurrent queries.
    # Since this runs in a worker thread (asyncio.to_thread), use a dedicated
    # cursor so parallel broadband/transmission queries don't collide.
    cursor = con.cursor()
    
    # Validate coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise HTTPException(400, f"Invalid coordinates: lon={lon}, lat={lat}")
    
    logger.info(f"Query: point=({lon}, {lat}), radius={radius_km}km, min_down={min_download}, min_up={min_upload}")
    
    try:
        start_time = time.time()
        
        # Phase 0: Determine which state contains the point
        all_candidates = get_candidate_states(lon, lat, buffer_deg=0.0)
        candidate_states = [all_candidates[0]] if all_candidates else []
        
        # Calculate degree buffer for spatial queries within the state
        deg_buffer = radius_km / 111.0
        
        if not candidate_states:
            logger.warning(f"No candidate states for point ({lon}, {lat})")
            return {
                "point": {"lon": lon, "lat": lat},
                "radius_km": radius_km,
                "results": [],
                "method": "state_filter",
                "message": "Point outside known US boundaries"
            }
        
        # Mirror the (large) geometry parquet locally on first use, capped + LRU.
        state_paths = [
            ensure_local_parquet(S3_GEO_BUCKET, f"{S3_GEO_PREFIX}{state}.parquet", cap_bytes=GEO_CACHE_MAX_BYTES)
            for state in candidate_states
        ]
        logger.info(f"Scanning states: {candidate_states}")
        
        # Phase 1: Fast bbox filter
        bbox_sql = f"""
        SELECT block_geoid
        FROM read_parquet([{','.join([f"'{p}'" for p in state_paths])}], union_by_name=true)
        WHERE ? BETWEEN minx - ? AND maxx + ?
          AND ? BETWEEN miny - ? AND maxy + ?
        LIMIT 500
        """
        
        bbox_result = cursor.execute(
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
        
        # Phase 2: Exact spatial check
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
        
        spatial_result = cursor.execute(
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
        
        # Broadband attribute files are small (<40MB) — mirror locally, no cap needed.
        broadband_paths = [
            ensure_local_parquet(S3_BROADBAND_BUCKET, f"{S3_BROADBAND_PREFIX}{state}.parquet")
            for state in candidate_states
        ]
        
        # Build filter conditions
        where_clauses = ["b.block_geoid IN ({})".format(
            ",".join([f"'{g}'" for g in matching_geoids])
        )]
        
        if min_download is not None:
            where_clauses.append(f"b.max_down >= {min_download}")
        if min_upload is not None:
            where_clauses.append(f"b.max_up >= {min_upload}")
        
        where_sql = " AND ".join(where_clauses)
        
        broadband_sql = f"""
        SELECT *
        FROM read_parquet([{','.join([f"'{p}'" for p in broadband_paths])}], union_by_name=true) b
        WHERE {where_sql}
        LIMIT {int(limit)}
        """
        
        broadband_time_start = time.time()
        cur = cursor.execute(broadband_sql)
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
        logger.info(f"Returning {len(results)} broadband records in {total_time:.2f}s total")
        
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


def get_transmission_lines_core(lon: float, lat: float, radius_km: float = 5.0, limit: int = 100) -> Dict[str, Any]:
    """Core transmission lines logic without FastAPI dependencies."""
    global con
    
    if con is None:
        raise HTTPException(503, "Database not initialized")
    
    # Thread-local cursor (see note in get_broadband_core) for safe concurrent use.
    cursor = con.cursor()
    
    # Validate coordinates
    if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise HTTPException(400, f"Invalid coordinates: lon={lon}, lat={lat}")
    
    logger.info(f"Transmission query: point=({lon}, {lat}), radius={radius_km}km")
    
    try:
        start_time = time.time()
        
        # Determine which state contains the point
        all_candidates = get_candidate_states(lon, lat, buffer_deg=0.0)
        candidate_states = [all_candidates[0]] if all_candidates else []
        
        # Calculate degree buffer for spatial queries
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
        
        # Get state bounding boxes for filtering
        state_bounds_filter = []
        for state in candidate_states:
            if state in STATE_BOUNDS:
                minx, miny, maxx, maxy = STATE_BOUNDS[state]
                state_bounds_filter.append(f"(minx <= {maxx} AND maxx >= {minx} AND miny <= {maxy} AND maxy >= {miny})")
        
        state_bounds_sql = " OR ".join(state_bounds_filter) if state_bounds_filter else "TRUE"

        # 47MB single file — mirror locally once, then read from disk.
        transmission_path = ensure_local_parquet("transmissioninfo", "resilience_power.parquet")

        query_sql = f"""
        SELECT 
            * EXCLUDE (geom, minx, miny, maxx, maxy),
            ST_AsGeoJSON(geom) as geometry_json,
            ST_Distance(geom, ST_Point(?, ?)) * 111.0 as distance_km
        FROM read_parquet('{transmission_path}')
        WHERE ({state_bounds_sql})
          AND minx <= ? + ? AND maxx >= ? - ?
          AND miny <= ? + ? AND maxy >= ? - ?
          AND ST_DWithin(geom, ST_Point(?, ?), ?)
        ORDER BY distance_km
        LIMIT ?
        """
        
        results_cursor = cursor.execute(
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


def get_all_transmission_geojson(simplify: float = 0.03) -> Dict[str, Any]:
    """All US transmission lines as a simplified GeoJSON FeatureCollection."""
    global con
    if con is None:
        raise HTTPException(503, "Database not initialized")

    import json
    cursor = con.cursor()
    transmission_path = ensure_local_parquet("transmissioninfo", "resilience_power.parquet")
    start = time.time()

    rows = cursor.execute(
        f"""
        SELECT
            ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, ?)) AS geometry_json,
            VOLTAGE, OWNER, VOLT_CLASS
        FROM read_parquet('{transmission_path}')
        WHERE geom IS NOT NULL
        """,
        [simplify],
    ).fetchall()

    features = []
    for geom_json, voltage, owner, volt_class in rows:
        if not geom_json:
            continue
        features.append({
            "type": "Feature",
            "geometry": json.loads(geom_json),
            "properties": {
                "VOLTAGE": voltage,
                "OWNER": owner,
                "VOLT_CLASS": volt_class,
            },
        })

    elapsed = time.time() - start
    logger.info(f"Built transmission overlay: {len(features)} lines in {elapsed:.1f}s")
    return {"type": "FeatureCollection", "count": len(features), "features": features}

