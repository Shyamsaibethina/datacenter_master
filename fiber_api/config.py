"""
Configuration constants, API keys, and state mappings.
"""
import os

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

# ──────────────────────────────────────────────────────────────────────────────
# API Configuration and Keys
# ──────────────────────────────────────────────────────────────────────────────
API_CONFIG = {
    "USER_AGENT": "DatacenterMCP/1.0 (contact@datacenter-planning.com)",
    "EIA_API_KEY": "B2BcRsfRYupoKyjyMrGiN62clJsKumSuB1R5uKCY",
    "NOAA_CDO_TOKEN": "FqpipxmwolxLAMVeTEAkxREnKoVZuUpX",
    "USGS_API_KEY": "c1Sg9HqhwKgPKKaG6SsYJKTLGfdZ3YGGGz26wW8Y",
    "OPENEI_API_KEY": "FhosGzYJcpbsbFRH2O0KXY1dJq2vfAbsEGRp2PB3"
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

TRANSPORTATION_APIS = {
    "OVERPASS_BASE": "https://overpass-api.de/api/interpreter"
}

# ──────────────────────────────────────────────────────────────────────────────
# State Mappings
# ──────────────────────────────────────────────────────────────────────────────
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

# State bounding boxes for fast state lookup
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

