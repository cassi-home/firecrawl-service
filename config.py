"""
Configuration constants and settings for the Firecrawl service.
"""
import os
from typing import Dict, Any

# ==================================================================================
# SERVICE CONFIGURATION
# ==================================================================================

# Service metadata
SERVICE_NAME = "firecrawl-service"
DEFAULT_PORT = 8000

# Credit limits and thresholds
MAX_CREDITS_PER_REQUEST = 10  # Conservative per-request limit
EXTRACTION_QUALITY_THRESHOLD = 25.0  # Minimum % of fields that must be filled
CACHE_EXPIRY_HOURS = 24

# Search limits
MAX_SEARCH_RESULTS = 3  # Reduced from 10 for credit conservation
MAX_URLS_FOR_VALIDATION = 1  # Single URL strategy
MAX_URLS_FOR_EXTRACTION = 2  # Primary + backup if needed

# ==================================================================================
# API ENDPOINTS EXCLUDED FROM MONITORING
# ==================================================================================

EXCLUDED_MONITORING_ENDPOINTS = [
    ".*admin.*", 
    "/metrics", 
    "/health", 
    "/credit_usage", 
    "/clear_cache"
]

# ==================================================================================
# PROMETHEUS METRICS CONFIGURATION
# ==================================================================================

METRICS_CONFIG = {
    "latency_buckets": (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    "should_group_status_codes": False,
    "should_ignore_untemplated": True,
    "should_respect_env_var": False,
    "should_instrument_requests_inprogress": True,
    "inprogress_name": "http_requests_inprogress",
    "inprogress_labels": True,
}

# ==================================================================================
# OPENTELEMETRY CONFIGURATION
# ==================================================================================

def get_otel_endpoint() -> str:
    """Get OpenTelemetry endpoint from environment or default."""
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

# ==================================================================================
# FIRECRAWL API CONFIGURATION
# ==================================================================================

def get_firecrawl_api_key() -> str:
    """Get Firecrawl API key from environment."""
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY environment variable is required")
    return api_key

# ==================================================================================
# SEARCH QUERY TEMPLATES
# ==================================================================================

SEARCH_QUERY_TEMPLATES = {
    "zillow": "{full_address} site:zillow.com homedetails",
    "redfin": "{full_address} site:redfin.com"
}

# URL validation patterns
URL_VALIDATION_PATTERNS = {
    "zillow": "zillow.com/homedetails/",
    "redfin_domain": "redfin.com", 
    "redfin_path": "/home/"
}

# ==================================================================================
# EXTRACTION SCHEMA FOR PROPERTY DATA
# ==================================================================================

PROPERTY_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "home_type": {
            "type": ["string", "null"],
            "description": "Property type: Single Family, Multi Family, Apartment, Townhouse, Condo, Duplex, Mobile/Manufactured, Land, or Other"
        },
        "heating_types": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Heating systems: Central, Forced Air, Baseboard, Radiant, Heat Pump, Gas, Electric, Oil, Solar, etc."
        },
        "cooling_types": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Cooling systems: Central Air, Window Units, Evaporative, Heat Pump, None, etc."
        },
        "interior_area_sqft": {
            "type": ["integer", "null"],
            "description": "Total finished square footage of interior living space"
        },
        "lot_size_sqft": {
            "type": ["integer", "null"],
            "description": "Lot size in square feet"
        },
        "bedrooms": {
            "type": ["integer", "null"],
            "description": "Number of bedrooms"
        },
        "bathrooms": {
            "type": ["number", "null"],
            "description": "Number of bathrooms (can be fractional like 2.5)"
        },
        "parking_options": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Parking: Garage, Carport, Driveway, Off-street, On-street, Covered, Uncovered, etc."
        },
        "year_built": {
            "type": ["integer", "null"],
            "description": "Year the property was constructed"
        },
        "finished_basement": {
            "type": ["boolean", "null"],
            "description": "Whether the basement is finished"
        },
        "has_patio": {
            "type": ["boolean", "null"],
            "description": "Whether property has a patio, deck, or outdoor space"
        },
        "flooring_types": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Flooring materials: Hardwood, Carpet, Tile, Laminate, Vinyl, etc."
        },
        "appliances_included": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Included appliances: Dishwasher, Refrigerator, Washer, Dryer, Microwave, etc."
        },
        "hoa_fee": {
            "type": ["number", "null"],
            "description": "Monthly HOA fee amount"
        },
        "property_tax": {
            "type": ["number", "null"],
            "description": "Annual property tax amount"
        }
    }
}

# ==================================================================================
# EXTRACTION PROMPT TEMPLATE
# ==================================================================================

EXTRACTION_PROMPT_TEMPLATE = """
You are extracting comprehensive property information for: {address}

Look for information in these specific sections commonly found on real estate websites:

**PROPERTY OVERVIEW & BASICS:**
- Property type: Look for "Property Type", "Home Type", or similar - extract Single Family, Condo, Townhouse, Apartment, etc.
- Bedrooms: Look for "Beds", "Bedrooms", or "BR" - extract the number
- Bathrooms: Look for "Baths", "Bathrooms", or "BA" - extract the number (including decimals like 2.5)
- Square footage: Look for "Sq Ft", "Square Feet", "Interior Area", "Living Area" - extract the number
- Lot size: Look for "Lot Size", "Land Area" - extract square footage
- Year built: Look for "Year Built", "Built in", "Construction Date"

**PROPERTY DETAILS & FEATURES:**
- Heating: Look in "Property Details", "Home Features", "Interior Features" for heating system info
- Cooling: Look for air conditioning, central air, cooling system details
- Flooring: Look for hardwood, carpet, tile, laminate, vinyl flooring types
- Appliances: Look for included appliances like dishwasher, refrigerator, washer/dryer
- Basement: Look for "Finished Basement", "Basement Features", or basement details
- Outdoor space: Look for patio, deck, balcony, outdoor features

**PARKING & UTILITIES:**
- Parking: Look for garage spaces, carport, driveway, parking details
- HOA fee: Look for "HOA", "Association Fee", "Monthly Fee"
- Property tax: Look for "Property Tax", "Annual Tax", "Tax Amount"

**SEARCH STRATEGY:**
1. First scan for property overview sections that show bed/bath/sqft
2. Look for detailed property information tables or lists
3. Check "Property Details", "Home Facts", "Features & Amenities" sections
4. Look for tax and fee information in financial sections
5. Scan listing descriptions for additional details

**DATA EXTRACTION RULES:**
- Extract exact numbers (don't round or estimate)
- For arrays, extract all applicable items found
- Use standard terminology (e.g., "Central Air" not "A/C")
- If multiple values exist, include all of them
- Return null only if information is truly not available
- Focus on factual data from structured sections, not subjective descriptions

Target websites: Zillow, Redfin, Realtor.com property pages and search results.
"""

# ==================================================================================
# CONSOLE COLORS FOR LOGGING
# ==================================================================================

class Colors:
    RED = "\033[31m"
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    WHITE = "\033[37m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"  # Reset to default
