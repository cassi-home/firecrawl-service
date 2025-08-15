# Firecrawl Home Information Service

A high-performance FastAPI service that extracts comprehensive home information from real estate websites using Firecrawl's search and extract APIs. Features revolutionary dual-layer caching for 287x speed improvements and zero-credit repeat requests.

**🚀 Key Highlights:**
- **Sub-second responses** for cached properties (<60ms vs 16+ seconds)
- **Zero credits used** on cache hits (massive cost savings)
- **2-9 credits per fresh search** (vs 60+ before optimization)
- **24-hour intelligent caching** with automatic expiry
- **Production-ready** with comprehensive monitoring and Railway deployment

## Features

- **🚀 Dual-Layer Caching System**: Revolutionary caching of both URL discovery AND extraction results
  - **URL Discovery Cache**: Instant property URL lookup (0 search credits)
  - **Extraction Results Cache**: Complete property data cache (0 extraction credits)
  - **287x Speed Improvement**: Repeat requests in <60ms vs 16+ seconds
- **Dynamic Property Discovery**: Uses Firecrawl search API to find property URLs across Zillow and Redfin
- **Smart Early Exit Strategy**: Searches Zillow first, only searches Redfin if Zillow fails
- **Intelligent URL Validation**: Ensures exact address matching to avoid wrong properties
- **Comprehensive Data Extraction**: Extracts 15+ property fields including financial and structural details
- **Credit-Optimized Performance**: Aggressive credit conservation with 10-credit budget per request
- **Quality-Based Backup Search**: Only searches second domain if extraction quality < 25%
- **Structured JSON Output**: Clean, typed responses with comprehensive property information
- **Comprehensive Monitoring**: OpenTelemetry tracing, Prometheus metrics, and cache analytics
- **Railway Deployment Ready**: Containerized and production-ready with 120s timeout support

## Comprehensive Property Information Extracted

### **Basic Property Details**
- **Property Type**: Single Family, Multi Family, Apartment, Townhouse, Condo, Duplex, Mobile/Manufactured, Land, Other
- **Bedrooms**: Number of bedrooms
- **Bathrooms**: Number of bathrooms (supports fractional like 2.5)
- **Year Built**: Construction year
- **Interior Area**: Total finished square footage
- **Lot Size**: Property lot size in square feet

### **Systems & Features**
- **Heating Systems**: Central, Forced Air, Baseboard, Radiant, Heat Pump, Gas, Electric, Oil, Solar, etc.
- **Cooling Systems**: Central Air, Window Units, Evaporative, Heat Pump, None, etc.
- **Parking Options**: Garage (Attached/Detached), Carport, Driveway, Off-street, On-street, Covered, Uncovered
- **Flooring Types**: Hardwood, Carpet, Tile, Laminate, Vinyl, etc.
- **Appliances Included**: Dishwasher, Refrigerator, Washer, Dryer, Microwave, Range/Oven, Disposal, etc.

### **Structural & Outdoor Features**
- **Finished Basement**: Whether basement is finished
- **Patio/Deck**: Whether property has outdoor living space

### **Financial Information**
- **HOA Fees**: Monthly homeowners association fees
- **Property Taxes**: Annual property tax amounts

## Environment Variables

- `FIRECRAWL_API_KEY`: Your Firecrawl API key
- `PORT`: Port to run the service on (default: 8000)
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OpenTelemetry endpoint for tracing

## API Endpoints

### POST /extract_home_info
Extract comprehensive home information for a given address (complete end-to-end flow).

**Request Body:**
```json
{
  "address": "2679 Castle Butte Dr",
  "city": "Castle Rock",
  "state": "CO",
  "zip_code": "80109"
}
```

**Response:**
```json
{
  "address": "2679 Castle Butte Dr, Castle Rock, CO 80109",
  "property_info": {
    "home_type": "Single Family",
    "heating_types": ["Forced Air"],
    "cooling_types": ["Central"],
    "interior_area_sqft": 5760,
    "lot_size_sqft": 196020,
    "bedrooms": 5,
    "bathrooms": 6,
    "parking_options": ["Garage - Attached", "Garage - Detached"],
    "year_built": 2002,
    "finished_basement": true,
    "has_patio": true,
    "flooring_types": ["Tile", "Carpet", "Hardwood"],
    "appliances_included": ["Dishwasher", "Refrigerator", "Microwave", "Disposal", "Washer", "Dryer"],
    "hoa_fee": null,
    "property_tax": 8828
  },
  "sources": ["zillow.com", "redfin.com"],
  "success": true,
  "error_message": null
}
```

### POST /find_property_urls
Discover property URLs from Zillow and Redfin using Firecrawl search (Step 1 of 2-step process).

**Request Body:**
```json
{
  "address": "2679 Castle Butte Dr",
  "city": "Castle Rock",
  "state": "CO",
  "zip_code": "80109"
}
```

