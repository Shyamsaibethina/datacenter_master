"""
Debug API endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from config import S3_BLOCKS_GEO, S3_BLOCKS_GLOB
from database import con

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.get("/debug/s3-access")
async def debug_s3():
    """Test S3 access using boto3."""
    try:
        import boto3
        s3 = boto3.client('s3')
        response = s3.head_object(Bucket='broadbandinfo', Key='fiber/census_blocks/FL.parquet')
        return {"status": "success", "metadata": response}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/debug/geo_sample")
def debug_geo_sample(limit: int = Query(5, ge=1, le=100)):
    """Debug endpoint to check what's in the geo parquet files."""
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


@router.get("/debug/broadband_sample")
def debug_broadband_sample(limit: int = Query(5, ge=1, le=100)):
    """Debug endpoint to check what's in the broadband parquet files."""
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


@router.get("/debug/bbox_check")
def debug_bbox_check(
    lon: float = Query(..., description="Longitude"),
    lat: float = Query(..., description="Latitude"),
    radius_km: float = Query(1.0, description="Radius in km")
):
    """Debug endpoint to check bbox filtering."""
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

