"""
Main FastAPI application entry point.
Imports and registers all API routers.
"""
import logging
from typing import Any, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import S3_BLOCKS_GEO
from database import init_duckdb, con as db_connection
import database

# Import API routers
from api.geocoding import router as geocoding_router
from api.electricity import router as electricity_router
from api.transmission import router as transmission_router
from api.climate import router as climate_router
from api.water import router as water_router
from api.wind import router as wind_router
from api.broadband import router as broadband_router
from api.transportation import router as transportation_router
from api.features import router as features_router
from api.debug import router as debug_router

logger = logging.getLogger("uvicorn.error")


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI App Setup with Lifespan
# ──────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection and cache lifecycle."""
    try:
        database.con = init_duckdb()
        logger.info("✓ DuckDB initialized successfully")
        
        # Import cache after startup to load from disk
        from cache import _cache
        logger.info(f"✓ Cache initialized with {len(_cache)} entries")
        
        yield
    except Exception as e:
        logger.exception("Startup failed during DuckDB initialization")
        raise
    finally:
        # Save cache to disk on shutdown
        try:
            from cache import _save_cache_to_disk
            _save_cache_to_disk()
            logger.info("✓ Cache saved to disk")
        except Exception as e:
            logger.warning(f"Could not save cache on shutdown: {e}")
        
        if database.con is not None:
            try:
                database.con.close()
            except Exception:
                pass


app = FastAPI(
    title="Broadband Geo API",
    version="1.0",
    description="Query broadband data by geographic point using DuckDB",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Health Check Endpoint
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> Dict[str, Any]:
    """Health check endpoint."""
    if database.con is None:
        return {"ok": False, "error": "Database not initialized"}
    
    try:
        # Test that we can query S3
        database.con.execute(f"SELECT 1 FROM read_parquet('{S3_BLOCKS_GEO}') LIMIT 1").fetchone()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# Register API Routers
# ──────────────────────────────────────────────────────────────────────────────
app.include_router(geocoding_router, tags=["Geocoding"])
app.include_router(electricity_router, tags=["Electricity & Energy"])
app.include_router(transmission_router, tags=["Transmission Lines"])
app.include_router(climate_router, tags=["Climate & Weather"])
app.include_router(water_router, tags=["Water Resources"])
app.include_router(wind_router, tags=["Wind Energy"])
app.include_router(broadband_router, tags=["Broadband"])
app.include_router(transportation_router, tags=["Transportation"])
app.include_router(features_router, tags=["Site Features & Scoring"])
app.include_router(debug_router, tags=["Debug"])


# ──────────────────────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import requests

    requests.get("https://s3.us-east-1.amazonaws.com")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