**Response:**
```json
{
  "address": "2679 Castle Butte Dr, Castle Rock, CO 80109",
  "found_urls": {
    "zillow": ["https://www.zillow.com/homedetails/2679-Castle-Butte-Dr-Castle-Rock-CO-80109/52462216_zpid/"],
    "redfin": ["https://www.redfin.com/CO/Castle-Rock/2679-Castle-Butte-Dr-80109/home/35272805"],
    "errors": []
  },
  "success": true,
  "error_message": null
}
```

### POST /extract_from_urls
Extract property data from specific URLs (Step 2 of 2-step process).

**Request Body:**
```json
{
  "property_urls": [
    "https://www.zillow.com/homedetails/2679-Castle-Butte-Dr-Castle-Rock-CO-80109/52462216_zpid/",
    "https://www.redfin.com/CO/Castle-Rock/2679-Castle-Butte-Dr-80109/home/35272805"
  ],
  "address": "2679 Castle Butte Dr, Castle Rock, CO 80109"
}
```

**Response:** *(Same format as `/extract_home_info`)*

### Cache Management & Monitoring Endpoints

#### GET /cache_health
Get comprehensive cache performance and health metrics.

**Response:**
```json
{
  "health_status": "healthy",
  "performance_rating": "excellent",
  "memory_status": "low",
  "statistics": {
    "total_entries": 2,
    "valid_entries": 2,
    "cache_hit_potential": "100.0%",
    "search_cache": {"total_entries": 1, "valid_entries": 1},
    "extraction_cache": {"total_entries": 1, "valid_entries": 1}
  }
}
```

#### GET /credit_usage
Monitor credit usage and cache statistics with detailed breakdown.

#### POST /clear_cache
Clear all cached data (both URL discovery and extraction results).

#### POST /cleanup_cache
Remove only expired cache entries to optimize memory usage.

## Testing

```bash
# Install dependencies
uv sync

# Run the service
uv run python main.py

# Test complete extraction (end-to-end) - Brooklyn MultiFamily
curl -X POST "http://localhost:8000/extract_home_info" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "494 Warren Street",
    "city": "Brooklyn", 
    "state": "NY",
    "zip_code": ""
  }' | jq .

# Test with Colorado property (Single Family)
curl -X POST "http://localhost:8000/extract_home_info" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "2679 Castle Butte Dr",
    "city": "Castle Rock", 
    "state": "CO",
    "zip_code": "80109"
  }' | jq .

# Test URL discovery only
curl -X POST "http://localhost:8000/find_property_urls" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "115 Hilton Ave",
    "city": "Garden City",
    "state": "NY",
    "zip_code": "11530"
  }' | jq .

# Test extraction from specific URLs
curl -X POST "http://localhost:8000/extract_from_urls" \
  -H "Content-Type: application/json" \
  -d '{
    "property_urls": [
      "https://www.zillow.com/homedetails/115-Hilton-Ave-Garden-City-NY-11530/94720960_zpid/"
    ],
    "address": "115 Hilton Ave, Garden City, NY 11530"
  }' | jq .

# 🚀 Test Caching Performance (shows 287x speed improvement)
echo "First request (cache miss - will take 15+ seconds):"
time curl -X POST "http://localhost:8000/extract_home_info" \
  -H "Content-Type: application/json" \
  -d '{"address": "2679 Castle Butte Dr", "city": "Castle Rock", "state": "CO", "zip_code": "80109"}' \
  | jq '.success'

echo "Second request (cache hit - <60ms response!):"
time curl -X POST "http://localhost:8000/extract_home_info" \
  -H "Content-Type: application/json" \
  -d '{"address": "2679 Castle Butte Dr", "city": "Castle Rock", "state": "CO", "zip_code": "80109"}' \
  | jq '.success'

# Check cache statistics
curl -s "http://localhost:8000/cache_health" | jq .
```

## How It Works

### **🚀 Optimized Flow with Dual-Layer Caching**

1. **Extraction Cache Check**: First checks if complete property data is already cached (instant response if found)
2. **URL Discovery Cache**: If extraction cache misses, checks for cached property URLs (0 search credits)
3. **Priority-Based Search**: If URL cache misses, searches Zillow first with conservative credit usage (1-3 credits)
4. **Smart Validation**: Validates URLs to ensure exact address match using regex patterns and address parsing  
5. **Quality-Based Extraction**: Extracts property data and checks quality score (1-2 credits)
6. **Intelligent Backup Search**: Only searches Redfin if extraction quality < 25% threshold
7. **Comprehensive Caching**: Caches both URLs and extraction results for 24-hour instant future access
8. **Data Optimization**: Returns complete property information with source attribution

### **Performance Benefits**
- ⚡ **287x faster for cached addresses** (<60ms vs 16+ seconds)
- 🎯 **Instant responses** for previously searched properties 
- 💰 **Zero credits used** on cache hits (both URL discovery + extraction)
- 🔥 **2-9 credits per fresh search** (vs 60+ before optimization)
- 🛡️ **24-hour intelligent caching** balances freshness with performance
- 📈 **Massive cost savings** for popular addresses and repeat queries
- 🚀 **Production-grade performance** with sub-second cached responses

## Deployment

This service is configured for Railway deployment with the included Dockerfile.
